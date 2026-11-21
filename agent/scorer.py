import json
from datetime import date

from agent.filters import adjusted_score, is_preferred_location
from agent.llm import ClaudeError
from agent.sources.descriptions import fetch_description

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "description": "Fit from 0 to 100"},
        "summary": {"type": "string", "description": "One or two sentences on the fit"},
        "matching_strengths": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "summary", "matching_strengths", "gaps"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You evaluate how well an internship fits a specific student, \
based only on their resume. The student is an undergraduate Information \
Systems major.

What the student wants, in order of preference:
1. IT roles: IT operations and support, infrastructure, cloud, networking, \
systems administration, cybersecurity and IT risk/audit/governance, \
enterprise and business systems (ERP/CRM implementation and support, \
ServiceNow, Microsoft 365), IT project/PMO coordination, and technology \
consulting.
2. Business analyst and systems analyst roles inside IT: requirements \
gathering, process mapping, documentation, bridging business users and IT.
3. Data roles with a real IT or systems side (data management, data \
governance, BI platforms, database administration): acceptable, a step \
below 1 and 2.
Roles that are mainly data analytics, reporting, or dashboards with no IT or \
systems component are NOT what the student wants right now: score them no \
higher than 60, even if the student's skills match.
Roles centered on software development, data science/machine learning, or \
heavy programming are a poor fit even if the title sounds related. Let the \
role's actual day-to-day duties drive the score, not its title.

Do NOT factor location or relocation into the score. The student is willing \
to relocate, and location preferences are handled separately.

Score from 0 to 100:
- 85-100: the role's core duties line up directly with the student's \
experience and skills, and they meet the stated requirements.
- 65-84: a solid fit. Most requirements are met; gaps are learnable on the job.
- 40-64: partial fit. The role leans on skills or a major the student doesn't have.
- 0-39: poor fit (e.g. needs a CS/engineering degree, graduate degree, \
heavy coding, or a different field).

The student will read your answer. Write the summary, strengths, and gaps \
addressed to them as "you" (e.g. "Your DocClean project shows..."), never \
in the third person.

Be honest and specific. Name strengths and gaps using real items from the \
resume and the posting; don't invent skills the student lacks or requirements \
the posting doesn't state. Hard requirements the student clearly fails (degree \
level, graduation date window, required major) should pull the score down a lot.

Sometimes only the job title, company, and location are available. In that \
case, judge from the title alone, keep the score conservative (no higher \
than 75), and say in the summary that the description wasn't available."""


class ScoreError(Exception):
    pass


def fetch_missing_description(row):
    if row["description"] is not None:
        return row["description"]
    return fetch_description(row["link"]) or ""


def build_job_text(row, description):
    lines = [
        f"Company: {row['company']}",
        f"Title: {row['role']}",
        f"Location: {row['location'] or 'not listed'}",
    ]
    if description:
        lines.append(f"\nJob description:\n{description}")
    else:
        lines.append("\nJob description: NOT AVAILABLE (judge from the title only).")
    return "\n".join(lines)


class Scorer:
    def __init__(self, claude, resume_text, model, effort="low"):
        self.claude = claude
        self.resume_text = resume_text
        self.model = model
        self.effort = effort

    def score(self, job_text):
        prompt = (f"<resume>\n{self.resume_text}\n</resume>\n\n"
                  f"<job>\n{job_text}\n</job>\n\n"
                  "Score how well this internship fits this student.")
        try:
            result = self.claude.ask(self.model, SYSTEM_PROMPT, prompt, SCORE_SCHEMA,
                                     effort=self.effort, max_tokens=8000)
        except ClaudeError as e:
            raise ScoreError(str(e))
        result["score"] = max(0, min(100, int(result["score"])))
        return result


def score_found_jobs(config, tracker, scorer, limit, log=print, stop_after_good=None):
    min_score = config["scoring"]["min_fit_score"]
    search = config.get("search", {})
    preferred = search.get("preferred_locations", [])
    counts = {"good": 0, "skipped": 0, "errors": 0}

    rows = tracker.unscored()
    rows = sorted(rows, key=lambda r: not is_preferred_location(r["location"], preferred))

    for row in rows[:limit]:
        if stop_after_good is not None and counts["good"] >= stop_after_good:
            break
        description = fetch_missing_description(row)
        try:
            result = scorer.score(build_job_text(row, description))
        except (ScoreError, json.JSONDecodeError, KeyError, ValueError) as e:
            log(f"  ! {row['company']} - {row['role']}: {e}")
            counts["errors"] += 1
            continue

        good = adjusted_score(result["score"], row["location"], search) >= min_score
        result["had_description"] = bool(description)
        tracker.update_details(
            row["id"],
            fit_score=result["score"],
            fit_summary=json.dumps(result),
            scored_at=date.today().isoformat(),
            description=description or None,
        )
        if not good:
            tracker.update_status(row["id"], "skipped")
        counts["good" if good else "skipped"] += 1
        mark = "✓" if good else "·"
        star = "★" if is_preferred_location(row["location"], preferred) else " "
        log(f"  {mark} {result['score']:3} {star} {row['company'][:28]} - {row['role'][:50]}")
    return counts
