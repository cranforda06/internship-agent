"""Go through your approved jobs one at a time and fill in each application.

For each job:
1. Open it in a real browser window you can see.
2. Upload the tailored resume PDF and fill in every answer we're sure of.
3. Print what's left for you (essays, consents, anything unclear).
4. WAIT. You check the form, finish anything left, and click Submit
   yourself. Then you tell the terminal what happened.

The agent never clicks Submit.

The browser keeps its own profile in data/browser-profile, so sites you log
into (like a company's Workday) stay logged in next time.
"""

import json

from agent.apply import greenhouse, lever
from agent.apply.answers import plan_answers
from agent.config import PROJECT_ROOT

BROWSER_PROFILE = PROJECT_ROOT / "data" / "browser-profile"


def site_for(url):
    if greenhouse.can_handle(url):
        return "greenhouse"
    if lever.can_handle(url):
        return "lever"
    return "other"


def _ask_outcome():
    while True:
        choice = input("\n  Did you submit it?  [y] yes, submitted   [n] not yet (keep for later)   "
                       "[s] skip this job   [q] quit\n  > ").strip().lower()
        if choice in ("y", "n", "s", "q"):
            return choice


def _print_left(left, profile_hint):
    if not left:
        print("  ✓ Every required question was filled in.")
        return
    print(f"  Left for you ({len(left)}):")
    for q in left:
        print(f"    - {q.label[:90]}")
    if profile_hint:
        print("  Tip: fill in blanks in data/profile.yaml and the agent will answer those next time.")


def apply_to_approved(config, tracker, claude, profile, resume_text, log=print):
    from playwright.sync_api import sync_playwright

    rows = tracker.list_all(status="approved")
    if not rows:
        print("No approved jobs. Approve some on the review page first: python main.py review")
        return {}
    settings = config.get("apply", {})
    counts = {"submitted": 0, "later": 0, "skipped": 0}

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            str(BROWSER_PROFILE), headless=False, viewport={"width": 1280, "height": 900},
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        for n, row in enumerate(reversed(rows), start=1):  # oldest approval first
            report = json.loads(row["tailor_report"] or "{}")
            pdf = report.get("pdf")
            print(f"\n[{n}/{len(rows)}] {row['company']} - {row['role']}")
            print(f"  Resume: {pdf}")
            past = tracker.similar_application(row["company"], row["role"])
            if past:
                print(f"  ⚠ This looks like a job you already applied to: {past['role']} "
                      f"({past['status']}). Skip it unless you're sure it's different.")
            site = site_for(row["link"])
            try:
                if site == "greenhouse":
                    questions = greenhouse.get_questions(row["link"])
                    answers = plan_answers(claude, settings.get("answer_model", "claude-opus-5-5"),
                                           profile, resume_text, questions)
                    left = greenhouse.fill(page, row["link"], questions, answers, profile, pdf, log)
                    _print_left(left, True)
                elif site == "lever":
                    questions = lever.open_and_read(page, row["link"])
                    answers = plan_answers(claude, settings.get("answer_model", "claude-opus-5-5"),
                                           profile, resume_text, questions)
                    left = lever.fill(page, questions, answers, pdf, log)
                    _print_left(left, True)
                else:
                    page.goto(row["link"], wait_until="domcontentloaded", timeout=60000)
                    print("  This site isn't auto-filled yet (e.g. Workday). The posting is open in the")
                    print("  browser: apply there, and upload the resume file shown above.")
            except Exception as e:
                print(f"  ! Couldn't fill this form automatically ({e.__class__.__name__}).")
                print("  The page is open: you can still fill it in yourself.")

            print("  Check every field, then click Submit in the browser yourself.")
            choice = _ask_outcome()
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
        browser.close()
    return counts
