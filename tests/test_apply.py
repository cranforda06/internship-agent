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


# --- Self-identification answers never go to Claude -------------------------------

class RecordingClaude:
    """Fake Claude that records exactly what it was sent."""
    def __init__(self):
        self.sent = ""

    def ask(self, model, system, prompt, schema, effort="low", max_tokens=16000):
        self.sent += prompt
        return {"answers": []}


def test_demographics_are_matched_locally_and_never_sent():
    profile = dict(PROFILE, race_ethnicity="Black or African American",
                   veteran_status="Decline to self-identify", gender="Male")
    questions = [
        Question("q_race", "What is your race/ethnicity?", "combobox",
                 ["Asian", "Black or African American", "White", "Decline to self-identify"]),
        Question("q_vet", "Veteran status", "combobox",
                 ["I am a protected veteran", "I am not a protected veteran", "I don't wish to answer"]),
        Question("q_gender", "Which most closely describes your gender?", "combobox", ["Male", "Female", "Decline"]),
        Question("q_orient", "Sexual orientation", "combobox", ["Straight", "Gay", "Prefer not to say"]),
        Question("q_year", "Graduation year", "combobox", ["2026", "2027"]),
    ]
    claude = RecordingClaude()
    answers = plan_answers(claude, "claude-opus-5-5", profile, "resume", questions)

    assert answers["q_race"] == "Black or African American"
    assert answers["q_vet"] == "I don't wish to answer"        # "decline" matched a differently-worded option
    assert answers["q_gender"] == "Male"
    assert "q_orient" not in answers                            # no profile answer: left for you
    # Nothing personal reached Claude: not your answers, not even those questions.
    for secret in ("Black or African", "Decline to self-identify", "Male", "race", "Veteran",
                   "gender", "orientation"):
        assert secret not in claude.sent, secret
    assert "Graduation year" in claude.sent                     # ordinary questions still go


def test_sensitive_match_never_guesses_between_two_options():
    from agent.apply.answers import match_sensitive
    q = Question("q", "Race", "combobox", ["Asian", "Asian Indian", "White"])
    assert match_sensitive(q, {"race_ethnicity": "asian"}) == "Asian"      # exact wins
    q2 = Question("q", "Race", "combobox", ["Black (Caribbean)", "Black (African)", "White"])
    assert match_sensitive(q2, {"race_ethnicity": "Black"}) is None        # two possible: left for you


def test_race_question_mentioning_hispanic_counts_as_race():
    from agent.apply.answers import sensitive_key
    assert sensitive_key(Question("q", "Race/Ethnicity (including Hispanic or Latino)", "combobox")) == "race_ethnicity"
    assert sensitive_key(Question("q", "Are you Hispanic or Latino?", "combobox")) == "hispanic_or_latino"


# --- Workday (fake page copying Workday's structure) ----------------------------

FAKE_WORKDAY = """<html><body>
<div data-automation-id="formField-firstName"><label for="fn">First Name*</label><input id="fn" type="text"></div>
<div data-automation-id="formField-email"><label for="em">Email Address*</label><input id="em" type="text" value="already@example.com"></div>
<div data-automation-id="formField-source"><label>How Did You Hear About Us?*</label>
  <button aria-haspopup="listbox" data-options='["Company Website","LinkedIn","Job Board"]'>Select One</button></div>
<fieldset data-automation-id="formField-previousWorker"><legend>Have you previously worked here?*</legend>
  <input type="radio" name="prev" id="r1"><label for="r1">Yes</label>
  <input type="radio" name="prev" id="r2"><label for="r2">No</label></fieldset>
<div data-automation-id="formField-gender"><label>Gender</label>
  <button aria-haspopup="listbox" data-options='["Male","Female","I do not wish to answer"]'>Select One</button></div>
<div data-automation-id="formField-terms"><input type="checkbox" id="tc"><label for="tc">I agree to the Terms and Conditions*</label></div>
<div data-automation-id="formField-resume"><label>Upload a file (Resume/CV)</label><input type="file" id="file" style="display:none"></div>
<button data-automation-id="bottom-navigation-next-button" onclick="document.title='NEXT CLICKED'">Next</button>
<div id="popup"></div>
<script>
  // Mimics Workday dropdowns: choices appear only after clicking; Escape closes.
  const popup = document.getElementById('popup');
  document.querySelectorAll('button[aria-haspopup]').forEach(btn => btn.addEventListener('click', () => {
    popup.innerHTML = '<ul role="listbox">' + JSON.parse(btn.dataset.options)
      .map(o => `<li role="option">${o}</li>`).join('') + '</ul>';
    popup.querySelectorAll('[role=option]').forEach(li => li.addEventListener('click', () => {
      btn.innerText = li.innerText; popup.innerHTML = '';
    }));
  }));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') popup.innerHTML = ''; });
</script></body></html>"""


