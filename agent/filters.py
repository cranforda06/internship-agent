"""Free, keyword-based filters that run BEFORE any AI scoring.

They throw out listings that clearly aren't a fit (not an internship, wrong
kind of role, wrong term, outside the US), so we only pay to score the rest.
The keyword lists live in config.yaml so you can tune them.
"""

import re

US_STATES = set("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS
MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR""".split())

# Words that show a location is in the US even without a state code.
US_WORDS = re.compile(r"\b(united states|usa|u\.s\.|us|nyc|sf|bay area|remote)\b", re.I)

# Words that show a location is outside the US.
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
    """Build one regex that matches any keyword as a whole word/phrase."""
    escaped = [re.escape(k.strip()) for k in keywords if k.strip()]
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.I)


def is_internship(title):
    return bool(INTERNSHIP_WORDS.search(title))


def is_us_location(location):
    """True if any listed location is in the US. Unknown locations count as yes."""
    if not location.strip():
        return True
    for part in re.split(r"[;|/]| or ", location):
        part = part.strip()
        if not part or NON_US_WORDS.search(part):
            continue
        # "Richmond, VA" or "Richmond, VA, USA" style.
        codes = [c.strip() for c in part.split(",")[1:]]
        if any(c.upper() in US_STATES for c in codes) or US_WORDS.search(part):
            return True
    return False


def is_right_term(title, term):
    """Drop titles that name a different term, e.g. "Fall 2026" when we want Summer 2027.

    Titles that don't mention any term are kept (many just say "Intern").
    """
    season, year = term.lower().split()
    lowered = title.lower()
    years = re.findall(r"\b20\d\d\b", lowered)
    if years and year not in years:
        return False
    other_seasons = {"summer", "fall", "spring", "winter"} - {season}
    mentions_other = any(re.search(rf"\b{s}\b", lowered) for s in other_seasons)
    return not (mentions_other and season not in lowered)


class JobFilter:
    """Applies all the filters, using the settings from config.yaml."""

    def __init__(self, search_config, term):
        self.include = _keyword_pattern(search_config["include_keywords"])
        self.exclude = _keyword_pattern(search_config["exclude_keywords"])
        self.us_only = search_config.get("us_only", True)
        self.term = term

    def reason_to_drop(self, job):
        """Return why a job should be dropped, or None if it passes."""
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
        return None
