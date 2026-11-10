"""The commands you run in the terminal.

Examples:
    python main.py add                  # add an application (it asks you questions)
    python main.py import data/past_applications.csv
    python main.py list                 # show everything in the tracker
    python main.py list --status applied
    python main.py status 3 interview   # change job #3's status
    python main.py resume               # check that your resume loads
"""

import argparse
import sys
from datetime import date

from agent.config import load_config
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

    p = sub.add_parser("list", help="Show everything in the tracker")
    p.add_argument("--status", choices=STATUSES, help="Only show this status")

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
        commands = {"add": cmd_add, "import": cmd_import, "list": cmd_list, "status": cmd_status}
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
