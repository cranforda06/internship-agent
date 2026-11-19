import argparse
import json
import sys
from datetime import date

from agent.config import get_api_key, load_config
from agent.resume import ResumeError, load_resume, split_sections
from agent.tracker import STATUSES, DuplicateError, Tracker, parse_date


def ask(prompt, default=None):
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def cmd_add(tracker, args):
    company = args.company or ask("Company")
    role = args.role or ask("Role")
    link = args.link if args.link is not None else ask("Link (optional)")
    status = args.status or ask("Status", default="applied")
    if args.date is not None:
        raw_date = args.date
    elif status == "found":
        raw_date = None
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
        rows = [r for r in rows if r["status"] not in ("found", "skipped")]
    if not rows:
        print("No applications yet.")
        return 0
    print(f"{'#':<4} {'Company':<22} {'Role':<36} {'Status':<10} {'Applied':<11}")
    print("-" * 86)
    from pathlib import Path

    from agent.config import PROJECT_ROOT

    for r in rows:
        print(f"{r['id']:<4} {r['company'][:22]:<22} {r['role'][:36]:<36} "
              f"{r['status']:<10} {r['date_applied'] or '':<11}")
        if r["tailored_dir"]:
            folder = Path(r["tailored_dir"])
            if folder.is_relative_to(PROJECT_ROOT):
                folder = folder.relative_to(PROJECT_ROOT)
            print(f"     Resume: {folder}/")
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
    from agent.finder import fill_descriptions, find_new_jobs

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
    from agent.llm import Claude

    try:
        return Claude(get_api_key()), load_resume(config["resume_path"])
    except (RuntimeError, ResumeError) as e:
        print(e)
        return None


def _run_with_api(claude, work):
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
    from datetime import datetime

    from agent import schedule

    now = datetime.now()
    if args.scheduled_at:
        hour, minute = schedule.parse_time(args.scheduled_at)
        if not schedule.should_run(now, hour, minute, args.weekdays_only, schedule.last_run_date()):
            return 0

    if not args.notify:
        return _prepare(config, tracker, args)[0]

    print(f"\n===== Scheduled run: {now:%Y-%m-%d %H:%M} =====")
    try:
        code, message = _prepare(config, tracker, args)
    except Exception as e:
        code, message = 1, f"Something went wrong ({e.__class__.__name__}). See data/logs/daily-prepare.log"
        print(f"ERROR: {e!r}")
    if code == 0 and args.scheduled_at:
        schedule.record_run(now.date())
    schedule.notify("Internship agent" if code == 0 else "Internship agent: problem", message)
    return code


def _prepare(config, tracker, args):
    from agent.scorer import Scorer, score_found_jobs
    from agent.tailor import tailor_queue

    from agent.approval import auto_approve

    size = args.count or config["daily"]["queue_size"]
    queued = len(tracker.list_all(status="queued")) + len(tracker.list_all(status="approved"))
    need = size - queued
    if need <= 0:
        print(f"You already have {queued} tailored job(s) waiting (to review or apply). "
              f"Finish those first: python main.py review / python main.py apply")
        return 0, f"{queued} jobs from before are still waiting. Run: python main.py review or apply"

    if not args.no_find:
        print("Step 1/3: Finding new internships...")
        cmd_find(config, tracker, args)
    setup = _setup_claude(config)
    if not setup:
        return 1, "Couldn't start: check your API key in .env and data/resume.md."
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
        return 1, "The Anthropic API returned an error (out of credit or offline?). See the log."
    print(f"{done} new job(s) tailored.")
    cost = f" (cost ${claude.cost_so_far:.2f})"

    print("\nAuto-approving strong matches...")
    auto_approve(config, tracker)
    to_review = len(tracker.list_all(status="queued"))
    to_apply = len(tracker.list_all(status="approved"))
    print(f"\nReady to apply: {to_apply} (python main.py apply)   "
          f"Need your review: {to_review} (python main.py review)")
    if done == 0 and not to_apply and not to_review:
        return 0, "No new good matches today." + cost
    return 0, f"{to_apply} ready to apply, {to_review} to review." + cost


