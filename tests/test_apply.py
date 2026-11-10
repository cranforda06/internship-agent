"""Tests for Phase 4: answer safety rules, the review page, and form filling.

Form filling runs against small FAKE forms saved as local files, never a
real employer's site, and nothing is ever submitted.
"""

import json

import pytest

from agent.apply import greenhouse, lever
from agent.apply.answers import Question, plan_answers, validate
from agent.tracker import Tracker
from tests.test_scorer import make_claude

PROFILE = {"first_name": "Pat", "last_name": "Doe", "email": "pat@example.com",
           "graduation_year": "2027", "gpa": "3.80", "country": "United States", "city": "Richmond"}
ALLOWED = {"pat", "doe", "pat", "example", "com", "2027", "3", "80", "united", "states", "richmond"}


# --- Safety rules for answers -------------------------------------------------

def test_choice_answer_must_be_an_option():
    q = Question("q1", "Graduation year?", "combobox", ["2026", "2027"])
    assert validate(q, "2027", ALLOWED) == "2027"
    assert validate(q, "2028", ALLOWED) is None


def test_text_answer_cannot_invent_words():
    q = Question("q2", "First name", "text")
    assert validate(q, "Pat", ALLOWED) == "Pat"
    assert validate(q, "Patrick", ALLOWED) is None


def test_consent_and_essays_are_always_left_for_you():
    consent = Question("q3", "I agree to the privacy policy", "checkbox", ["Yes"])
    essay = Question("q4", "Tell us why you want this role", "textarea")
    assert validate(consent, "Yes", ALLOWED) is None
    assert validate(essay, "Pat", ALLOWED) is None


def test_describes_your_gender_is_not_treated_as_an_essay():
    q = Question("q5", "Which most closely describes your gender?", "combobox", ["Decline to self-identify"])
    assert validate(q, "Decline to self-identify", ALLOWED) == "Decline to self-identify"


def test_plan_answers_drops_unsafe_answers():
    questions = [Question("first_name", "First Name", "text"),
                 Question("q_auth", "Are you authorized to work in the US?", "combobox", ["Yes", "No"]),
                 Question("q_city", "City", "text")]
    claude = make_claude([("end_turn", {"answers": [
        {"key": "first_name", "leave_for_student": False, "answer": "Pat"},
        {"key": "q_auth", "leave_for_student": False, "answer": "Maybe"},         # not an option
        {"key": "q_city", "leave_for_student": False, "answer": "San Francisco"},  # not in profile
    ]})])
    assert plan_answers(claude, "claude-opus-5-5", PROFILE, "", questions) == {"first_name": "Pat"}


# --- Form filling on fake local forms ------------------------------------------

FAKE_GREENHOUSE = """<html><body><form>
<input id="first_name"><input id="last_name"><input id="email">
<input type="file" id="resume">
<input id="question_1" role="combobox"><div id="menu_question_1"></div>
<input id="question_3" role="combobox"><div id="menu_question_3"></div>
<textarea id="question_2"></textarea>
<button type="submit" onclick="document.title='SUBMITTED'; return false;">Submit</button>
<script>
  // Mimics Greenhouse's dropdowns: typing shows matching options, clicking picks one.
  function dropdown(id, options) {
    const box = document.getElementById(id), menu = document.getElementById('menu_' + id);
    box.addEventListener('input', () => {
      menu.innerHTML = options.filter(o => o.toLowerCase().includes(box.value.toLowerCase()))
        .map(o => `<div role="option" onclick="document.getElementById('${id}').value='${o}';
                    this.parentNode.innerHTML=''">${o}</div>`).join('');
    });
  }
  dropdown('question_1', ['2026', '2027']);
  dropdown('question_3', ['American Indian or Alaska Native', 'Indian', 'Decline to self-identify']);
</script></form></body></html>"""

FAKE_LEVER = """<html><body><form>
<div class="application-question"><div class="application-label">Resume</div><input type="file" name="resume"></div>
<div class="application-question"><div class="application-label">Full name<span class="required">✱</span></div><input type="text" name="name"></div>
<div class="application-question"><div class="application-label">Authorized to work?<span class="required">✱</span></div>
  <input type="radio" name="cards[a][field0]" value="Yes"><input type="radio" name="cards[a][field0]" value="No"></div>
<div class="application-question"><div class="application-label">School</div>
  <select name="cards[a][field1]"><option>Select...</option><option>Virginia Commonwealth University</option></select></div>
<div class="application-question"><div class="application-label">I consent to data processing<span class="required">✱</span></div>
  <input type="checkbox" name="cards[a][field2]" value="I Consent"></div>
</form></body></html>"""


