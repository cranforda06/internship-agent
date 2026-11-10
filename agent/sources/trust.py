"""Is a job link on a trustworthy site?

A link counts as verified if it's on:
  - an established hiring system that employers use directly (Workday,
    Greenhouse, Lever, ...), or
  - the company's own website (the company's name appears in the domain,
    e.g. TikTok -> lifeattiktok.com).
Anything else is "unverified": not necessarily fake, but worth a look to make
sure it's the company's real careers page before you apply.
"""

import re
from urllib.parse import urlsplit

# Hiring systems ("applicant tracking systems") employers use directly.
HIRING_SYSTEMS = {
    "myworkdayjobs.com": "Workday",
    "myworkdaysite.com": "Workday",
    "greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "oraclecloud.com": "Oracle",
    "taleo.net": "Taleo",
    "icims.com": "iCIMS",
    "ashbyhq.com": "Ashby",
    "smartrecruiters.com": "SmartRecruiters",
    "jobvite.com": "Jobvite",
    "avature.net": "Avature",
    "paylocity.com": "Paylocity",
    "successfactors.com": "SuccessFactors",
    "successfactors.eu": "SuccessFactors",
    "workable.com": "Workable",
    "breezy.hr": "Breezy",
    "bamboohr.com": "BambooHR",
    "jibeapply.com": "Jibe",
    "yello.co": "Yello",
    "ultipro.com": "UKG",
    "ukg.net": "UKG",
    "adp.com": "ADP",
    "rippling.com": "Rippling",
    "eightfold.ai": "Eightfold",
    "phenompeople.com": "Phenom",
}

COMPANY_FILLER = {"the", "inc", "llc", "corp", "corporation", "company", "co", "group", "holdings",
                  "and", "of", "solutions", "technologies", "technology", "services", "international"}


def _company_words(company):
    words = [w for w in re.findall(r"[a-z0-9]+", company.lower()) if w not in COMPANY_FILLER]
    joined = "".join(words)
    # "TikTok" -> {"tiktok"}; "HF Sinclair" -> {"hfsinclair", "sinclair"}
    return {w for w in words if len(w) >= 4} | ({joined} if len(joined) >= 3 else set())


def classify(url, company):
    """Return (level, description). level is "hiring_system", "company_site", or "unverified"."""
    host = urlsplit(url or "").netloc.lower()
    if not host:
        return "unverified", "no link"
    if urlsplit(url).scheme != "https":
        return "unverified", f"{host} (not a secure https link)"
    for domain, name in HIRING_SYSTEMS.items():
        if host == domain or host.endswith("." + domain):
            return "hiring_system", name
    squashed = host.replace("-", "").replace(".", "")
    if any(word in squashed for word in _company_words(company)):
        return "company_site", host
    return "unverified", host
