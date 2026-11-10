"""Internships from public Lever job boards.

Like Greenhouse, Lever gives each company a public, read-only feed:
    https://api.lever.co/v0/postings/<company>?mode=json
The company name is the part after jobs.lever.co/ in its job links.
"""

import re
from datetime import datetime, timezone

from agent.jobs import Job
from agent.sources.web import get_json, html_to_text

API = "https://api.lever.co/v0/postings"

# Matches job links like jobs.lever.co/palantir/6ed76ce8-4156-...
URL_PATTERN = re.compile(r"jobs\.lever\.co/([\w-]+)/([0-9a-f-]{36})")


def _description(data):
    """Lever splits descriptions into parts. Glue them back together."""
    parts = [data.get("descriptionPlain", "")]
    for section in data.get("lists", []):  # e.g. "Requirements", "Responsibilities"
        parts.append(f"{section.get('text', '')}:\n{html_to_text(section.get('content', ''))}")
    parts.append(data.get("additionalPlain", ""))
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _to_job(data, company):
    categories = data.get("categories") or {}
    locations = categories.get("allLocations") or [categories.get("location", "")]
    created = data.get("createdAt")  # milliseconds since 1970
    posted = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).date().isoformat()
              if created else "")
    return Job(
        company=company,
        title=data["text"].strip(),
        url=data["hostedUrl"],
        location="; ".join(l for l in locations if l),
        source="lever",
        description=_description(data),
        posted=posted,
    )


def fetch_board(company):
    """Return every job on one company's Lever board."""
    return [_to_job(j, company) for j in get_json(f"{API}/{company}?mode=json")]


def fetch_description(url):
    """Get the full description for one Lever job link, or None."""
    match = URL_PATTERN.search(url)
    if not match:
        return None
    company, job_id = match.groups()
    return _description(get_json(f"{API}/{company}/{job_id}"))
