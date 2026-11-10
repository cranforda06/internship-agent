"""The commands you run in the terminal.

Examples:
    python main.py add                  # add an application (it asks you questions)
    python main.py import data/past_applications.csv
    python main.py list                 # show your applications
    python main.py list --all           # also show jobs the agent found/skipped
    python main.py status 3 interview   # change job #3's status
    python main.py resume               # check that your resume loads

    python main.py find                 # look for new internships (free)
    python main.py score                # score found jobs with Claude (costs credits)
    python main.py score --limit 25
    python main.py jobs                 # show the best matches
    python main.py show 42              # full details for job #42

    python main.py prepare              # daily: find, score, tailor your top 5
    python main.py queue                # tailored jobs waiting for your review
    python main.py tailor 42            # tailor your resume for one job
    python main.py review               # approve/edit/skip on a page in your browser
    python main.py apply                # fill in approved applications (you click Submit)
"""

import argparse
import json
import sys
from datetime import date

from agent.config import get_api_key, load_config
from agent.resume import ResumeError, load_resume, split_sections
from agent.tracker import STATUSES, DuplicateError, Tracker, parse_date


def ask(prompt, default=None):
    """Ask a question in the terminal. Press Enter to accept the default."""
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def cmd_add(tracker, args):
    company = args.company or ask("Company")
    role = args.role or ask("Role")
    link = args.link if args.link is not None else ask("Link (optional)")
    status = args.status or ask("Status", default="applied")
    # "is not None" so that --date "" means "no date" instead of asking.
    if args.date is not None:
        raw_date = args.date
    elif status == "found":
        raw_date = None  # not applied yet, so no date
    else:
        raw_date = ask("Date applied", default=date.today().isoformat())

    try:
        app_id = tracker.add(company or "", role or "", link=link, status=status,
                             date_applied=parse_date(raw_date))
    except DuplicateError as e:
        print(f"Not added. {e}")
        return 1
    except ValueError as e:
        print(f"Not added: {e}")
        return 1
    print(f"Added #{app_id}: {company} - {role} ({status})")
    return 0


def cmd_import(tracker, args):
    added, duplicates, errors = tracker.import_csv(args.csv_path)
    print(f"Imported {added} application(s).")
    if duplicates:
        print(f"Skipped {len(duplicates)} already in the tracker:")
        for d in duplicates:
            print(f"  {d}")
    if errors:
        print(f"{len(errors)} row(s) had problems and were NOT imported:")
        for e in errors:
            print(f"  {e}")
    return 1 if errors else 0


def cmd_list(tracker, args):
    rows = tracker.list_all(status=args.status)
    if not args.status and not args.all:
        # Hide what the agent found/skipped; those are shown by "jobs".
        rows = [r for r in rows if r["status"] not in ("found", "skipped")]
    if not rows:
        print("No applications yet.")
        return 0
    # Print a simple table. The :<N format pads each column to N characters.
    print(f"{'#':<4} {'Company':<22} {'Role':<36} {'Status':<10} {'Applied':<11}")
    print("-" * 86)
    for r in rows:
        print(f"{r['id']:<4} {r['company'][:22]:<22} {r['role'][:36]:<36} "
              f"{r['status']:<10} {r['date_applied'] or '':<11}")
    print(f"\n{len(rows)} total")
    return 0


def cmd_status(tracker, args):
    try:
        tracker.update_status(args.id, args.new_status)
    except ValueError as e:
        print(e)
        return 1
    print(f"#{args.id} is now '{args.new_status}'.")
    return 0


def cmd_find(config, tracker, args):
    from agent.finder import fill_descriptions, find_new_jobs  # imported here so other commands start fast

    results = find_new_jobs(config, tracker)
    print("\nResults:")
    for label, count in results.most_common():
        print(f"  {count:6}  {label}")

    descriptions = fill_descriptions(tracker)
    if descriptions:
        print("\nJob descriptions:")
        for label, count in sorted(descriptions.items()):
            print(f"  {count:6}  {label}")
    waiting = tracker.count_unscored()
    print(f"\n{waiting} job(s) are waiting to be scored. Next: python main.py score")
    return 0


def _setup_claude(config):
    """Load the API key and resume. Returns (claude, resume_text), or None on error."""
    from agent.llm import Claude

    try:
        return Claude(get_api_key()), load_resume(config["resume_path"])
    except (RuntimeError, ResumeError) as e:
        print(e)
        return None


