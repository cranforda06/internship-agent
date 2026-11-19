import json

from agent.approval import auto_approve
from agent.tracker import Tracker

CONFIG = {"daily": {"auto_approve_min_fit": 75}}
GOOD_REPORT = json.dumps({"needs_attention": False})
WITH_DESC = json.dumps({"had_description": True})


def queued(t, company, fit, report=GOOD_REPORT, fit_summary=WITH_DESC,
           link="https://acme.wd1.myworkdayjobs.com/x/job/1"):
    job = t.add(company, "Business Analyst Intern", link=link, status="queued")
    t.update_details(job, fit_score=fit, tailor_report=report, fit_summary=fit_summary)
    return job


def test_strong_clean_match_is_approved_and_weaker_stays(tmp_path):
    t = Tracker(tmp_path / "t.db")
    strong = queued(t, "Acme", 80)
    exact = queued(t, "Globex", 75, link="https://globex.wd1.myworkdayjobs.com/x/job/2")
    weaker = queued(t, "Initech", 70, link="https://initech.wd1.myworkdayjobs.com/x/job/3")
    approved, kept = auto_approve(CONFIG, t, log=lambda m: None)
    assert {r["id"] for r in approved} == {strong, exact}
    assert t.get(weaker)["status"] == "queued"
    t.close()


def test_strong_match_needing_a_look_goes_to_review(tmp_path):
    t = Tracker(tmp_path / "t.db")
    flagged = queued(t, "Acme", 90, report=json.dumps({"needs_attention": True}))
    title_only = queued(t, "Globex", 90, fit_summary=json.dumps({"had_description": False}),
                        link="https://globex.wd1.myworkdayjobs.com/x/job/2")
    unverified = queued(t, "Initech", 90, link="https://some-random-jobs.example.net/3")
    t.add("Hooli", "Data Analyst Intern", status="applied")
    applied_before = queued(t, "Hooli", 90, link="https://hooli.wd1.myworkdayjobs.com/x/job/4")
    approved, kept = auto_approve(CONFIG, t, log=lambda m: None)
    assert approved == []
    assert {r["id"] for r in kept} == {flagged, title_only, unverified, applied_before}
    t.close()


def test_turned_off_when_setting_missing(tmp_path):
    t = Tracker(tmp_path / "t.db")
    job = queued(t, "Acme", 95)
    assert auto_approve({"daily": {}}, t, log=lambda m: None) == ([], [])
    assert t.get(job)["status"] == "queued"
    t.close()
