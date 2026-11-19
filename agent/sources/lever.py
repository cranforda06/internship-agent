import re
from datetime import datetime, timezone

from agent.jobs import Job
from agent.sources.web import get_json, html_to_text

API = "https://api.lever.co/v0/postings"

URL_PATTERN = re.compile(r"jobs\.lever\.co/([\w-]+)/([0-9a-f-]{36})")


def _description(data):
    parts = [data.get("descriptionPlain", "")]
    for section in data.get("lists", []):
        parts.append(f"{section.get('text', '')}:\n{html_to_text(section.get('content', ''))}")
    parts.append(data.get("additionalPlain", ""))
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _to_job(data, company):
    categories = data.get("categories") or {}
    locations = categories.get("allLocations") or [categories.get("location", "")]
    created = data.get("createdAt")
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
    return [_to_job(j, company) for j in get_json(f"{API}/{company}?mode=json")]


def fetch_description(url):
    match = URL_PATTERN.search(url)
    if not match:
        return None
    company, job_id = match.groups()
    return _description(get_json(f"{API}/{company}/{job_id}"))
