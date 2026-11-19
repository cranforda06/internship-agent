from datetime import date

from agent.sources import workday
from agent.tracker import normalize_link

TODAY = date(2026, 11, 16)


def test_posted_date():
    assert workday.posted_date("Posted Today", TODAY) == "2026-11-16"
    assert workday.posted_date("Posted Yesterday", TODAY) == "2026-11-15"
    assert workday.posted_date("Posted 3 Days Ago", TODAY) == "2026-11-13"
    assert workday.posted_date("Posted 30+ Days Ago", TODAY) == "2026-10-16"
    assert workday.posted_date("", TODAY) == ""


def test_location_uses_the_link_when_there_are_several():
    one = {"locationsText": "McLean, VA", "externalPath": "/job/McLean-VA/Intern_R1"}
    many = {"locationsText": "3 Locations", "externalPath": "/job/Richmond-VA/Intern_R2"}
    assert workday._location(one) == "McLean, VA"
    assert workday._location(many) == "Richmond, VA; and 2 more locations"


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def test_fetch_site_combines_searches_and_drops_old_postings(monkeypatch):
    postings = [
        {"title": "Business Analyst Intern", "externalPath": "/job/Richmond-VA/BA-Intern_R1",
         "locationsText": "Richmond, VA", "postedOn": "Posted 2 Days Ago"},
        {"title": "Old Intern", "externalPath": "/job/Plano-TX/Old_R2",
         "locationsText": "Plano, TX", "postedOn": "Posted 30+ Days Ago"},
    ]
    calls = []

    def fake_request(method, url, json, **kwargs):
        calls.append((url, json["searchText"]))
        return FakeResponse({"jobPostings": postings})

    monkeypatch.setattr(workday.web, "request", fake_request)
    jobs = workday.fetch_site("capitalone.wd12.myworkdayjobs.com/Capital_One", "Capital One",
                              max_age_days=14, today=TODAY)
    assert calls[0][0] == "https://capitalone.wd12.myworkdayjobs.com/wday/cxs/capitalone/Capital_One/jobs"
    assert len(calls) == len(workday.SEARCHES)
    assert [j.title for j in jobs] == ["Business Analyst Intern"]
    job = jobs[0]
    assert job.url == "https://capitalone.wd12.myworkdayjobs.com/Capital_One/job/Richmond-VA/BA-Intern_R1"
    assert (job.company, job.location, job.posted, job.source) == (
        "Capital One", "Richmond, VA", "2026-11-14", "workday")


def test_workday_links_match_with_or_without_en_us():
    a = "https://vanguard.wd5.myworkdayjobs.com/en-US/vanguard_external/job/Malvern-PA/Intern_1"
    b = "https://vanguard.wd5.myworkdayjobs.com/vanguard_external/job/Malvern-PA/Intern_1"
    assert normalize_link(a) == normalize_link(b)
