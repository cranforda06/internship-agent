"""Get a job's full description from the site that hosts it.

The SimplifyJobs list only gives us a link. Most companies post their jobs
through a hiring system (Workday, Oracle, Greenhouse...), and each of those
systems has a public, read-only data feed behind its job pages. That's the
same data your browser loads when you open the page, just without the page
around it. We read that feed instead of scraping the page.

Use: fetch_description(url) -> description text, or None if we can't get it.
"""

import re
from urllib.parse import quote, urlsplit

from agent.sources import greenhouse, lever
from agent.sources.web import get_json, html_to_text


def _workday(url):
    # https://boeing.wd1.myworkdayjobs.com/[en-US/]INTERN/job/<location>/<title_id>
    #   -> https://boeing.wd1.myworkdayjobs.com/wday/cxs/boeing/INTERN/job/<location>/<title_id>
    parts = urlsplit(url)
    if "myworkdayjobs.com" not in parts.netloc:
        return None
    path = [p for p in parts.path.split("/") if p]
    if path and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", path[0]):  # drop "en-US"
        path = path[1:]
    if len(path) < 3 or "job" not in path:
        return None
    tenant = parts.netloc.split(".")[0]
    api = f"https://{parts.netloc}/wday/cxs/{tenant}/{'/'.join(path)}"
    info = get_json(api).get("jobPostingInfo", {})
    return html_to_text(info.get("jobDescription", ""))


def _oracle(url):
    # https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210773869
    match = re.search(r"https://([^/]*oraclecloud\.com)/.*/sites/([^/]+)/job/(\d+)", url)
    if not match:
        return None
    host, site, job_id = match.groups()
    api = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
           f"?expand=all&onlyData=true&finder=ById;Id=%22{job_id}%22,siteNumber={quote(site)}")
    items = get_json(api).get("items", [])
    if not items:
        return None
    item = items[0]
    sections = [item.get(k) for k in
                ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")]
    return "\n\n".join(html_to_text(s) for s in sections if s)


def _ashby(url):
    # https://jobs.ashbyhq.com/<company>/<job id>[/application]
    match = re.search(r"jobs\.ashbyhq\.com/([^/?]+)/([0-9a-f-]{36})", url)
    if not match:
        return None
    company, job_id = match.groups()
    for job in get_json(f"https://api.ashbyhq.com/posting-api/job-board/{company}").get("jobs", []):
        if job.get("id") == job_id:
            return job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml", ""))
    return None


def _smartrecruiters(url):
    # https://jobs.smartrecruiters.com/<Company>/<posting id>[-title]
    match = re.search(r"smartrecruiters\.com/([^/?]+)/(\d+)", url)
    if not match:
        return None
    company, posting_id = match.groups()
    data = get_json(f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}")
    sections = (data.get("jobAd") or {}).get("sections") or {}
    parts = []
    for key in ("jobDescription", "qualifications", "additionalInformation"):
        section = sections.get(key) or {}
        if section.get("text"):
            parts.append(f"{section.get('title', '')}\n{html_to_text(section['text'])}".strip())
    return "\n\n".join(parts) or None


# Each fetcher returns None right away if the link isn't from its site.
FETCHERS = [
    greenhouse.fetch_description,
    lever.fetch_description,
    _workday,
    _oracle,
    _ashby,
    _smartrecruiters,
]


def fetch_description(url):
    """Return the job description text, or None if we can't get it.

    Errors (posting taken down, site changed) also return None, so one bad
    link never stops the agent.
    """
    if not url:
        return None
    for fetcher in FETCHERS:
        try:
            text = fetcher(url)
        except Exception:
            return None  # right site, but the request failed
        if text:
            return text.strip()
    return None


def site_name(url):
    """Short name of the hiring system behind a link, for summaries."""
    host = urlsplit(url or "").netloc
    for key, name in [("myworkdayjobs", "Workday"), ("oraclecloud", "Oracle"),
                      ("greenhouse", "Greenhouse"), ("lever.co", "Lever"),
                      ("ashbyhq", "Ashby"), ("smartrecruiters", "SmartRecruiters")]:
        if key in host:
            return name
    return "other"
