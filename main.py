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


def cmd_score(config, tracker, args):
    import anthropic

    from agent.scorer import Scorer, score_found_jobs

    try:
        api_key = get_api_key()
        resume_text = load_resume(config["resume_path"])
    except (RuntimeError, ResumeError) as e:
        print(e)
        return 1

    settings = config["scoring"]
    limit = args.limit or settings["default_limit"]
    waiting = tracker.count_unscored()
    if waiting == 0:
        print("Nothing to score. Run 'python main.py find' first.")
        return 0
    print(f"Scoring {min(limit, waiting)} of {waiting} waiting job(s) with {settings['model']}...")

    scorer = Scorer(api_key, resume_text, settings["model"], settings.get("effort", "low"))
    try:
        counts = score_found_jobs(config, tracker, scorer, limit)
    except anthropic.AuthenticationError:
        print("Your API key was rejected. Check the key in your .env file.")
        return 1
    except anthropic.APIStatusError as e:
        print(f"The API returned an error ({e.status_code}): {e.message}")
        return 1
    except anthropic.APIConnectionError:
        print("Couldn't reach the Anthropic API. Check your internet connection.")
        return 1
    finally:
        cost = scorer.cost()
        if cost is not None:
            print(f"\nCost of this run: ${cost:.3f} "
                  f"({scorer.input_tokens:,} input + {scorer.output_tokens:,} output tokens)")

    print(f"Good matches: {counts['good']}   Below your minimum "
          f"({settings['min_fit_score']}), skipped: {counts['skipped']}   Errors: {counts['errors']}")
    left = tracker.count_unscored()
    if left:
        print(f"{left} still waiting. Run score again to continue.")
    print("See your matches: python main.py jobs")
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

    print(f"{'#':<5} {'Rank':<5} {'Fit':<4} {'Company':<24} {'Role':<42} {'Location':<20}")
    print("-" * 104)
    for r in rows:
        star = "★" if is_preferred_location(r["location"], preferred) else " "
        rank = adjusted_score(r["fit_score"], r["location"], search)
        print(f"{r['id']:<5} {rank:<3}{star}  {r['fit_score']:<4} {r['company'][:24]:<24} "
              f"{r['role'][:42]:<42} {(r['location'] or '')[:20]:<20}")
        warning = _warning_for(tracker, r)
        if warning:
            print(f"      {warning}")
    bonus = search.get("preferred_location_bonus", 0)
    print(f"\n{len(rows)} match(es). Fit = skills match from Claude. "
          f"Rank = Fit + {bonus} if ★ (Richmond/DC area).")
    print("Details for one job: python main.py show 123   (use the number in the # column)")
    return 0


def cmd_show(tracker, args):
    row = tracker.get(args.id)
    if not row:
        print(f"No job with id {args.id}.")
        return 1
    print(f"{row['company']} - {row['role']}")
    print(f"Status: {row['status']}   Location: {row['location'] or 'n/a'}   "
          f"Posted: {row['posted'] or 'n/a'}")
    print(f"Link: {row['link'] or 'n/a'}")
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
        if args.command == "jobs":
            return cmd_jobs(config, tracker, args)
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
