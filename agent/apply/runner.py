"""Go through your approved jobs one at a time and fill in each application.

For each job:
1. Open it in a real browser window you can see.
2. Upload the tailored resume PDF and fill in every answer we're sure of.
3. Print what's left for you (essays, consents, anything unclear).
4. WAIT. You check the form, finish anything left, and click Submit
   yourself. Then you tell the agent what happened.

The agent never clicks Submit.

The browser keeps its own profile in data/browser-profile, so sites you log
into (like a company's Workday) stay logged in next time.

Two ways to use it: the terminal (python main.py apply), or buttons on the
home page (python main.py home / go), which uses fill_job() below too.
"""

import json

from agent.apply import greenhouse, history, lever, workday
from agent.apply.answers import plan_answers
from agent.config import PROJECT_ROOT

BROWSER_PROFILE = PROJECT_ROOT / "data" / "browser-profile"


def show_resume(pdf):
    """Open the tailored PDF in your normal PDF viewer (Preview on a Mac),
    so you can read exactly what's being uploaded."""
    import subprocess
    import sys
    import webbrowser
    from pathlib import Path

    if not pdf or not Path(pdf).exists():
        print("  ! Couldn't find the resume file.")
        return
    if sys.platform == "darwin":
        subprocess.run(["open", pdf], check=False)
    else:
        webbrowser.open(Path(pdf).as_uri())


def site_for(url):
    if greenhouse.can_handle(url):
        return "greenhouse"
    if lever.can_handle(url):
        return "lever"
    if "myworkdayjobs.com" in (url or ""):
        return "workday"
    return "other"


def resume_pdf(row):
    return json.loads(row["tailor_report"] or "{}").get("pdf")


class BrowserWindow:
    """The browser the agent fills forms in. If you close its tab or the
    whole window, a new one opens for the next job instead of failing."""

    def __init__(self, playwright):
        self.playwright = playwright
        self.browser = None
        self._page = None

    def _open(self):
        self.browser = self.playwright.chromium.launch_persistent_context(
            str(BROWSER_PROFILE), headless=False, viewport={"width": 1280, "height": 900},
        )
        pages = self.browser.pages
        self._page = pages[0] if pages else self.browser.new_page()

    def page(self):
        if self.browser is None:
            self._open()
        elif self._page is None or self._page.is_closed():
            try:
                self._page = self.browser.new_page()        # tab closed: new tab
            except Exception:
                print("  (The browser was closed. Opening it again...)")
                self.close()
                self._open()                                 # window closed: new window
        return self._page

    def close(self):
        try:
            if self.browser is not None:
                self.browser.close()
        except Exception:
            pass   # already closed by you
        self.browser = None


def _report_left(left, log):
    if not left:
        log("  ✓ Every required question was filled in.")
        return
    log(f"  Left for you ({len(left)}):")
    for q in left:
        log(f"    - {q.label[:90]}")
    log("  Tip: fill in blanks in data/profile.yaml and the agent will answer those next time.")


def fill_job(page, row, tracker, claude, profile, resume_text, settings, log=print, workday_keys=None):
    """Open one job's application and fill in everything we're sure of.

    For Workday this keeps going page by page until it gets "d" (from your
    keyboard, or from `workday_keys` when the home page's buttons drive it).
    """
    pdf = resume_pdf(row)
    model = settings.get("answer_model", "claude-opus-5-5")
    site = site_for(row["link"])
    history.write(f"=== #{row['id']} {row['company']} - {row['role']} ({site}) {row['link']}")
    log = history.logged(log)   # everything shown is also saved to data/logs/apply.log
    if settings.get("open_resume_automatically", True):
        show_resume(pdf)
        log("  Opened the resume in your PDF viewer so you can see exactly what's uploaded.")
    past = tracker.similar_application(row["company"], row["role"])
    if past:
        log(f"  ⚠ This looks like a job you already applied to: {past['role']} "
            f"({past['status']}). Skip it unless you're sure it's different.")
    try:
        if site == "greenhouse":
            questions = greenhouse.get_questions(row["link"])
            answers = plan_answers(claude, model, profile, resume_text, questions)
            _report_left(greenhouse.fill(page, row["link"], questions, answers, profile, pdf, log), log)
        elif site == "lever":
            questions = lever.open_and_read(page, row["link"])
            answers = plan_answers(claude, model, profile, resume_text, questions)
            _report_left(lever.fill(page, questions, answers, pdf, log), log)
        elif site == "workday":
            workday.assist(page, row["link"], claude, model, profile, resume_text, pdf, log,
                           typed=workday_keys)
        else:
            # Sites the agent doesn't fill: open them in YOUR normal browser.
            # Some (like SmartRecruiters) block browsers run by a program.
            import webbrowser
            webbrowser.open(row["link"])
            log("  This site isn't auto-filled. It's open in your normal browser (not the agent's")
            log("  window): apply there yourself and upload the tailored resume PDF.")
    except Exception as e:
        log(f"  ! Couldn't fill this form automatically ({e.__class__.__name__}).")
        if "Closed" in e.__class__.__name__:
            log("  The browser window was closed. Choose 'later' to keep this job;")
            log("  a new window opens for the next job.")
        else:
            log("  The page is open: you can still fill it in yourself.")


def _ask_outcome(pdf):
    while True:
        choice = input("\n  Did you submit it?  [y] yes, submitted   [n] not yet (keep for later)   "
                       "[s] skip this job   [q] quit   [v] view resume\n  > ").strip().lower()
        if choice == "v":
            show_resume(pdf)
        elif choice in ("y", "n", "s", "q"):
            return choice


def apply_to_approved(config, tracker, claude, profile, resume_text, log=print, only_ids=None):
    """Fill in every approved job (or only the job numbers in `only_ids`),
    asking in the terminal what happened after each one."""
    from playwright.sync_api import sync_playwright

    rows = tracker.list_all(status="approved")
    if only_ids:
        rows = [r for r in rows if r["id"] in only_ids]
    if not rows:
        print("No approved jobs to apply to. Approve one first: python main.py review "
              "(or e.g. python main.py status 42 approved, using the job's number)")
        return {}
    settings = config.get("apply", {})
    counts = {"submitted": 0, "later": 0, "skipped": 0}

    with sync_playwright() as p:
        window = BrowserWindow(p)
        for n, row in enumerate(reversed(rows), start=1):  # oldest approval first
            page = window.page()
            pdf = resume_pdf(row)
            print(f"\n[{n}/{len(rows)}] {row['company']} - {row['role']}")
            print(f"  Resume: {pdf}")
            print("  Type v at any prompt to open the resume again.")
            fill_job(page, row, tracker, claude, profile, resume_text, settings, log)
            print("  Check every field, then click Submit in the browser yourself.")
            choice = _ask_outcome(pdf)
            if choice == "y":
                tracker.update_status(row["id"], "applied")
                counts["submitted"] += 1
            elif choice == "s":
                tracker.update_status(row["id"], "skipped")
                counts["skipped"] += 1
            elif choice == "n":
                counts["later"] += 1
            else:
                counts["later"] += len(rows) - n + 1
                break
        window.close()
    return counts
