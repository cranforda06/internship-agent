"""Internships from public Greenhouse job boards.

Every company on Greenhouse has a public, read-only feed meant for programs:
    https://boards-api.greenhouse.io/v1/boards/<board name>/jobs
The "board name" is the part after greenhouse.io/ in a company's job links,
e.g. job-boards.greenhouse.io/appian/jobs/123 -> "appian".
"""

import re

from agent.jobs import Job
from agent.sources.web import get_json, html_to_text

API = "https://boards-api.greenhouse.io/v1/boards"

# Matches job links like boards.greenhouse.io/appian/jobs/12345
URL_PATTERN = re.compile(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)")


def _to_job(data, board):
    return Job(
        company=data.get("company_name") or board,
        title=data["title"].strip(),
        url=data["absolute_url"],
        location=(data.get("location") or {}).get("name", ""),
        source="greenhouse",
        description=html_to_text(data.get("content", "")),
        posted=(data.get("first_published") or data.get("updated_at") or "")[:10],
    )


def fetch_board(board):
    """Return every job on one company's Greenhouse board."""
    data = get_json(f"{API}/{board}/jobs?content=true")
    return [_to_job(j, board) for j in data["jobs"]]


def fetch_description(url):
    """Get the full description for one Greenhouse job link, or None."""
    match = URL_PATTERN.search(url)
    if not match:
        return None
    board, job_id = match.groups()
    return html_to_text(get_json(f"{API}/{board}/jobs/{job_id}").get("content", ""))