@pytest.fixture
def browser_page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser.new_page()
        browser.close()


def test_greenhouse_fill_on_fake_form(tmp_path, browser_page):
    form = tmp_path / "gh.html"
    form.write_text(FAKE_GREENHOUSE)
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    questions = [Question("first_name", "First Name", "text", required=True),
                 Question("resume", "Resume", "file", required=True),
                 Question("question_1", "Graduation year", "combobox", ["2026", "2027"], True),
                 Question("question_3", "Ethnicity", "combobox", ["American Indian or Alaska Native", "Indian"], True),
                 Question("question_2", "Why do you want this job?", "textarea", required=True)]
    answers = {"first_name": "Pat", "question_1": "2027", "question_3": "Indian"}
    left = greenhouse.fill(browser_page, form.as_uri(), questions, answers, PROFILE, str(pdf), log=lambda m: None)
    assert browser_page.input_value("#first_name") == "Pat"
    assert browser_page.input_value("#question_1") == "2027"
    assert browser_page.input_value("#question_3") == "Indian"   # exact option, not "American Indian..."
    assert browser_page.title() != "SUBMITTED"          # never clicks Submit
    assert [q.key for q in left] == ["question_2"]      # the essay is left for you


def test_lever_read_and_fill_on_fake_form(tmp_path, browser_page, monkeypatch):
    form = tmp_path / "lever.html"
    form.write_text(FAKE_LEVER)
    browser_page.goto(form.as_uri())
    questions = [Question(**q) for q in browser_page.evaluate(lever.READ_FORM)]
    kinds = {q.label: q.kind for q in questions}
    assert kinds == {"Resume": "file", "Full name": "text", "Authorized to work?": "radio",
                     "School": "select", "I consent to data processing": "checkbox"}
    school = next(q for q in questions if q.label == "School")
    assert school.options == ["Virginia Commonwealth University"]

    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(browser_page, "wait_for_timeout", lambda ms: None)
    answers = {"name": "Pat Doe", "cards[a][field1]": "Virginia Commonwealth University"}
    left = lever.fill(browser_page, questions, answers, str(pdf), log=lambda m: None)
    assert browser_page.input_value('[name="name"]') == "Pat Doe"
    assert {q.label for q in left} == {"Authorized to work?", "I consent to data processing"}


def test_greenhouse_questions_from_feed(monkeypatch):
    feed = {"questions": [
        {"label": "First Name", "required": True, "fields": [{"name": "first_name", "type": "input_text"}]},
        {"label": "Resume", "required": True, "fields": [{"name": "resume", "type": "input_file"},
                                                        {"name": "resume_text", "type": "textarea"}]},
        {"label": "Sponsorship?", "required": True, "fields": [{"name": "question_9", "type": "multi_value_single_select",
                                                                "values": [{"label": "Yes"}, {"label": "No"}]}]},
    ]}
    monkeypatch.setattr(greenhouse, "get_json", lambda url: feed)
    qs = greenhouse.get_questions("https://job-boards.greenhouse.io/acme/jobs/123")
    assert [(q.key, q.kind) for q in qs] == [("first_name", "text"), ("resume", "file"), ("question_9", "combobox")]
    assert qs[2].options == ["Yes", "No"]


# --- Review page ---------------------------------------------------------------

def test_review_page_approve_needs_token(tmp_path):
    from agent import review

    resume = tmp_path / "resume.md"
    resume.write_text("# Pat Doe\npat@example.com\n\n## Skills\n- SQL\n")
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "resume.md").write_text("# Pat Doe\npat@example.com\n\n## Skills\n- SQL, Excel\n")
    t = Tracker(tmp_path / "t.db")
    job = t.add("Acme", "IT Intern", status="queued")
    t.update_details(job, tailored_dir=str(folder), fit_score=80,
                     tailor_report=json.dumps({"changes": ["x"], "ai_check_issues": [],
                                               "code_check_problems": [], "pages": 1}))
    client = review.create_app({"resume_path": resume}, t).test_client()

    assert b"Acme" in client.get("/").data
    detail = client.get(f"/job/{job}").data
    assert b"was: - SQL" in detail                     # reworded line shows the original
    assert client.post(f"/job/{job}/approve").status_code == 403   # no token -> refused
    client.post(f"/job/{job}/approve", data={"token": review.TOKEN})
    assert t.get(job)["status"] == "approved"
    t.close()