def test_workday_read_and_fill(tmp_path, browser_page):
    from agent.apply import workday
    form = tmp_path / "wd.html"
    form.write_text(FAKE_WORKDAY)
    browser_page.goto(form.as_uri())

    questions = workday.read_page(browser_page)
    by_label = {q.label: q for q in questions}
    assert "Email Address" not in by_label                       # already filled: left alone
    assert by_label["How Did You Hear About Us?"].options == ["Company Website", "LinkedIn", "Job Board"]
    assert by_label["Have you previously worked here?"].options == ["Yes", "No"]
    assert by_label["First Name"].required is True

    profile = dict(PROFILE, how_did_you_hear="Company Website", gender="Decline to self-identify")
    claude = make_claude([("end_turn", {"answers": [
        {"key": by_label["First Name"].key, "leave_for_student": False, "answer": "Pat"},
        {"key": by_label["How Did You Hear About Us?"].key, "leave_for_student": False, "answer": "Company Website"},
        {"key": by_label["Have you previously worked here?"].key, "leave_for_student": True, "answer": ""},
    ]})])
    answers = plan_answers(claude, "claude-opus-5-5", profile, "", questions)
    pdf = tmp_path / "Pat_Doe_Resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    left = workday.fill_page(browser_page, questions, answers, str(pdf), log=lambda m: None)

    assert browser_page.input_value("#fn") == "Pat"
    assert browser_page.input_value("#em") == "already@example.com"           # not overwritten
    buttons = browser_page.locator("button[aria-haspopup]").all_inner_texts()
    assert buttons == ["Company Website", "I do not wish to answer"]          # gender matched locally
    assert browser_page.evaluate("document.getElementById('file').files.length") == 1
    assert not browser_page.is_checked("#tc")                                  # terms: always yours
    assert browser_page.title() != "NEXT CLICKED"                              # never clicks Next
    assert {q.label for q in left} == {"Have you previously worked here?", "I agree to the Terms and Conditions"}


def test_done_button_stops_review_page(tmp_path):
    from agent import review
    resume = tmp_path / "resume.md"
    resume.write_text("# Pat Doe\n")
    t = Tracker(tmp_path / "t.db")
    app = review.create_app({"resume_path": resume}, t)
    client = app.test_client()
    assert b"Done reviewing" in client.get("/").data
    assert client.post("/done").status_code == 403            # needs the session token
    assert not app.config.get("DONE")
    client.post("/done", data={"token": review.TOKEN})
    assert app.config["DONE"] is True
    t.close()


def test_pronouns_matched_locally_and_never_sent():
    profile = dict(PROFILE, pronouns="he/him")
    q = Question("q_pron", "Pronouns", "combobox", ["she/her", "he/him", "they/them", "Prefer not to say"])
    claude = RecordingClaude()
    answers = plan_answers(claude, "claude-opus-5-5", profile, "resume", [q, Question("y", "Graduation year", "text")])
    assert answers["q_pron"] == "he/him"
    assert "he/him" not in claude.sent and "Pronouns" not in claude.sent


def test_veteran_no_matches_however_the_form_words_it():
    from agent.apply.answers import match_sensitive
    profile = {"veteran_status": "I am not a protected veteran"}

    def pick(options):
        return match_sensitive(Question("q", "Veteran status", "combobox", options), profile)

    assert pick(["I am a veteran", "I am not a veteran", "I don't wish to answer"]) == "I am not a veteran"
    assert pick(["Yes, I am a protected veteran", "No, I am not a protected veteran",
                 "Decline to self-identify"]) == "No, I am not a protected veteran"
    assert pick(["I identify as one or more of the classifications of protected veteran",
                 "I am not a protected veteran", "I do not wish to self-identify"]) == "I am not a protected veteran"
    # Two different "no" options and no exact match: left for you.
    assert pick(["I am a protected veteran", "I am not a veteran",
                 "I am a veteran, but not a protected veteran"]) is None


def test_disability_no_and_decline_wordings():
    from agent.apply.answers import match_sensitive
    options = ["Yes, I have a disability (or previously had a disability)",
               "No, I do not have a disability and have not had one in the past",
               "I do not want to answer"]
    q = Question("q", "Disability status", "combobox", options)
    assert match_sensitive(q, {"disability_status": "No, I do not have a disability"}) == options[1]
    assert match_sensitive(q, {"disability_status": "Decline to self-identify"}) == options[2]


WORKDAY_LOOSE_RADIOS = """<html><body>
<div data-automation-id="formField-candidateIsPreviousWorker">
  <label>Have you previously worked for this organization?*</label>
  <div role="radiogroup">
    <div><input type="radio" name="r-a1" id="ra"><span>Yes</span></div>
    <div><input type="radio" name="r-b2" id="rb"><span>No</span></div>
  </div>
</div></body></html>"""


