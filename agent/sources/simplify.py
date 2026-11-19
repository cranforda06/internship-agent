from datetime import datetime, timezone

from agent.jobs import Job
from agent.sources.web import get_json

URL = "https://raw.githubusercontent.com/SimplifyJobs/{repo}/dev/.github/scripts/listings.json"


def fetch(term):
    repo = term.replace(" ", "") + "-Internships"
    jobs = []
    for item in get_json(URL.format(repo=repo), timeout=60):
        if not item.get("active") or not item.get("is_visible"):
            continue
        if term not in item.get("terms", []):
            continue
        posted = item.get("date_posted")
        jobs.append(Job(
            company=item["company_name"].strip(),
            title=item["title"].strip(),
            url=item["url"],
            location="; ".join(item.get("locations", [])),
            source="simplify",
            posted=(datetime.fromtimestamp(posted, tz=timezone.utc).date().isoformat()
                    if posted else ""),
        ))
    return jobs
