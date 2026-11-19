import re
from datetime import date

US_STATES = set("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS
MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR""".split())

US_WORDS = re.compile(r"\b(united states|usa|u\.s\.|us|nyc|sf|bay area|remote)\b", re.I)

NON_US_WORDS = re.compile(
    r"\b(canada|uk|united kingdom|england|ireland|india|germany|france|netherlands|"
    r"singapore|japan|china|hong kong|australia|mexico|brazil|poland|spain|israel|"
    r"switzerland|sweden|korea|taiwan|philippines|emea|apac|latam|london|toronto|"
    r"vancouver|dublin|amsterdam|bengaluru|bangalore|berlin|paris|tokyo|sydney)\b",
    re.I,
)

INTERNSHIP_WORDS = re.compile(
    r"\b(intern|interns|internship|internships|co-?op|summer analyst|summer associate)\b", re.I
)


def _keyword_pattern(keywords):
    escaped = [re.escape(k.strip()) for k in keywords if k.strip()]
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.I)


def is_internship(title):
    return bool(INTERNSHIP_WORDS.search(title))


def is_us_location(location):
    if not location.strip():
        return True
    for part in re.split(r"[;|/]| or ", location):
        part = part.strip()
        if not part or NON_US_WORDS.search(part):
            continue
        codes = [c.strip() for c in part.split(",")[1:]]
        if any(c.upper() in US_STATES for c in codes) or US_WORDS.search(part):
            return True
    return False


def is_right_term(title, term):
    season, year = term.lower().split()
    lowered = title.lower()
    years = re.findall(r"\b20\d\d\b", lowered)
    if years and year not in years:
        return False
    other_seasons = {"summer", "fall", "spring", "winter"} - {season}
    mentions_other = any(re.search(rf"\b{s}\b", lowered) for s in other_seasons)
    return not (mentions_other and season not in lowered)


def is_preferred_location(location, preferred):
    lowered = (location or "").lower()
    return any(place.lower() in lowered for place in preferred)


def adjusted_score(fit_score, location, search_config):
    if fit_score is None:
        return None
    bonus = 0
    if is_preferred_location(location, search_config.get("preferred_locations", [])):
        bonus = search_config.get("preferred_location_bonus", 0)
    return min(100, fit_score + bonus)


def posting_age_days(posted, today=None):
    if not posted:
        return None
    try:
        return ((today or date.today()) - date.fromisoformat(posted[:10])).days
    except ValueError:
        return None


def age_text(posted, today=None):
    days = posting_age_days(posted, today)
    if days is None:
        return "post date unknown"
    return "posted today" if days <= 0 else f"posted {days} day{'s' if days != 1 else ''} ago"


class JobFilter:
    def __init__(self, search_config, term, today=None):
        self.include = _keyword_pattern(search_config["include_keywords"])
        self.exclude = _keyword_pattern(search_config["exclude_keywords"])
        self.us_only = search_config.get("us_only", True)
        self.max_age = search_config.get("max_posting_age_days")
        self.only_verified = search_config.get("only_verified_sites", False)
        self.term = term
        self.today = today

    def reason_to_drop(self, job):
        if not is_internship(job.title):
            return "not an internship"
        if self.exclude.search(job.title):
            return "excluded keyword"
        if not self.include.search(job.title):
            return "not a target role"
        if not is_right_term(job.title, self.term):
            return "different term"
        if self.us_only and not is_us_location(job.location):
            return "outside the US"
        age = posting_age_days(job.posted, self.today)
        if self.max_age and age is not None and age > self.max_age:
            return f"posted more than {self.max_age} days ago"
        if self.only_verified:
            from agent.sources.trust import classify
            if classify(job.url, job.company)[0] == "unverified":
                return "not on a verified site"
        return None