def test_workday_radios_with_unlinked_labels_and_different_names(tmp_path, browser_page):
    from agent.apply import workday
    form = tmp_path / "wd2.html"
    form.write_text(WORKDAY_LOOSE_RADIOS)
    browser_page.goto(form.as_uri())
    questions = workday.read_page(browser_page)
    assert len(questions) == 1                                   # one question, not two
    q = questions[0]
    assert q.label == "Have you previously worked for this organization?"
    assert q.options == ["Yes", "No"]
    left = workday.fill_page(browser_page, questions, {q.key: "No"}, None, log=lambda m: None)
    assert left == []
    assert browser_page.is_checked("#rb") and not browser_page.is_checked("#ra")


class LabelClaude:
    """Fake Claude that answers form questions by their label."""
    def __init__(self, by_label):
        self.by_label, self.calls = by_label, 0

    def ask(self, model, system, prompt, schema, effort="low", max_tokens=16000):
        import yaml
        self.calls += 1
        listing = yaml.safe_load(prompt.split("<questions>\n", 1)[1].split("</questions>")[0])
        return {"answers": [
            {"key": q["key"], "leave_for_student": q["question"] not in self.by_label,
             "answer": self.by_label.get(q["question"], "")} for q in listing]}


def test_workday_hands_free_fills_each_page_as_it_loads(tmp_path, browser_page):
    import queue
    from agent.apply import workday
    folder = tmp_path / "apply"                     # Workday application URLs contain /apply
    folder.mkdir()
    (folder / "signin.html").write_text("""<html><body>
      <div data-automation-id="formField-email"><label for="e">Email</label><input id="e"></div>
      <div data-automation-id="formField-pw"><label for="p">Password</label><input id="p" type="password"></div>
      <script>setTimeout(() => location.href = 'page1.html', 2500)</script></body></html>""")
    (folder / "page1.html").write_text("""<html><body><h2>My Information</h2>
      <div data-automation-id="formField-first"><label for="fn">First Name*</label><input id="fn"></div>
      <script>
        // Pretend you click Next once the page is filled.
        setInterval(() => { if (document.getElementById('fn').value) location.href = 'page2.html'; }, 500);
      </script></body></html>""")
    (folder / "page2.html").write_text("""<html><body><h2>Application Questions</h2>
      <div data-automation-id="formField-city"><label for="c">City*</label><input id="c"></div>
      </body></html>""")

    claude = LabelClaude({"First Name": "Pat", "City": "Richmond"})
    workday.assist(browser_page, (folder / "signin.html").as_uri(), claude, "m", PROFILE, "", None,
                   log=lambda m: None, poll_seconds=0.2, typed=queue.Queue(), time_limit=12)

    assert browser_page.url.endswith("page2.html")
    assert browser_page.input_value("#c") == "Richmond"          # page 2 filled with no Enter pressed
    assert claude.calls == 2                                      # once per page; sign-in page never touched


def test_workday_page_that_keeps_changing_does_not_loop(tmp_path, browser_page):
    import queue
    from agent.apply import workday
    folder = tmp_path / "apply"
    folder.mkdir()
    (folder / "info.html").write_text("""<html><body><h2>My Information</h2>
      <div data-automation-id="formField-phoneType"><label>Phone Device Type</label>
        <button aria-haspopup="listbox" id="dd">Select One</button></div>
      <div id="menu"></div><div id="extra"></div>
      <script>
        window.opens = 0; let n = 0;
        document.getElementById('dd').addEventListener('click', () => {
          window.opens++;
          document.getElementById('menu').innerHTML =
            '<ul role="listbox"><li role="option">Mobile</li><li role="option">Home</li></ul>';
        });
        document.addEventListener('keydown', e => {
          if (e.key !== 'Escape' || !document.getElementById('menu').innerHTML) return;
          document.getElementById('menu').innerHTML = '';
          // Worst case: every time a menu closes, the page adds another field.
          n++;
          document.getElementById('extra').insertAdjacentHTML('beforeend',
            `<div data-automation-id="formField-x${n}"><label for="x${n}">Extra ${n}</label><input id="x${n}"></div>`);
        });
      </script></body></html>""")

    claude = LabelClaude({})       # answers nothing, like a blank profile
    workday.assist(browser_page, (folder / "info.html").as_uri(), claude, "m", PROFILE, "", None,
                   log=lambda m: None, poll_seconds=0.2, typed=queue.Queue(), time_limit=15)

    assert browser_page.evaluate("window.opens") == 1     # the dropdown was opened only once
    assert claude.calls <= workday.MAX_AUTO_ROUNDS        # stopped instead of looping