def cmd_schedule(config, tracker, args):
    from agent import schedule

    if args.off:
        removed = schedule.uninstall()
        print("Daily schedule turned off." if removed else "There was no daily schedule to turn off.")
        return 0
    if args.time:
        weekdays_only = not args.every_day
        try:
            hour, minute = schedule.parse_time(args.time)
            schedule.install(hour, minute, weekdays_only)
        except (ValueError, RuntimeError) as e:
            print(e)
            return 1
        when = schedule.format_time(hour, minute)
        days = "every weekday (Mon–Fri)" if weekdays_only else "every day"
        print(f"✓ Schedule on: 'prepare' runs {days} at {when}.")
        print("  Mac asleep then? It runs when it wakes. Mac shut down? It runs when you log in.")
        print("  It runs at most once a day, and you get a notification when jobs are ready.")
        print(f"  Log: {schedule.LOG_PATH}")
        print("  Turn off anytime: python main.py schedule --off")
        return 0
    current = schedule.current_schedule()
    if current is None:
        print("Daily schedule is OFF. Turn it on with e.g.: python main.py schedule --time 7:00")
    else:
        hour, minute, weekdays_only = current
        days = "every weekday (Mon–Fri)" if weekdays_only else "every day"
        print(f"Schedule is ON: {days} at {schedule.format_time(hour, minute)}.")
        last = schedule.last_run_date()
        print(f"Last completed run: {last.isoformat() if last else 'not yet'}")
    lines = schedule.last_log_lines()
    if lines:
        print("\nLast run's log:")
        for line in lines:
            print(f"  {line}")
    return 0


def cmd_go(config, tracker, args):
    from datetime import date

    from agent import schedule
    from agent.approval import auto_approve

    today = date.today()
    print("=== Step 1/2: Getting today's jobs ready ===")
    if schedule.last_run_date() == today:
        print("Already done today (by the schedule or an earlier run), nothing to pay for.")
    else:
        code, message = _prepare(config, tracker, args)
        if code != 0:
            print(f"Couldn't prepare new jobs: {message}")
            print("Continuing with the jobs you already have.")
        else:
            schedule.record_run(today)

    auto_approve(config, tracker)
    print("\n=== Step 2/2: Review and apply on the home page ===")
    if not tracker.list_all(status="queued") and not tracker.list_all(status="approved"):
        print("Nothing to review or apply to today. All done!")
        return 0
    return cmd_home(config, tracker, args, auto_approved=True)


def _auto_approve_quietly(config, tracker):
    from agent.approval import auto_approve

    approved, _ = auto_approve(config, tracker, log=lambda m: None)
    if approved:
        print(f"Auto-approved {len(approved)} strong match(es) from your queue (fit "
              f"{config['daily']['auto_approve_min_fit']}+).")


def _print_counts(counts):
    if counts:
        print(f"Submitted: {counts['submitted']}   Saved for later: {counts['later']}   "
              f"Skipped: {counts['skipped']}")


def cmd_home(config, tracker, args, auto_approved=False):
    from agent.home import run_home

    if not auto_approved:
        _auto_approve_quietly(config, tracker)
    _print_counts(run_home(config, tracker, port=args.port))
    return 0


def cmd_apply(config, tracker, args):
    from agent.apply import apply_in_terminal

    _auto_approve_quietly(config, tracker)
    _print_counts(apply_in_terminal(tracker, only_ids=args.ids))
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
    print(f"\n{len(rows)} waiting. Full details for one, e.g.: python main.py show {rows[0]['id']}")
    return 0


def _warning_for(tracker, row):
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


