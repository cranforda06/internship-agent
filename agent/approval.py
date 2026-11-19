import json

from agent.sources.trust import classify


def reasons_to_review(tracker, row):
    reasons = []
    report = json.loads(row["tailor_report"] or "{}")
    fit = json.loads(row["fit_summary"] or "{}")
    if report.get("needs_attention"):
        reasons.append("truthfulness check flagged something (or resume over 1 page)")
    if not fit.get("had_description", True):
        reasons.append("scored from the title only")
    if classify(row["link"], row["company"])[0] == "unverified":
        reasons.append("unverified site")
    if tracker.applied_at_company(row["company"], exclude_id=row["id"]):
        reasons.append("you've applied at this company before")
    return reasons


def auto_approve(config, tracker, log=print):
    threshold = config.get("daily", {}).get("auto_approve_min_fit")
    if threshold is None:
        return [], []
    approved, kept = [], []
    for row in tracker.list_all(status="queued"):
        if (row["fit_score"] or 0) < threshold:
            continue
        reasons = reasons_to_review(tracker, row)
        if reasons:
            kept.append(row)
            log(f"  → review page: {row['company']} - {row['role'][:40]} (fit {row['fit_score']}): "
                f"{'; '.join(reasons)}")
        else:
            tracker.update_status(row["id"], "approved")
            approved.append(row)
            log(f"  ✓ auto-approved: {row['company']} - {row['role'][:40]} (fit {row['fit_score']})")
    return approved, kept