def test_workday_autofill_with_resume_page_gets_the_resume(tmp_path, browser_page, apply_log_in_tmp):
    """The "Autofill with Resume" page is only an upload box, no other questions."""
    import queue
    from agent.apply import workday
    folder = tmp_path / "apply"
    folder.mkdir()
    pdf = tmp_path / "Pat_Doe_Resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    (folder / "autofillWithResume.html").write_text("""<html><body><h2>Autofill with Resume</h2>
      <div data-automation-id="file-upload-drop-zone">Drop file here
        <button>Select file</button>
        <input type="file" data-automation-id="file-upload-input-ref" style="display:none">
      </div>
      <!-- Leftovers Workday can keep hidden in the page: must not block filling -->
      <div style="display:none"><input type="password">
        <ul role="listbox"><li role="option">English</li></ul></div>
      </body></html>""")

    claude = LabelClaude({})
    workday.assist(browser_page, (folder / "autofillWithResume.html").as_uri(), claude, "m", PROFILE, "",
                   str(pdf), log=lambda m: None, poll_seconds=0.2, typed=queue.Queue(), time_limit=5)

    assert browser_page.evaluate("document.querySelector('input[type=file]').files[0].name") == pdf.name
    assert claude.calls == 0                     # nothing to ask Claude on an upload-only page
    assert "upload box" in apply_log_in_tmp.read_text()   # saved to the apply log


def test_sites_we_dont_fill_open_in_your_normal_browser(monkeypatch, apply_log_in_tmp, tmp_path):
    import webbrowser
    from agent.apply import runner
    opened = []
    monkeypatch.setattr(webbrowser, "open", opened.append)

    class NoTouchPage:
        def goto(self, *a, **k):
            raise AssertionError("the agent's browser must not open this site")

    t = Tracker(tmp_path / "t.db")
    job = t.add("NBCUniversal", "Ops Intern", link="https://jobs.smartrecruiters.com/X/1", status="approved")
    runner.fill_job(NoTouchPage(), t.get(job), t, None, {}, "", {"open_resume_automatically": False},
                    log=lambda m: None)
    assert opened == ["https://jobs.smartrecruiters.com/X/1"]
    assert "NBCUniversal - Ops Intern (other)" in apply_log_in_tmp.read_text()
    t.close()


def test_workday_nested_labels_still_get_filled(tmp_path, browser_page):
    """Some companies' Workday nests the label deeper and doesn't link it with for=."""
    import queue
    from agent.apply import workday
    folder = tmp_path / "apply"
    folder.mkdir()
    (folder / "info.html").write_text("""<html><body><h2>My Information</h2>
      <div data-automation-id="formField-addressLine1">
        <div class="labelWrap"><label id="l1">Address Line 1<abbr>*</abbr></label></div>
        <div><input id="a1" aria-labelledby="l1"></div></div>
      <div data-automation-id="formField-city">
        <div><label id="l2">City</label></div><div><input id="c1" aria-labelledby="l2"></div></div>
      </body></html>""")

    claude = LabelClaude({"Address Line 1": "Richmond", "City": "Richmond"})
    workday.assist(browser_page, (folder / "info.html").as_uri(), claude, "m", PROFILE, "", None,
                   log=lambda m: None, poll_seconds=0.2, typed=queue.Queue(), time_limit=6)

    assert browser_page.input_value("#a1") == "Richmond"
    assert browser_page.input_value("#c1") == "Richmond"


def test_workday_stuck_page_is_described_in_the_log(tmp_path, browser_page, apply_log_in_tmp):
    import queue
    from agent.apply import workday
    folder = tmp_path / "apply"
    folder.mkdir()
    (folder / "odd.html").write_text("""<html><body><h2>My Information</h2>
      <div data-automation-id="weirdBox"><span>Address</span><div contenteditable="true"></div></div>
      </body></html>""")
    workday.assist(browser_page, (folder / "odd.html").as_uri(), LabelClaude({}), "m", PROFILE, "", None,
                   log=lambda m: None, poll_seconds=0.2, typed=queue.Queue(), time_limit=11)
    text = apply_log_in_tmp.read_text()
    assert "no questions found on:" in text and "weirdBox" in text
    assert "Richmond" not in text            # never anything from your profile


def test_workday_page_that_always_shows_a_list_still_gets_filled(tmp_path, browser_page):
    import queue
    from agent.apply import workday
    folder = tmp_path / "apply"
    folder.mkdir()
    (folder / "info.html").write_text("""<html><body><h2>My Information</h2>
      <div data-automation-id="formField-city"><label for="c1">City</label><input id="c1"></div>
      <ul role="listbox"><li role="option">Always showing</li></ul>
      </body></html>""")
    workday.assist(browser_page, (folder / "info.html").as_uri(), LabelClaude({"City": "Richmond"}), "m",
                   PROFILE, "", None, log=lambda m: None, poll_seconds=0.2, typed=queue.Queue(), time_limit=12)
    assert browser_page.input_value("#c1") == "Richmond"
