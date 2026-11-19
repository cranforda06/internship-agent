from datetime import date

from agent.filters import JobFilter, age_text, posting_age_days
from agent.finder import mark_closed, refilter_found
from agent.jobs import Job
from agent.sources.trust import classify
from agent.tracker import Tracker

TODAY = date(2026, 11, 9)
SEARCH = {"include_keywords": ["analyst"], "exclude_keywords": ["engineer"],
          "max_posting_age_days": 30}


def job(posted, url="https://acme.wd1.myworkdayjobs.com/x/job/y", company="Acme"):
    return Job(company, "Business Analyst Intern", url, "Richmond, VA", "simplify", posted=posted)


def test_posting_age():
    assert posting_age_days("2026-11-02", TODAY) == 7
    assert age_text("2026-11-08", TODAY) == "posted 1 day ago"
    assert age_text("", TODAY) == "post date unknown"


def test_old_postings_are_dropped_but_unknown_dates_kept():
    f = JobFilter(SEARCH, "Summer 2027", today=TODAY)
    assert f.reason_to_drop(job("2026-10-20")) is None
    assert f.reason_to_drop(job("2026-09-01")) == "posted more than 30 days ago"
    assert f.reason_to_drop(job("")) is None


def test_source_classification():
    assert classify("https://highmark.wd1.myworkdayjobs.com/x", "Highmark Health") == ("hiring_system", "Workday")
    assert classify("https://job-boards.greenhouse.io/acme/jobs/1", "Acme")[0] == "hiring_system"
    assert classify("https://lifeattiktok.com/search/123", "TikTok")[0] == "company_site"
    assert classify("https://careers.hfsinclair.com/job/1", "HF Sinclair")[0] == "company_site"
    assert classify("https://jobs-hiring-now.example.net/apply", "Acme")[0] == "unverified"
    assert classify("http://acme.wd1.myworkdayjobs.com/x", "Acme")[0] == "unverified"


def test_only_verified_sites_option():
    f = JobFilter(dict(SEARCH, only_verified_sites=True), "Summer 2027", today=TODAY)
    assert f.reason_to_drop(job("2026-11-01", url="https://randomjobs.example.net/1")) == "not on a verified site"
    assert f.reason_to_drop(job("2026-11-01")) is None


def test_scored_jobs_that_get_too_old_are_skipped(tmp_path):
    t = Tracker(tmp_path / "t.db")
    old = t.add("Acme", "Business Analyst Intern", status="found", posted="2026-09-01", source="simplify")
    t.update_details(old, fit_score=80)
    new = t.add("Globex", "Business Analyst Intern", status="found", posted="2026-11-01", source="simplify")
    assert refilter_found(t, JobFilter(SEARCH, "Summer 2027", today=TODAY)) == 1
    assert t.get(old)["status"] == "skipped" and t.get(new)["status"] == "found"
    t.close()


def test_closed_jobs_are_detected_only_when_source_loaded(tmp_path):
    t = Tracker(tmp_path / "t.db")
    still_open = t.add("Acme", "Analyst Intern", link="https://a.com/1", status="found", source="simplify")
    gone = t.add("Globex", "Analyst Intern", link="https://a.com/2", status="queued", source="simplify")
    approved = t.add("Initech", "Analyst Intern", link="https://a.com/3", status="approved", source="simplify")
    listed = [Job("Acme", "Analyst Intern", "https://a.com/1", "", "simplify")]

    assert mark_closed(t, listed, failed={"simplify"}) == 0
    assert mark_closed(t, listed, failed=set()) == 1
    assert t.get(still_open)["status"] == "found"
    assert t.get(gone)["status"] == "skipped"
    assert t.get(approved)["status"] == "approved"
    t.close()
