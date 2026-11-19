import csv
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STATUSES = [
    "found",
    "queued",
    "approved",
    "applied",
    "assessment",
    "interview",
    "offer",
    "rejected",
    "closed",
    "skipped",
]

ROLE_NOISE_WORDS = {
    "summer", "fall", "spring", "winter", "internship", "intern", "interns",
    "remote", "hybrid", "onsite", "the",
}

COMPANY_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc"}

TRACKING_PARAMS = {"gh_src", "lever-source", "lever-origin", "source", "src", "ref", "referrer"}


EXTRA_COLUMNS = {
    "location": "TEXT",
    "source": "TEXT",
    "description": "TEXT",
    "posted": "TEXT",
    "fit_score": "INTEGER",
    "fit_summary": "TEXT",
    "scored_at": "TEXT",
    "tailored_dir": "TEXT",
    "tailor_report": "TEXT",
}

APPLIED_STATUSES = {"applied", "assessment", "interview", "offer", "rejected", "closed"}


class DuplicateError(Exception):
    def __init__(self, existing):
        self.existing = existing
        super().__init__(
            f"Already tracked: {existing['company']} - {existing['role']} "
            f"(status: {existing['status']})"
        )


def _clean_words(text):
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
    a, b = key_a.split(), key_b.split()
    shorter, longer = sorted([a, b], key=len)
    return bool(shorter) and longer[:len(shorter)] == shorter


def normalize_role(role):
    text = role.lower()
    text = re.sub(r"\b(req|requisition|app|application|job)\s*(id|#)", " ", text)
    text = " ".join(chunk for chunk in text.split() if not re.search(r"\d", chunk))
    words = {w for w in _clean_words(text) if w not in ROLE_NOISE_WORDS}
    return " ".join(sorted(words))


def normalize_link(link):
    link = (link or "").strip()
    if not link:
        return None
    parts = urlsplit(link)
    params = sorted(
        (k, v) for k, v in parse_qsl(parts.query)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    )
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    if host.endswith("myworkdayjobs.com"):
        path = re.sub(r"^/[a-z]{2}-[A-Z]{2}(?=/)", "", path)
    return urlunsplit(("https", host, path, urlencode(params), ""))


def parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Couldn't read the date '{value}'. Use YYYY-MM-DD, like 2026-10-15.")


class Tracker:
    def __init__(self, db_path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_table()
        self._refresh_keys()

    def _create_table(self):
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
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(applications)")}
        for column, kind in EXTRA_COLUMNS.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE applications ADD COLUMN {column} {kind}")
        self.conn.commit()

    def _refresh_keys(self):
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
                pass

    def find_existing(self, company, role, link=None):
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
        company, role = company.strip(), role.strip()
        if not company or not role:
            raise ValueError("Company and role are both required.")
        if status not in STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(STATUSES)}")

        existing = self.find_existing(company, role, link)
        if existing:
            raise DuplicateError(existing)

        try:
            with self.conn:
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
            raise DuplicateError(self.find_existing(company, role, link))
        if details:
            self.update_details(cursor.lastrowid, **details)
        return cursor.lastrowid

    def update_details(self, app_id, **details):
        unknown = set(details) - set(EXTRA_COLUMNS)
        if unknown:
            raise ValueError(f"Unknown column(s): {', '.join(sorted(unknown))}")
        assignments = ", ".join(f"{column} = ?" for column in details)
        with self.conn:
            self.conn.execute(
                f"UPDATE applications SET {assignments} WHERE id = ?",
                (*details.values(), app_id),
            )

    def get(self, app_id):
        return self.conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()

    def unscored(self, limit=None):
        return self.conn.execute(
            "SELECT * FROM applications WHERE status = 'found' AND fit_score IS NULL "
            "ORDER BY posted DESC, id DESC LIMIT ?", (-1 if limit is None else limit,)
        ).fetchall()

    def missing_descriptions(self):
        return self.conn.execute(
            "SELECT * FROM applications WHERE status = 'found' AND fit_score IS NULL "
            "AND description IS NULL ORDER BY id"
        ).fetchall()

    def count_unscored(self):
        return self.conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status = 'found' AND fit_score IS NULL"
        ).fetchone()[0]

    def scored_matches(self):
        return self.conn.execute(
            "SELECT * FROM applications WHERE status = 'found' AND fit_score IS NOT NULL "
            "ORDER BY fit_score DESC, id"
        ).fetchall()

    def similar_application(self, company, role):
        new_words = set(normalize_role(role).split())
        for past in self.applied_at_company(company):
            past_words = set(past["role_key"].split())
            shorter, longer = sorted([new_words, past_words], key=len)
            if len(shorter) >= 2 and shorter <= longer:
                return past
        return None

    def applied_at_company(self, company, exclude_id=None):
        placeholders = ", ".join("?" for _ in APPLIED_STATUSES)
        rows = self.conn.execute(
            f"SELECT * FROM applications WHERE id != ? AND status IN ({placeholders})",
            (exclude_id or -1, *sorted(APPLIED_STATUSES)),
        ).fetchall()
        key = normalize_company(company)
        return [r for r in rows if same_company(r["company_key"], key)]

    def update_status(self, app_id, status):
        if status not in STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(STATUSES)}")
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE applications SET status = ? WHERE id = ?", (status, app_id)
            )
            if status == "applied":
                self.conn.execute(
                    "UPDATE applications SET date_applied = ? "
                    "WHERE id = ? AND date_applied IS NULL",
                    (date.today().isoformat(), app_id),
                )
        if cursor.rowcount == 0:
            raise ValueError(f"No application with id {app_id}.")

    def list_all(self, status=None):
        if status:
            return self.conn.execute(
                "SELECT * FROM applications WHERE status = ? ORDER BY id DESC", (status,)
            ).fetchall()
        return self.conn.execute("SELECT * FROM applications ORDER BY id DESC").fetchall()

    def import_csv(self, csv_path):
        added, duplicates, errors = 0, [], []
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            for line_num, row in enumerate(csv.DictReader(f), start=2):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                try:
                    self.add(
                        company=row.get("company", ""),
                        role=row.get("role", ""),
                        link=row.get("link"),
                        status=(row.get("status") or "applied").lower(),
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
