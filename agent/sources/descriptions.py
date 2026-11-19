import re
from urllib.parse import quote, urlsplit

from agent.sources import greenhouse, lever
from agent.sources.web import get_json, html_to_text


def _workday(url):
    parts = urlsplit(url)
    if "myworkdayjobs.com" not in parts.netloc:
        return None
    path = [p for p in parts.path.split("/") if p]
    if path and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", path[0]):
        path = path[1:]
    if len(path) < 3 or "job" not in path:
        return None
    tenant = parts.netloc.split(".")[0]
    api = f"https://{parts.netloc}/wday/cxs/{tenant}/{'/'.join(path)}"
    info = get_json(api).get("jobPostingInfo", {})
    return html_to_text(info.get("jobDescription", ""))


def _oracle(url):
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
    match = re.search(r"jobs\.ashbyhq\.com/([^/?]+)/([0-9a-f-]{36})", url)
    if not match:
        return None
    company, job_id = match.groups()
    for job in get_json(f"https://api.ashbyhq.com/posting-api/job-board/{company}").get("jobs", []):
        if job.get("id") == job_id:
            return job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml", ""))
    return None


def _smartrecruiters(url):
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


FETCHERS = [
    greenhouse.fetch_description,
    lever.fetch_description,
    _workday,
    _oracle,
    _ashby,
    _smartrecruiters,
]


def fetch_description(url):
    if not url:
        return None
    for fetcher in FETCHERS:
        try:
            text = fetcher(url)
        except Exception:
            return None
        if text:
            return text.strip()
    return None


def site_name(url):
    host = urlsplit(url or "").netloc
    for key, name in [("myworkdayjobs", "Workday"), ("oraclecloud", "Oracle"),
                      ("greenhouse", "Greenhouse"), ("lever.co", "Lever"),
                      ("ashbyhq", "Ashby"), ("smartrecruiters", "SmartRecruiters")]:
        if key in host:
            return name
    return "other"
