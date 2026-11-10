"""Phase 2, step 1: find new internships. Free (no AI calls).

1. Download listings from every source.
2. Drop the ones the keyword filters rule out.
3. Skip anything already in the tracker (applied, skipped, or found before).
4. Save the rest to the tracker with status "found", ready for scoring.
"""

import time
from collections import Counter

from agent.filters import JobFilter
from agent.sources import greenhouse, lever, simplify
from agent.sources.descriptions import fetch_description, site_name
from agent.tracker import DuplicateError


def gather_jobs(config, log=print):
    """Download from every source. One broken source doesn't stop the others."""
    jobs = []

    def collect(label, fetch):
        try:
            found = fetch()
            jobs.extend(found)
            return len(found)
        except Exception as e:  # network problems, a board that was renamed, etc.
            log(f"  ! Couldn't load {label}: {e}")
            return 0

    term = config["target_term"]
    n = collect("SimplifyJobs list", lambda: simplify.fetch(term))
    log(f"  SimplifyJobs {term} list: {n} active listings")

    total = 0
    for board in config.get("greenhouse_boards", []):
        total += collect(f"Greenhouse board '{board}'", lambda: greenhouse.fetch_board(board))
    for board in config.get("lever_boards", []):
        total += collect(f"Lever board '{board}'", lambda: lever.fetch_board(board))
    log(f"  Greenhouse/Lever company boards: {total} jobs (all kinds, not just internships)")
    return jobs


def find_new_jobs(config, tracker, log=print):
    """Run the whole find step. Returns a Counter summarizing what happened."""
    log("Downloading listings...")
    jobs = gather_jobs(config, log)

    job_filter = JobFilter(config["search"], config["target_term"])
    results = Counter()
    for job in jobs:
        reason = job_filter.reason_to_drop(job)
        if reason:
            results[f"dropped: {reason}"] += 1
            continue
        try:
            tracker.add(
                job.company, job.title, link=job.url, status="found",
                location=job.location, source=job.source,
                description=job.description or None, posted=job.posted or None,
            )
            results["new"] += 1
        except DuplicateError as e:
            # Already tracked. Often the same job listed on Simplify AND
            # the company's own board, or something you applied to before.
            if e.existing["status"] == "found" or e.existing["source"]:
                results["already found earlier"] += 1
            else:
                results["already applied / in your tracker"] += 1
    return results


def fill_descriptions(tracker, log=print, pause=0.3):
    """Fetch descriptions for found jobs that don't have one yet.

    `pause` waits a moment between requests so we don't hammer anyone's site.
    Returns a Counter like {"Workday: got it": 120, "other: not available": 40}.
    """
    rows = tracker.missing_descriptions()
    if not rows:
        return Counter()
    log(f"\nGetting job descriptions for {len(rows)} job(s) (about {len(rows) * pause / 60 + 1:.0f} min)...")
    results = Counter()
    for i, row in enumerate(rows, start=1):
        text = fetch_description(row["link"])
        # Save "" when it's not available, so we don't retry it every run.
        tracker.update_details(row["id"], description=text or "")
        results[f"{site_name(row['link'])}: {'got it' if text else 'not available'}"] += 1
        if i % 50 == 0:
            log(f"  {i}/{len(rows)} done")
        time.sleep(pause)
    return results
