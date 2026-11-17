"""The application tracker: a small SQLite database of every internship.

SQLite is a database stored in a single file (data/applications.db). Python
has it built in, so there's nothing extra to install.

The key job of this file is preventing duplicates. A job counts as "already
in the tracker" if EITHER:
  1. its link matches one we've saved, or
  2. its company + role match one we've saved, after cleanup, so that
     "Data Analyst Intern - Summer 2027" at "Acme Inc." matches
     "data analyst intern" at "Acme".
"""

import csv
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Every status a job can have, roughly in the order it moves through them.
STATUSES = [
    "found",       # the agent found it, you haven't decided yet
    "queued",      # resume tailored, waiting for your review
    "approved",    # you said yes, not submitted yet
    "applied",
    "assessment",  # they sent an online test / assessment
    "interview",
    "offer",
    "rejected",
    "closed",      # ended without a decision (e.g. missed an assessment deadline)
    "skipped",     # you (or the fit score) said no
]

# Words removed from role titles before comparing, because they don't change
# which job it is ("Data Analyst Intern, Summer 2027" == "Data Analyst Intern").
ROLE_NOISE_WORDS = {
    "summer", "fall", "spring", "winter", "internship", "intern", "interns",
    "remote", "hybrid", "onsite", "the",
}

# Endings removed from company names ("Acme Inc." == "Acme").
COMPANY_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc"}

# Link parameters that only track where you clicked from. Removing them means
# the same job page matches even if you reached it from different sites.
TRACKING_PARAMS = {"gh_src", "lever-source", "lever-origin", "source", "src", "ref", "referrer"}


EXTRA_COLUMNS = {
    "location": "TEXT",
    "source": "TEXT",         # where the agent found it: simplify, greenhouse, lever
    "description": "TEXT",    # the job description, used for scoring and tailoring
    "posted": "TEXT",         # date the job was posted
    "fit_score": "INTEGER",   # 0-100, from Claude
    "fit_summary": "TEXT",    # Claude's reasons, stored as JSON text
    "scored_at": "TEXT",
    "tailored_dir": "TEXT",   # folder with the tailored resume files
    "tailor_report": "TEXT",  # what changed + truthfulness check results (JSON)
}

# Statuses that mean you actually applied somewhere (vs. the agent just finding it).
APPLIED_STATUSES = {"applied", "assessment", "interview", "offer", "rejected", "closed"}


class DuplicateError(Exception):
    """Raised when you try to add a job that's already in the tracker."""

    def __init__(self, existing):
        self.existing = existing  # the row that's already there
        super().__init__(
            f"Already tracked: {existing['company']} - {existing['role']} "
            f"(status: {existing['status']})"
        )


# ---------------------------------------------------------------------------
# Cleanup ("normalize") helpers. These turn messy text into a standard form
# so two versions of the same thing compare as equal.
# ---------------------------------------------------------------------------

def _clean_words(text):
    """Lowercase, swap & for 'and', and replace punctuation with spaces."""
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.split()


def normalize_company(company):
    words = _clean_words(company)
    if words and words[0] == "the":
        words = words[1:]
    while words and words[-1] in COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def same_company(key_a, key_b):
    """Looser company match: one name starts with the other, word by word.

    "navy federal" matches "navy federal credit union". Used for warnings
    and "probably already applied" checks, not for exact duplicates.
    """
    a, b = key_a.split(), key_b.split()
    shorter, longer = sorted([a, b], key=len)
    return bool(shorter) and longer[:len(shorter)] == shorter


def normalize_role(role):
    text = role.lower()
    # Drop labels like "Req ID" / "App ID" / "Job ID" (the numbers go next).
    text = re.sub(r"\b(req|requisition|app|application|job)\s*(id|#)", " ", text)
    # Drop any chunk containing a digit: job IDs (R171828, 10078973-WD,
    # (13375)) and years (2027). Job boards often leave these out of the
    # title, so keeping them would stop the same job from matching.
    text = " ".join(chunk for chunk in text.split() if not re.search(r"\d", chunk))
    words = {w for w in _clean_words(text) if w not in ROLE_NOISE_WORDS}
    # Sorted, so word order doesn't matter: "BI Analyst Summer Associate"
    # and "Summer Associate (BI Analyst)" give the same key.
    return " ".join(sorted(words))


