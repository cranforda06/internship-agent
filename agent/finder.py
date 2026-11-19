import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from agent.filters import JobFilter
from agent.jobs import Job
from agent.sources import greenhouse, lever, simplify, workday
from agent.sources.descriptions import fetch_description, site_name
from agent.tracker import DuplicateError


def gather_jobs(config, log=print):
    jobs, failed = [], set()

    def collect(label, fetch, source):
        try:
            found = fetch()
            jobs.extend(found)
            return len(found)
        except Exception as e:
            log(f"  ! Couldn't load {label}: {e}")
            failed.add(source)
            return 0

    term = config["target_term"]
    n = collect("SimplifyJobs list", lambda: simplify.fetch(term), "simplify")
    log(f"  SimplifyJobs {term} list: {n} active listings")

    total = 0
    for board in config.get("greenhouse_boards", []):
        total += collect(f"Greenhouse board '{board}'", lambda: greenhouse.fetch_board(board), "greenhouse")
    for board in config.get("lever_boards", []):
        total += collect(f"Lever board '{board}'", lambda: lever.fetch_board(board), "lever")
    log(f"  Greenhouse/Lever company boards: {total} jobs (all kinds, not just internships)")

    sites = config.get("workday_sites") or {}
    max_age = config["search"].get("max_posting_age_days") or 30

    def fetch_workday(item):
        site, company = item
        try:
            return workday.fetch_site(site, company, max_age_days=max_age), None
        except Exception as e:
            return [], f"  ! Couldn't load Workday site for {company}: {e}"

    total = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        for found, error in pool.map(fetch_workday, sites.items()):
            if error:
                log(error)
            jobs.extend(found)
            total += len(found)
    if sites:
        log(f"  Workday company sites: {total} recent postings from {len(sites)} companies")
    return jobs, failed


def refilter_found(tracker, job_filter):
    skipped = 0
    for row in tracker.list_all(status="found"):
        job = Job(row["company"], row["role"], row["link"] or "", row["location"] or "",
                  row["source"] or "", posted=row["posted"] or "")
        reason = job_filter.reason_to_drop(job)
        if reason:
            note = f"Filtered out after a settings change: {reason}"
        else:
            past = tracker.similar_application(row["company"], row["role"])
            note = f"Probably the same job you applied to: {past['role']}" if past else None
        if note:
            tracker.update_status(row["id"], "skipped")
            _set_note(tracker, row["id"], note)
            skipped += 1
    return skipped


def _set_note(tracker, app_id, note):
    with tracker.conn:
        tracker.conn.execute("UPDATE applications SET notes = ? WHERE id = ?", (note, app_id))


refilter_unscored = refilter_found


def mark_closed(tracker, jobs, failed):
    from agent.tracker import normalize_link

    open_links = {normalize_link(j.url) for j in jobs}
    closed = 0
    for status in ("found", "queued"):
        for row in tracker.list_all(status=status):
            if row["source"] not in ("simplify", "greenhouse", "lever") or row["source"] in failed:
                continue
            if normalize_link(row["link"]) not in open_links:
                tracker.update_status(row["id"], "skipped")
                _set_note(tracker, row["id"], "Posting closed: no longer listed as open")
                closed += 1
    return closed


def find_new_jobs(config, tracker, log=print):
    job_filter = JobFilter(config["search"], config["target_term"])
    results = Counter()
    refiltered = refilter_found(tracker, job_filter)
    if refiltered:
        results["earlier finds now skipped (too old, settings, or already applied)"] = refiltered

    log("Downloading listings...")
    jobs, failed = gather_jobs(config, log)
    closed = mark_closed(tracker, jobs, failed)
    if closed:
        results["earlier finds now closed (no longer listed)"] = closed
    for job in jobs:
        reason = job_filter.reason_to_drop(job)
        if reason:
            results[f"dropped: {reason}"] += 1
            continue
        past = tracker.similar_application(job.company, job.title)
        try:
            app_id = tracker.add(
                job.company, job.title, link=job.url,
                status="skipped" if past else "found",
                location=job.location, source=job.source,
                description=job.description or None, posted=job.posted or None,
            )
            if past:
                _set_note(tracker, app_id, f"Probably the same job you applied to: {past['role']}")
                results["probably already applied (similar title)"] += 1
            else:
                results["new"] += 1
        except DuplicateError as e:
            if e.existing["status"] == "found" or e.existing["source"]:
                results["already found earlier"] += 1
            else:
                results["already applied / in your tracker"] += 1
    return results


def fill_descriptions(tracker, log=print, pause=0.3):
    rows = tracker.missing_descriptions()
    if not rows:
        return Counter()
    log(f"\nGetting job descriptions for {len(rows)} job(s) (about {len(rows) * pause / 60 + 1:.0f} min)...")
    results = Counter()
    for i, row in enumerate(rows, start=1):
        text = fetch_description(row["link"])
        tracker.update_details(row["id"], description=text or "")
        results[f"{site_name(row['link'])}: {'got it' if text else 'not available'}"] += 1
        if i % 50 == 0:
            log(f"  {i}/{len(rows)} done")
        time.sleep(pause)
    return results
