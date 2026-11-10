"""Phase 3: tailor your resume to one job, then check it for truthfulness.

Three steps for each job:
1. TAILOR: Claude rewrites your resume for the job. It may reorder sections
   and bullets, reword bullets using the job's vocabulary, and cut the least
   relevant lines. It may NOT add anything that isn't already in your resume.
2. CHECK (AI): a second, separate Claude request compares the tailored
   resume to the original line by line and lists any claim it can't trace
   back to the original.
3. CHECK (code): plain Python double-checks the facts that matter most:
   your name/contact line, every job title/company/date line, and every
   number (50+, 100%, 3.80...) must appear exactly as in the original.

Anything flagged is shown to you in the review step. Nothing is hidden.
"""

import json
import re
from datetime import date
from pathlib import Path

from agent import render
from agent.llm import ClaudeError

TAILOR_SCHEMA = {
    "type": "object",
    "properties": {
        "resume_markdown": {"type": "string"},
        "changes": {"type": "array", "items": {"type": "string"},
                    "description": "Short list of what you changed and why"},
    },
    "required": ["resume_markdown", "changes"],
    "additionalProperties": False,
}

TAILOR_PROMPT = """You tailor a student's resume to one specific internship. \
The student will send it to a real employer, so it must stay 100% truthful.

ALLOWED:
- Reorder sections and bullets so the most relevant experience comes first.
- Reword a bullet to use the job posting's vocabulary, ONLY when the \
underlying fact stays the same (e.g. "gather requirements" -> "elicit \
business requirements" is fine if they gathered requirements).
- Reorder items inside the skills lines to lead with what the job asks for.
- Remove lines that are least relevant (e.g. hobbies, a weaker bullet) to \
keep the resume to one page (roughly 450-550 words).

NOT ALLOWED (never, even if the job asks for it):
- Adding any skill, tool, certification, course, technology, or responsibility \
that isn't already in the resume.
- Adding, changing, or rounding any number, percentage, date, GPA, or count.
- Changing any job title, company, organization, location, or date.
- Inflating scope (e.g. "helped" -> "led", "a colleague and I" -> "I", \
"coursework" -> "professional experience").

FORMAT RULES (the resume is turned into a PDF by code that depends on these):
- Keep the exact Markdown layout of the original: "# Name", the contact \
line(s), "## Section" headings, "### " entry lines, and "- " bullets.
- Copy the name line, the contact line(s), and every "### " line you keep \
EXACTLY, character for character.
- Don't add new sections or new "### " lines.

In "changes", list each meaningful change in a few words \
(e.g. "Moved Work Experience above Research to lead with DocClean")."""

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tailored_text": {"type": "string", "description": "The exact phrase from the tailored resume"},
                    "problem": {"type": "string", "description": "Why it isn't supported by the original"},
                    "severity": {"type": "string", "enum": ["fabricated", "exaggerated", "minor"]},
                },
                "required": ["tailored_text", "problem", "severity"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["issues"],
    "additionalProperties": False,
}

CHECK_PROMPT = """You are a strict fact-checker. You get a student's ORIGINAL \
resume and a TAILORED version. Find every claim in the tailored version that \
is not supported by the original.

Flag:
- fabricated: a skill, tool, certification, responsibility, result, number, \
title, or experience that does not appear in the original at all.
- exaggerated: something in the original made bigger: more ownership \
("helped" -> "led"), larger scope, stronger results, or a team effort \
presented as solo work.
- minor: a wording change that slightly shifts meaning but is arguably fine.

Do NOT flag: reordering, removed lines, or rewording that keeps the same \
meaning. If everything is supported, return an empty issues list."""

NUMBER = re.compile(r"\d[\d,.]*\+?%?")


