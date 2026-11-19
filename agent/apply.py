import json
import subprocess
import sys
import webbrowser
from pathlib import Path


def resume_pdf(row):
    return json.loads(row["tailor_report"] or "{}").get("pdf")


def show_in_finder(pdf):
    if not pdf or not Path(pdf).exists():
        return False
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", pdf], check=False)
    else:
        webbrowser.open(Path(pdf).parent.as_uri())
    return True


def open_job(row):
    webbrowser.open(row["link"])
    return show_in_finder(resume_pdf(row))


def _ask_outcome(pdf):
    while True:
        choice = input("\n  Did you submit it?  [y] yes, submitted   [n] not yet (keep for later)   "
                       "[s] skip this job   [q] quit   [r] show the resume again\n  > ").strip().lower()
        if choice == "r":
            show_in_finder(pdf)
        elif choice in ("y", "n", "s", "q"):
            return choice


def apply_in_terminal(tracker, only_ids=None):
    rows = tracker.list_all(status="approved")
    if only_ids:
        rows = [r for r in rows if r["id"] in only_ids]
    if not rows:
        print("No approved jobs to apply to. Approve one first: python main.py home")
        return {}
    counts = {"submitted": 0, "later": 0, "skipped": 0}
    from agent.review import newest_first
    for n, row in enumerate(newest_first(rows), start=1):
        pdf = resume_pdf(row)
        print(f"\n[{n}/{len(rows)}] {row['company']} - {row['role']}")
        past = tracker.similar_application(row["company"], row["role"])
        if past:
            print(f"  ⚠ This looks like a job you already applied to: {past['role']} ({past['status']}).")
        open_job(row)
        print("  The application is open in your browser, and your tailored resume is")
        print(f"  selected in Finder: {pdf}")
        print("  Apply there yourself, then come back here.")
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
    return counts