def _run_with_api(claude, work):
    """Run `work()`, turning API problems into plain messages, and always
    print what the run cost. Returns work()'s result, or None on an API error."""
    import anthropic

    try:
        return work()
    except anthropic.AuthenticationError:
        print("Your API key was rejected. Check the key in your .env file.")
    except anthropic.APIStatusError as e:
        print(f"The API returned an error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        print("Couldn't reach the Anthropic API. Check your internet connection.")
    finally:
        print(f"\n{claude.cost_line()}")
    return None


def cmd_score(config, tracker, args):
    from agent.scorer import Scorer, score_found_jobs

    setup = _setup_claude(config)
    if not setup:
        return 1
    claude, resume_text = setup
    settings = config["scoring"]
    limit = args.limit or settings["default_limit"]
    waiting = tracker.count_unscored()
    if waiting == 0:
        print("Nothing to score. Run 'python main.py find' first.")
        return 0
    print(f"Scoring {min(limit, waiting)} of {waiting} waiting job(s) with {settings['model']}...")

    scorer = Scorer(claude, resume_text, settings["model"], settings.get("effort", "low"))
    counts = _run_with_api(claude, lambda: score_found_jobs(config, tracker, scorer, limit))
    if counts is None:
        return 1
    print(f"Good matches: {counts['good']}   Below your minimum "
          f"({settings['min_fit_score']}), skipped: {counts['skipped']}   Errors: {counts['errors']}")
    left = tracker.count_unscored()
    if left:
        print(f"{left} still waiting. Run score again to continue.")
    print("See your matches: python main.py jobs")
    return 0


def cmd_tailor(config, tracker, args):
    """Tailor your resume for one specific job (by its # from 'jobs')."""
    from agent.tailor import tailor_job

    row = tracker.get(args.id)
    if not row:
        print(f"No job with id {args.id}.")
        return 1
    setup = _setup_claude(config)
    if not setup:
        return 1
    claude, resume_text = setup
    print(f"Tailoring your resume for {row['company']} - {row['role']}...")
    result = _run_with_api(claude, lambda: tailor_job(
        claude, config["tailoring"], resume_text, row, config["output_dir"]))
    if result is None:
        return 1
    report, folder = result
    tracker.update_details(row["id"], tailored_dir=folder, tailor_report=json.dumps(report))
    if row["status"] == "found":
        tracker.update_status(row["id"], "queued")
    _print_report(report, folder)
    return 0


def _print_report(report, folder):
    print(f"\nSaved to: {folder}")
    print("\nWhat changed:")
    for change in report["changes"]:
        print(f"  • {change}")
    problems = report["code_check_problems"]
    issues = report["ai_check_issues"]
    if not problems and not issues and report["pages"] == 1:
        print("\n✓ Truthfulness checks passed. Fits on 1 page.")
        return
    print("\n⚠ Please look at these before using this resume:")
    if report["pages"] > 1:
        print(f"  - The PDF is {report['pages']} pages (should be 1).")
    for p in problems:
        print(f"  - {p}")
    for i in issues:
        print(f"  - [{i['severity']}] \"{i['tailored_text']}\": {i['problem']}")


def cmd_prepare(config, tracker, args):
    """The daily routine: find new jobs, score until there are enough good
    matches, then tailor resumes for the best ones."""
    from agent.scorer import Scorer, score_found_jobs
    from agent.tailor import tailor_queue

    size = args.count or config["daily"]["queue_size"]
    queued = len(tracker.list_all(status="queued"))
    need = size - queued
    if need <= 0:
        print(f"Your queue already has {queued} job(s) waiting for review. "
              f"Review those first: python main.py review")
        return 0

    if not args.no_find:
        print("Step 1/3: Finding new internships...")
        cmd_find(config, tracker, args)
    setup = _setup_claude(config)
    if not setup:
        return 1
    claude, resume_text = setup

    def work():
        have = len(tracker.scored_matches())
        if have < need:
            print(f"\nStep 2/3: Scoring until {need - have} more good match(es) are found...")
            scorer = Scorer(claude, resume_text, config["scoring"]["model"],
                            config["scoring"].get("effort", "low"))
            score_found_jobs(config, tracker, scorer, config["daily"]["max_to_score"],
                             stop_after_good=need - have)
        else:
            print(f"\nStep 2/3: Already have {have} scored match(es), no scoring needed.")
        print(f"\nStep 3/3: Tailoring your resume for the top {need}...")
        return tailor_queue(config, tracker, claude, resume_text, need)

    done = _run_with_api(claude, work)
    if done is None:
        return 1
    print(f"{done} new job(s) tailored. Your queue: {queued + done} waiting for review.")
    print("See them: python main.py queue")
    return 0


def cmd_review(config, tracker, args):
    import webbrowser

    from agent.review import create_app

    url = f"http://127.0.0.1:{args.port}/"
    print(f"Review page: {url}")
    print("It opens in your browser. Press Ctrl+C here when you're done.")
    webbrowser.open(url)
    # One request at a time, because the tracker's database connection can
    # only be used from one thread.
    create_app(config, tracker).run(host="127.0.0.1", port=args.port, threaded=False)
    return 0


def cmd_apply(config, tracker, args):
    from agent.apply.runner import apply_to_approved
    from agent.profile import create_template, load_profile

    profile_path = config["profile_path"]
    setup = _setup_claude(config)
    if not setup:
        return 1
    claude, resume_text = setup
    if not profile_path.exists():
        create_template(profile_path, resume_text)
        print(f"Created {profile_path}. Fill in the blank answers there, then run apply again.")
        return 0
    profile = load_profile(profile_path)
    print("Opening a browser. For each approved job the agent fills in what it can,")
    print("then waits for YOU to check everything and click Submit.")
    counts = _run_with_api(claude, lambda: apply_to_approved(
        config, tracker, claude, profile, resume_text, only_ids=args.ids))
    if counts:
        print(f"Submitted: {counts['submitted']}   Saved for later: {counts['later']}   "
              f"Skipped: {counts['skipped']}")
    return 0


def cmd_queue(config, tracker, args):
    rows = tracker.list_all(status="queued")
    if not rows:
        print("Your queue is empty. Run: python main.py prepare")
        return 0
    from agent.filters import age_text

    for r in rows:
        report = json.loads(r["tailor_report"] or "{}")
        flag = "⚠ needs a look" if report.get("needs_attention") else "✓ checks passed"
        print(f"#{r['id']:<5} fit {r['fit_score']:<3} {flag:16} {r['company'][:26]} - {r['role'][:44]}")
        print(f"       {age_text(r['posted'])} · {r['tailored_dir']}")
    print(f"\n{len(rows)} waiting. Full details for one: python main.py show <#>")
    return 0


def _warning_for(tracker, row):
    """Warn if you've already applied somewhere at this company."""
    past = tracker.applied_at_company(row["company"], exclude_id=row["id"])
    if not past:
        return ""
    roles = "; ".join(f"{p['role']} ({p['status']})" for p in past[:2])
    return f"⚠ already applied at {row['company']}: {roles}"


def cmd_jobs(config, tracker, args):
    from agent.filters import adjusted_score, is_preferred_location

    search = config["search"]
    preferred = search.get("preferred_locations", [])
    rows = tracker.scored_matches()
    if not rows:
        print("No scored matches yet. Run 'python main.py find' then 'python main.py score'.")
        return 0
    # Best first, counting the bonus for Richmond/DC.
    rows = sorted(rows, key=lambda r: -adjusted_score(r["fit_score"], r["location"], search))

    from agent.filters import posting_age_days
    from agent.sources.trust import classify

    print(f"{'#':<5} {'Rank':<5} {'Fit':<4} {'Age':<5} {'Company':<24} {'Role':<40} {'Location':<18}")
    print("-" * 106)
    for r in rows:
        star = "★" if is_preferred_location(r["location"], preferred) else " "
        rank = adjusted_score(r["fit_score"], r["location"], search)
        days = posting_age_days(r["posted"])
        age = f"{days}d" if days is not None else "?"
        print(f"{r['id']:<5} {rank:<3}{star}  {r['fit_score']:<4} {age:<5} {r['company'][:24]:<24} "
              f"{r['role'][:40]:<40} {(r['location'] or '')[:18]:<18}")
        warning = _warning_for(tracker, r)
        if warning:
            print(f"      {warning}")
        level, where = classify(r["link"], r["company"])
        if level == "unverified":
            print(f"      ⚠ unverified site ({where}): make sure it's the company's real careers page")
    bonus = search.get("preferred_location_bonus", 0)
    print(f"\n{len(rows)} match(es). Fit = skills match from Claude. "
          f"Rank = Fit + {bonus} if ★ (Richmond/DC area). Age = days since posted.")
    print("Details for one job: python main.py show 123   (use the number in the # column)")
    return 0


def cmd_show(tracker, args):
    row = tracker.get(args.id)
    if not row:
        print(f"No job with id {args.id}.")
        return 1
    print(f"{row['company']} - {row['role']}")
    from agent.filters import age_text
    from agent.sources.trust import classify

    print(f"Status: {row['status']}   Location: {row['location'] or 'n/a'}   "
          f"Posted: {row['posted'] or 'n/a'} ({age_text(row['posted'])})")
    print(f"Link: {row['link'] or 'n/a'}")
    level, where = classify(row["link"], row["company"])
    print({"hiring_system": f"Source: ✓ {where} (an official hiring system the company uses)",
           "company_site": f"Source: ✓ the company's own site ({where})",
           "unverified": f"Source: ⚠ unverified site ({where}): make sure it's the company's real careers page"}[level])
    warning = _warning_for(tracker, row)
    if warning:
        print(warning)
    if row["fit_summary"]:
        fit = json.loads(row["fit_summary"])
        print(f"\nFit score: {fit['score']}/100"
              + ("" if fit.get("had_description") else "  (title only, no description available)"))
        print(fit["summary"])
        print("\nStrengths:")
        for s in fit["matching_strengths"]:
            print(f"  + {s}")
        print("Gaps:")
        for g in fit["gaps"]:
            print(f"  - {g}")
    if row["notes"]:
        print(f"\nNotes: {row['notes']}")
    if row["tailor_report"]:
        print("\n--- Tailored resume ---")
        _print_report(json.loads(row["tailor_report"]), row["tailored_dir"])
    return 0


def cmd_resume(config, args):
    try:
        text = load_resume(config["resume_path"])
    except ResumeError as e:
        print(e)
        return 1
    sections = split_sections(text)
    print(f"Resume loaded: {len(text.split())} words.")
    print("Sections found: " + ", ".join(name for name in sections if name != "Header"))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="Internship agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="Add an internship to the tracker")
    p.add_argument("--company")
    p.add_argument("--role")
    p.add_argument("--link")
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--date", help="Date applied, e.g. 2026-10-15")

    p = sub.add_parser("import", help="Import past applications from a CSV file")
    p.add_argument("csv_path")

    p = sub.add_parser("list", help="Show your applications")
    p.add_argument("--status", choices=STATUSES, help="Only show this status")
    p.add_argument("--all", action="store_true", help="Include found/skipped jobs too")

    sub.add_parser("find", help="Look for new internships (free)")

    p = sub.add_parser("score", help="Score found jobs with Claude (uses API credits)")
    p.add_argument("--limit", type=int, help="Most jobs to score this run")

    sub.add_parser("jobs", help="Show scored matches, best first")

    p = sub.add_parser("tailor", help="Tailor your resume for one job (uses API credits)")
    p.add_argument("id", type=int, help="The # shown by 'jobs'")

    p = sub.add_parser("prepare", help="Daily routine: find, score, and tailor your top matches")
    p.add_argument("--count", type=int, help="How many to prepare (default from config.yaml)")
    p.add_argument("--no-find", action="store_true", help="Skip downloading new listings")

    sub.add_parser("queue", help="Show tailored jobs waiting for your review")

    p = sub.add_parser("review", help="Open the review page in your browser")
    p.add_argument("--port", type=int, default=5050)

    p = sub.add_parser("apply", help="Fill in applications for approved jobs (you click Submit)")
    p.add_argument("ids", type=int, nargs="*", help="Only these job numbers (default: all approved)")

    p = sub.add_parser("show", help="Show full details for one job")
    p.add_argument("id", type=int)

    p = sub.add_parser("status", help="Change an application's status")
    p.add_argument("id", type=int, help="The # shown by 'list'")
    p.add_argument("new_status", choices=STATUSES)

    sub.add_parser("resume", help="Check that your resume file loads")
    return parser


def main():
    args = build_parser().parse_args()
    config = load_config()

    if args.command == "resume":
        return cmd_resume(config, args)

    tracker = Tracker(config["tracker_path"])
    try:
        if args.command == "find":
            return cmd_find(config, tracker, args)
        if args.command == "score":
            return cmd_score(config, tracker, args)
        if args.command in ("jobs", "tailor", "prepare", "queue", "review", "apply"):
            handler = {"jobs": cmd_jobs, "tailor": cmd_tailor, "prepare": cmd_prepare,
                       "queue": cmd_queue, "review": cmd_review, "apply": cmd_apply}[args.command]
            return handler(config, tracker, args)
        commands = {"add": cmd_add, "import": cmd_import, "list": cmd_list,
                    "status": cmd_status, "show": cmd_show}
        return commands[args.command](tracker, args)
    finally:
        tracker.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        # You pressed Ctrl+C (or Ctrl+D) at a question. Exit quietly.
        print("\nCancelled.")
        sys.exit(1)