def cmd_today(config, tracker, args):
    from datetime import date

    from agent.filters import adjusted_score, is_preferred_location

    day = args.date or date.today().isoformat()
    search = config["search"]
    preferred = search.get("preferred_locations", [])
    rows = tracker.list_all()

    def line(r, extra=""):
        star = "★" if is_preferred_location(r["location"], preferred) else " "
        fit = f"fit {r['fit_score']:<3}" if r["fit_score"] is not None else "not scored"
        return (f"  #{r['id']:<5}{star} {fit:10} {r['status']:9} {r['company'][:24]:24} "
                f"{r['role'][:44]}{extra}")

    found = [r for r in rows if r["date_added"] == day and r["source"]]
    scored = [r for r in rows if r["scored_at"] == day]
    tailored = [r for r in rows if r["tailor_report"]
                and json.loads(r["tailor_report"]).get("date") == day]
    applied = [r for r in rows if r["date_applied"] == day and r["status"] != "found"]

    print(f"=== {day} ===")
    print(f"\nNew listings found ({len(found)}):")
    for r in found:
        note = f"  ({r['notes']})" if r["status"] == "skipped" and r["notes"] else ""
        print(line(r, note))
    if not found:
        print("  none")
    print(f"\nScored ({len(scored)}), best first:")
    for r in sorted(scored, key=lambda r: -adjusted_score(r["fit_score"], r["location"], search)):
        print(line(r))
    if not scored:
        print("  none")
    print(f"\nResumes tailored ({len(tailored)}):")
    for r in tailored:
        print(line(r))
    if not tailored:
        print("  none")
    print(f"\nApplied ({len(applied)}):")
    for r in applied:
        print(line(r))
    if not applied:
        print("  none")
    print("\nStatus: found = waiting · queued = needs your review · approved = ready to apply · "
          "skipped = below your minimum or filtered out")
    example = (scored or found or tailored or [{"id": 42}])[0]["id"]
    print(f"Details for one job, e.g.: python main.py show {example}   (use the number after #)")
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

    p = sub.add_parser("today", help="What the agent found, scored, and tailored today")
    p.add_argument("--date", help="Another day instead, e.g. 2026-11-09")

    p = sub.add_parser("tailor", help="Tailor your resume for one job (uses API credits)")
    p.add_argument("id", type=int, help="The # shown by 'jobs'")

    p = sub.add_parser("prepare", help="Daily routine: find, score, and tailor your top matches")
    p.add_argument("--count", type=int, help="How many to prepare (default from config.yaml)")
    p.add_argument("--no-find", action="store_true", help="Skip downloading new listings")
    p.add_argument("--notify", action="store_true", help="Show a notification when done (used by the schedule)")
    p.add_argument("--scheduled-at", help=argparse.SUPPRESS)
    p.add_argument("--weekdays-only", action="store_true", help=argparse.SUPPRESS)

    p = sub.add_parser("schedule", help="Run 'prepare' automatically every weekday")
    p.add_argument("--time", help="When to run, e.g. 7:00 or 6:30pm")
    p.add_argument("--every-day", action="store_true", help="Include weekends (default: weekdays only)")
    p.add_argument("--off", action="store_true", help="Turn the daily schedule off")

    sub.add_parser("queue", help="Show tailored jobs waiting for your review")

    p = sub.add_parser("review", help="Same as home")
    p.add_argument("--port", type=int, default=5050)

    p = sub.add_parser("home", help="Review and apply with buttons on a page in your browser")
    p.add_argument("--port", type=int, default=5050)

    p = sub.add_parser("go", help="Everything in one: prepare, then the home page")
    p.add_argument("--port", type=int, default=5050)
    p.add_argument("--count", type=int, help=argparse.SUPPRESS)
    p.add_argument("--no-find", action="store_true", help=argparse.SUPPRESS)

    p = sub.add_parser("apply", help="Apply to approved jobs, answering in the terminal")
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
        if args.command in ("jobs", "tailor", "prepare", "queue", "review", "apply", "schedule", "go", "today", "home"):
            handler = {"jobs": cmd_jobs, "tailor": cmd_tailor, "prepare": cmd_prepare,
                       "queue": cmd_queue, "review": cmd_home, "apply": cmd_apply,
                       "schedule": cmd_schedule, "go": cmd_go, "today": cmd_today,
                       "home": cmd_home}[args.command]
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
        print("\nCancelled.")
        sys.exit(1)
