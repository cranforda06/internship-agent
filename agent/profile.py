"""Your standard application answers, kept in data/profile.yaml.

The agent fills application forms using ONLY what's in this file (plus your
resume). Anything blank is left on the form for you to answer yourself.
"""

from pathlib import Path

import yaml

TEMPLATE = """\
# Your standard answers for application forms.
# The agent uses ONLY what's written here. Leave something blank ("") and
# the agent will leave that question for you to answer on the form.
# This file is in data/, so git never commits it.

# --- Contact (copied from your resume) ---
first_name: "{first}"
last_name: "{last}"
email: "{email}"
phone: "{phone}"
city: "Richmond"
state: "Virginia"
state_code: "VA"
zip: "23220"
country: "United States"
linkedin: "https://www.linkedin.com/in/alex-cranford"
github: ""
website: ""

# --- School (copied from your resume) ---
school: "Virginia Commonwealth University"
degree: "Bachelor of Science"
major: "Information Systems"
minor: ""
graduation_month_year: "December 2027"
graduation_year: "2027"
gpa: "3.80"
currently_enrolled_student: "Yes"
current_company: "B&A Metal Graphics"
current_title: "Production Manager"

# --- You said you'd relocate ---
willing_to_relocate: "Yes"

# --- FILL THESE IN YOURSELF (the agent will never guess them) ---
authorized_to_work_in_us: ""         # Yes / No
need_sponsorship_now_or_future: ""   # Yes / No
at_least_18: ""                      # Yes / No
available_for_summer_2027: ""        # Yes / No
earliest_start_date: ""              # e.g. May 2027
how_did_you_hear: ""                 # e.g. Company website
previously_employed_by_company: ""   # usually No
needs_accommodations: ""             # Yes / No
needs_housing: ""                    # Yes / No / Unsure

# --- Voluntary self-identification (optional) ---
# Every form lets you decline. Write exactly what you'd pick, e.g.
# "Decline to self-identify", or leave blank to answer on each form yourself.
gender: ""
race_ethnicity: ""
hispanic_or_latino: ""
veteran_status: ""
disability_status: ""
"""


def create_template(path, resume_text):
    """Write a starter profile.yaml using details from the resume."""
    lines = [l.strip() for l in resume_text.splitlines() if l.strip()]
    name = lines[0].lstrip("# ").split()
    contact = lines[1].split("|") if len(lines) > 1 else []
    email = next((c.strip() for c in contact if "@" in c), "")
    phone = next((c.strip() for c in contact if sum(ch.isdigit() for ch in c) >= 10), "")
    Path(path).write_text(TEMPLATE.format(
        first=name[0] if name else "", last=" ".join(name[1:]), email=email, phone=phone,
    ), encoding="utf-8")


def load_profile(path):
    """Return the profile as a dict, with blank answers removed."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {k: str(v).strip() for k, v in data.items() if v is not None and str(v).strip()}
