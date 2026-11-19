import re
from datetime import date, timedelta

from agent.jobs import Job
from agent.sources import web

PAGE_SIZE = 20
MAX_PAGES = 2
SEARCHES = ["intern 2027", "summer 2027"]


def posted_date(text, today=None):
    today = today or date.today()
    text = (text or "").lower()
    if "today" in text:
        days = 0
    elif "yesterday" in text:
        days = 1
    else:
        match = re.search(r"(\d+)\+?\s*days?", text)
        if not match:
            return ""
        days = int(match.group(1)) + (1 if "+" in text else 0)
    return (today - timedelta(days=days)).isoformat()


def _location(posting):
    text = posting.get("locationsText") or ""
    match = re.fullmatch(r"(\d+) Locations", text.strip())
    if not match:
        return text
    parts = (posting.get("externalPath") or "").split("/")
    main = parts[2] if len(parts) > 2 and parts[1] == "job" else ""
    main = re.sub(r"-([A-Z]{2})$", r", \1", main).replace("-", " ").strip()
    others = int(match.group(1)) - 1 if main else int(match.group(1))
    return f"{main}; and {others} more locations" if main else ""


def _search(api, text):
    postings = []
    for page in range(MAX_PAGES):
        response = web.request(
            "POST", api, headers={"Accept": "application/json"},
            json={"appliedFacets": {}, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE,
                  "searchText": text},
        )
        batch = response.json().get("jobPostings") or []
        postings.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    return postings


def fetch_site(site, company, max_age_days=30, today=None):
    today = today or date.today()
    host, site_name = site.strip("/").split("/")[:2]
    tenant = host.split(".")[0]
    api = f"https://{host}/wday/cxs/{tenant}/{site_name}/jobs"
    jobs, seen = [], set()
    for text in SEARCHES:
        for p in _search(api, text):
            path = p.get("externalPath")
            if not path or path in seen:
                continue
            seen.add(path)
            posted = posted_date(p.get("postedOn"), today)
            if posted and (today - date.fromisoformat(posted)).days > max_age_days:
                continue
            jobs.append(Job(
                company=company,
                title=p["title"].strip(),
                url=f"https://{host}/{site_name}{path}",
                location=_location(p),
                source="workday",
                posted=posted,
            ))
    return jobs
