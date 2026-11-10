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

# --- More answers that forms often ask (fill in what applies) ---
preferred_name: ""                   # if you go by a different first name
address_line_1: ""                   # street address (some Workday forms require it)
address_line_2: ""                   # apt / unit, if any
phone_type: ""                       # e.g. Mobile
phone_country_code: ""               # e.g. United States of America (+1)
us_citizen: ""                       # Yes / No
security_clearance: ""               # e.g. None, Secret, Top Secret
willing_to_obtain_clearance: ""      # Yes / No
education_start_date: ""             # e.g. August 2024
degree_type: ""                      # e.g. Bachelor's Degree
class_standing_summer_2027: ""       # e.g. Senior (your year during the internship)
available_hours_per_week: ""         # e.g. 40
internship_end_date: ""              # e.g. August 2027
willing_to_travel: ""                # Yes / No, or e.g. Up to 25%
work_setting_preference: ""          # e.g. Open to on-site, hybrid, or remote
have_drivers_license: ""             # Yes / No
languages: ""                        # e.g. English (fluent), Spanish (conversational)

# --- Voluntary self-identification (optional) ---
# PRIVATE: these answers never leave your computer. They are matched to each
# form's options by code on your Mac, and are never sent to Claude.
# Every form lets you decline. Write what you'd pick, e.g.
# "Decline to self-identify", or leave blank to answer on each form yourself.
# If a form's options don't clearly match your answer, it's left for you.
gender: ""
race_ethnicity: ""
hispanic_or_latino: ""
veteran_status: ""
disability_status: ""
pronouns: ""
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