def normalize_link(link):
    """Standardize a URL. Returns None for an empty link."""
    link = (link or "").strip()
    if not link:
        return None
    parts = urlsplit(link)
    # Keep real parameters (Greenhouse uses ?gh_jid=123 to identify the job)
    # but drop tracking ones, and sort them so their order doesn't matter.
    params = sorted(
        (k, v) for k, v in parse_qsl(parts.query)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    )
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    if host.endswith("myworkdayjobs.com"):
        # The same Workday job can be linked with or without "/en-US".
        path = re.sub(r"^/[a-z]{2}-[A-Z]{2}(?=/)", "", path)
    return urlunsplit(("https", host, path, urlencode(params), ""))


def parse_date(value):
    """Accept 2026-10-15, 10/15/2026 or 10/15/26 and return '2026-10-15'."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Couldn't read the date '{value}'. Use YYYY-MM-DD, like 2026-10-15.")


# ---------------------------------------------------------------------------
# The tracker itself
# ---------------------------------------------------------------------------

class Tracker:
    def __init__(self, db_path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False lets the review page's web server use this
        # connection. That server handles one request at a time, so it's safe.
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        # Lets us read columns by name: row["company"] instead of row[1].
        self.conn.row_factory = sqlite3.Row
        self._create_table()
        self._refresh_keys()

    def _create_table(self):
        # The UNIQUE rules make the database itself refuse duplicates,
        # as a safety net in case the code above ever misses one.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                company      TEXT NOT NULL,
                role         TEXT NOT NULL,
                link         TEXT,
                date_applied TEXT,
                status       TEXT NOT NULL,
                notes        TEXT,
                date_added   TEXT NOT NULL,
                company_key  TEXT NOT NULL,
                role_key     TEXT NOT NULL,
                link_key     TEXT UNIQUE,
                UNIQUE (company_key, role_key)
            )
        """)
        # Columns added in Phase 2. Older databases get them added here, so
        # your existing data is kept.
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(applications)")}
        for column, kind in EXTRA_COLUMNS.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE applications ADD COLUMN {column} {kind}")
        self.conn.commit()

    def _refresh_keys(self):
        """Recompute the cleaned-up matching keys for every saved job.

        The keys are saved when a job is added. If the cleanup rules above
        change later, old keys would be out of date and duplicates could
        slip through. This keeps them current each time the tracker opens.
        """
        rows = self.conn.execute("SELECT id, company, role, link FROM applications").fetchall()
        for r in rows:
            try:
                with self.conn:
                    self.conn.execute(
                        "UPDATE applications SET company_key = ?, role_key = ?, link_key = ? "
                        "WHERE id = ?",
                        (normalize_company(r["company"]), normalize_role(r["role"]),
                         normalize_link(r["link"]), r["id"]),
                    )
            except sqlite3.IntegrityError:
                # Under the new rules this job matches another saved job.
                # Leave its old keys alone rather than lose either entry.
                pass

    def find_existing(self, company, role, link=None):
        """Return the matching saved job, or None if this job is new.

        This is the check that runs before every application.
        """
        link_key = normalize_link(link)
        if link_key:
            row = self.conn.execute(
                "SELECT * FROM applications WHERE link_key = ?", (link_key,)
            ).fetchone()
            if row:
                return row
        return self.conn.execute(
            "SELECT * FROM applications WHERE company_key = ? AND role_key = ?",
            (normalize_company(company), normalize_role(role)),
        ).fetchone()

    def add(self, company, role, link=None, status="applied", date_applied=None, notes=None,
            **details):
        """Save a new job. Raises DuplicateError if it's already tracked.

        `details` can hold any of the EXTRA_COLUMNS, e.g. location="Richmond, VA".
        """
        company, role = company.strip(), role.strip()
        if not company or not role:
            raise ValueError("Company and role are both required.")
        if status not in STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(STATUSES)}")

        existing = self.find_existing(company, role, link)
        if existing:
            raise DuplicateError(existing)

        try:
            with self.conn:  # "with" saves the change, or undoes it on error
                cursor = self.conn.execute(
                    """INSERT INTO applications
                       (company, role, link, date_applied, status, notes,
                        date_added, company_key, role_key, link_key)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (company, role, (link or "").strip() or None, date_applied, status,
                     notes, date.today().isoformat(), normalize_company(company),
                     normalize_role(role), normalize_link(link)),
                )
        except sqlite3.IntegrityError:
            # The database's UNIQUE rule caught a duplicate.
            raise DuplicateError(self.find_existing(company, role, link))
        if details:
            self.update_details(cursor.lastrowid, **details)
        return cursor.lastrowid

    def update_details(self, app_id, **details):
        """Fill in extra columns, e.g. update_details(5, fit_score=80)."""
        unknown = set(details) - set(EXTRA_COLUMNS)
        if unknown:
            raise ValueError(f"Unknown column(s): {', '.join(sorted(unknown))}")
        # Column names come from EXTRA_COLUMNS (checked above), never from
        # user input, so building the SQL text this way is safe.
        assignments = ", ".join(f"{column} = ?" for column in details)
        with self.conn:
            self.conn.execute(
                f"UPDATE applications SET {assignments} WHERE id = ?",
                (*details.values(), app_id),
            )

    def get(self, app_id):
        return self.conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()

    def unscored(self, limit=None):
        """Found jobs that haven't been scored yet, newest postings first.

        limit=None returns all of them.
        """
        return self.conn.execute(
            "SELECT * FROM applications WHERE status = 'found' AND fit_score IS NULL "
            "ORDER BY posted DESC, id DESC LIMIT ?", (-1 if limit is None else limit,)
        ).fetchall()

    def missing_descriptions(self):
        """Found, unscored jobs whose description we haven't tried to get yet.

        description is NULL = not tried yet; "" = tried, not available.
        """
        return self.conn.execute(
            "SELECT * FROM applications WHERE status = 'found' AND fit_score IS NULL "
            "AND description IS NULL ORDER BY id"
        ).fetchall()

    def count_unscored(self):
        return self.conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status = 'found' AND fit_score IS NULL"
        ).fetchone()[0]

    def scored_matches(self):
        """Found jobs that passed scoring, best score first."""
        return self.conn.execute(
            "SELECT * FROM applications WHERE status = 'found' AND fit_score IS NOT NULL "
            "ORDER BY fit_score DESC, id"
        ).fetchall()

    def similar_application(self, company, role):
        """Return a past application at this company whose title is probably
        the same job, or None.

        "Probably the same" = every word of the shorter title appears in the
        longer one, and the shorter one has at least 2 words. For example
        "Business Systems Analyst Intern" vs. "Summer Associate Internship
        (Business Systems Analyst)". Only checks jobs you actually applied to.
        """
        new_words = set(normalize_role(role).split())
        for past in self.applied_at_company(company):
            past_words = set(past["role_key"].split())
            shorter, longer = sorted([new_words, past_words], key=len)
            if len(shorter) >= 2 and shorter <= longer:
                return past
        return None

    def applied_at_company(self, company, exclude_id=None):
        """Jobs you've applied to at this company (any role).

        Used to warn you, e.g. if a past application's role was unknown.
        """
        placeholders = ", ".join("?" for _ in APPLIED_STATUSES)
        rows = self.conn.execute(
            f"SELECT * FROM applications WHERE id != ? AND status IN ({placeholders})",
            (exclude_id or -1, *sorted(APPLIED_STATUSES)),
        ).fetchall()
        key = normalize_company(company)
        return [r for r in rows if same_company(r["company_key"], key)]

    def update_status(self, app_id, status):
        """Change a job's status, e.g. from 'applied' to 'interview'."""
        if status not in STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(STATUSES)}")
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE applications SET status = ? WHERE id = ?", (status, app_id)
            )
            # Applying for real fills in the date if it was missing.
            if status == "applied":
                self.conn.execute(
                    "UPDATE applications SET date_applied = ? "
                    "WHERE id = ? AND date_applied IS NULL",
                    (date.today().isoformat(), app_id),
                )
        if cursor.rowcount == 0:
            raise ValueError(f"No application with id {app_id}.")

    def list_all(self, status=None):
        """Return every saved job (or only ones with a given status), newest first."""
        if status:
            return self.conn.execute(
                "SELECT * FROM applications WHERE status = ? ORDER BY id DESC", (status,)
            ).fetchall()
        return self.conn.execute("SELECT * FROM applications ORDER BY id DESC").fetchall()

    def import_csv(self, csv_path):
        """Add jobs from a CSV with columns: company, role, link, date, status, notes.

        Only company and role are required. Status defaults to 'applied'.
        Returns (number added, list of rows skipped as duplicates, list of errors).
        """
        added, duplicates, errors = 0, [], []
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            # start=2 because line 1 is the header row
            for line_num, row in enumerate(csv.DictReader(f), start=2):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                try:
                    self.add(
                        company=row.get("company", ""),
                        role=row.get("role", ""),
                        link=row.get("link"),
                        status=(row.get("status") or "applied").lower(),
                        # Accept either "date" or "date_applied" as the column name.
                        date_applied=parse_date(row.get("date") or row.get("date_applied")),
                        notes=row.get("notes") or None,
                    )
                    added += 1
                except DuplicateError:
                    duplicates.append(f"line {line_num}: {row.get('company')} - {row.get('role')}")
                except ValueError as e:
                    errors.append(f"line {line_num}: {e}")
        return added, duplicates, errors

    def close(self):
        self.conn.close()