def code_checks(original, tailored):
    """Fact checks that don't need AI. Returns a list of problems (strings)."""
    problems = []
    orig_lines = [l.strip() for l in original.splitlines() if l.strip()]
    new_lines = [l.strip() for l in tailored.splitlines() if l.strip()]

    # 1. Name and contact line(s) must be identical.
    header_len = next((i for i, l in enumerate(orig_lines) if l.startswith("## ")), 2)
    if new_lines[:header_len] != orig_lines[:header_len]:
        problems.append("Name or contact line was changed.")

    # 2. Every entry line (title / company / dates) must exist in the original.
    original_entries = {l for l in orig_lines if l.startswith("### ")}
    for line in new_lines:
        if line.startswith("### ") and line not in original_entries:
            problems.append(f"Entry line not in your original resume: {line[4:]}")

    # 3. Every number must appear somewhere in the original. Compare just the
    #    digits ("50+" vs "50", "2026," vs "2026") so punctuation isn't flagged.
    def core(n):
        return n.rstrip(".,").replace("+", "").replace("%", "")
    original_numbers = {core(n) for n in NUMBER.findall(original)}
    for number in sorted({core(n) for n in NUMBER.findall(tailored)} - original_numbers):
        problems.append(f"Number not in your original resume: {number}")
    return problems


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def _file_name(original):
    """'# Alex Cranford' -> 'Alex_Cranford_Resume'"""
    first = next((l for l in original.splitlines() if l.startswith("# ")), "# Resume")
    return re.sub(r"\W+", "_", first[2:].strip()).strip("_") + "_Resume"


def tailor_job(claude, settings, original, row, out_root):
    """Tailor the resume for one tracker row. Returns the report dict.

    Saves resume.md, a PDF, a Word file, and report.json into a folder
    under out_root, named after the job.
    """
    job_text = (f"Company: {row['company']}\nTitle: {row['role']}\n"
                f"Location: {row['location'] or 'n/a'}\n\n"
                f"Job description:\n{row['description'] or 'NOT AVAILABLE (tailor to the title).'}")

    tailored = claude.ask(
        settings["model"], TAILOR_PROMPT,
        f"<original_resume>\n{original}\n</original_resume>\n\n<job>\n{job_text}\n</job>",
        TAILOR_SCHEMA, effort=settings.get("effort", "medium"),
    )
    resume_md = tailored["resume_markdown"].strip() + "\n"

    check = claude.ask(
        settings["model"], CHECK_PROMPT,
        f"<original_resume>\n{original}\n</original_resume>\n\n"
        f"<tailored_resume>\n{resume_md}\n</tailored_resume>",
        CHECK_SCHEMA, effort=settings.get("check_effort", "medium"),
    )

    folder = Path(out_root) / f"{row['id']}-{_slug(row['company'])}-{_slug(row['role'])}"
    folder.mkdir(parents=True, exist_ok=True)
    name = _file_name(original)
    (folder / "resume.md").write_text(resume_md, encoding="utf-8")
    pages = render.to_pdf(resume_md, folder / f"{name}.pdf")
    render.to_docx(resume_md, folder / f"{name}.docx")

    report = {
        "job_id": row["id"],
        "date": date.today().isoformat(),
        "changes": tailored["changes"],
        "ai_check_issues": check["issues"],
        "code_check_problems": code_checks(original, resume_md),
        "pages": pages,
        "pdf": str(folder / f"{name}.pdf"),
        "docx": str(folder / f"{name}.docx"),
    }
    serious = [i for i in report["ai_check_issues"] if i["severity"] != "minor"]
    report["needs_attention"] = bool(serious or report["code_check_problems"] or pages > 1)
    (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report, str(folder)


def tailor_queue(config, tracker, claude, original, count, log=print):
    """Tailor the `count` best matches that aren't queued yet.

    Each one moves from status "found" to "queued" (ready for your review).
    """
    from agent.filters import adjusted_score

    search, settings = config["search"], config["tailoring"]
    matches = sorted(tracker.scored_matches(),
                     key=lambda r: -adjusted_score(r["fit_score"], r["location"], search))
    done = 0
    for row in matches[:count]:
        try:
            report, folder = tailor_job(claude, settings, original, row, config["output_dir"])
        except (ClaudeError, KeyError) as e:
            log(f"  ! {row['company']} - {row['role']}: {e}")
            continue
        tracker.update_details(row["id"], tailored_dir=folder, tailor_report=json.dumps(report))
        tracker.update_status(row["id"], "queued")
        done += 1
        flag = "⚠ check flagged items" if report["needs_attention"] else "✓ passed checks"
        log(f"  {flag:24} {row['company'][:28]} - {row['role'][:45]}")
    return done
