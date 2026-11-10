"""Fill a Greenhouse application form (never submits it).

Greenhouse's public feed lists every question on a job's form, with the
field names the page uses and the choices for each dropdown:
    https://boards-api.greenhouse.io/v1/boards/<board>/jobs/<id>?questions=true
So we know the questions before even opening the page.
"""

import re

from agent.apply.answers import Question
from agent.sources.web import get_json

URL_PATTERN = re.compile(r"greenhouse\.io/([\w-]+)/jobs/(\d+)")

KINDS = {
    "input_text": "text",
    "textarea": "textarea",
    "input_file": "file",
    "multi_value_single_select": "combobox",
    "multi_value_multi_select": "multiselect",  # left for you (multiple choices)
    "input_hidden": "hidden",
}


def can_handle(url):
    return bool(URL_PATTERN.search(url or ""))


def get_questions(url):
    board, job_id = URL_PATTERN.search(url).groups()
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}?questions=true")
    questions = []
    for q in data.get("questions", []):
        for f in q["fields"]:
            kind = KINDS.get(f["type"], "unknown")
            if kind == "hidden" or f["name"].endswith("_text"):  # "paste resume as text" boxes
                continue
            questions.append(Question(
                key=f["name"], label=q["label"], kind=kind, required=q.get("required", False),
                options=[v["label"] for v in f.get("values", [])],
            ))
    return questions


def _pick_from_dropdown(page, field, text, timeout=4000):
    """Greenhouse dropdowns: click, type, then click the matching option."""
    field.click()
    field.fill("")
    field.press_sequentially(text[:40], delay=20)
    try:
        page.locator('[role="option"]').first.wait_for(timeout=timeout)
        # Prefer the option whose text is exactly the answer ("Indian", not
        # "American Indian or Alaska Native"); otherwise the first that contains it.
        exact = page.get_by_role("option", name=text, exact=True)
        option = exact.first if exact.count() else page.locator('[role="option"]', has_text=text).first
        option.click()
        return True
    except Exception:
        field.press("Escape")
        return False


def fill(page, url, questions, answers, profile, resume_pdf, log=print):
    """Fill the form on the open page. Returns the list of questions left for you."""
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector('[id="first_name"]', timeout=30000)
    left = []

    for q in questions:
        field = page.locator(f'[id="{q.key}"]')
        if field.count() == 0:
            continue
        try:
            if q.kind == "file":
                if q.key == "resume":
                    field.set_input_files(resume_pdf)
                    log("  ✓ uploaded tailored resume PDF")
                elif q.required:
                    left.append(q)
            elif q.key in answers and q.kind in ("text", "textarea"):
                field.fill(answers[q.key])
            elif q.key in answers and q.kind == "combobox":
                if not _pick_from_dropdown(page, field, answers[q.key]):
                    left.append(q)
            elif q.required:
                left.append(q)
        except Exception as e:  # one stubborn field shouldn't stop the rest
            log(f"  ! couldn't fill '{q.label[:50]}': {e.__class__.__name__}")
            left.append(q)

    # Fields some forms add that aren't in the question list.
    country = page.locator('[id="country"]')
    if country.count() and profile.get("country"):
        _pick_from_dropdown(page, country, profile["country"])
    location = page.locator('[id="candidate-location"]')
    if location.count() and profile.get("city"):
        # Location suggestions come from a map service, so pick the first one
        # that mentions your city.
        _pick_from_dropdown(page, location, f"{profile['city']}, {profile.get('state', '')}".strip(", "),
                            timeout=6000)
    return left
