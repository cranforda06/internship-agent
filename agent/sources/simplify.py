"""Internships from the SimplifyJobs GitHub list.

SimplifyJobs keeps a community list of internships on GitHub
(github.com/SimplifyJobs/Summer2027-Internships). Besides the readable table,
it publishes the same list as a data file, which is what we download.

The list has title, company, location and link, but NOT the job description.
"""

from datetime import datetime, timezone

from agent.jobs import Job
from agent.sources.web import get_json

URL = "https://raw.githubusercontent.com/SimplifyJobs/{repo}/dev/.github/scripts/listings.json"


def fetch(term):
    """Return active listings for a term like "Summer 2027"."""
    repo = term.replace(" ", "") + "-Internships"  # "Summer2027-Internships"
    jobs = []
    for item in get_json(URL.format(repo=repo), timeout=60):
        # Skip closed/hidden listings and other terms (the list mixes terms).
        if not item.get("active") or not item.get("is_visible"):
            continue
        if term not in item.get("terms", []):
            continue
        posted = item.get("date_posted")  # seconds since 1970
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
