from agent.config import load_config
from agent.filters import JobFilter, is_internship, is_right_term, is_us_location
from agent.jobs import Job
from agent.sources import greenhouse, lever
from agent.sources.web import html_to_text


def make_filter():
    config = load_config()
    return JobFilter(config["search"], config["target_term"])


def job(title, location="Richmond, VA"):
    return Job(company="Acme", title=title, url="https://x.com", location=location, source="test")


def test_internship_detection_ignores_internal_and_international():
    assert is_internship("Data Analyst Intern")
    assert is_internship("Summer Analyst Program")
    assert not is_internship("Internal Audit Manager")
    assert not is_internship("International Payroll Analyst")


def test_us_locations():
    assert is_us_location("Richmond, VA")
    assert is_us_location("Remote in USA")
    assert is_us_location("NYC")
    assert is_us_location("London, UK; New York, NY")
    assert is_us_location("")
    assert not is_us_location("London, UK")
    assert not is_us_location("Toronto, ON, Canada")


def test_term_check():
    assert is_right_term("Data Analyst Intern", "Summer 2027")
    assert is_right_term("Data Analyst Intern (Summer 2027)", "Summer 2027")
    assert not is_right_term("Data Analyst Intern - Fall 2026", "Summer 2027")
    assert not is_right_term("IT Intern 2026", "Summer 2027")


def test_filter_keeps_target_roles():
    f = make_filter()
    assert f.reason_to_drop(job("Business Analyst Intern")) is None
    assert f.reason_to_drop(job("IT Intern")) is None
    assert f.reason_to_drop(job("Data Analytics Intern")) is None


def test_filter_drops_wrong_roles():
    f = make_filter()
    assert f.reason_to_drop(job("Software Engineer Intern")) == "excluded keyword"
    assert f.reason_to_drop(job("Master's Data Science Internship")) == "excluded keyword"
    assert f.reason_to_drop(job("Marketing Intern")) == "not a target role"
    assert f.reason_to_drop(job("Business Analyst")) == "not an internship"
    assert f.reason_to_drop(job("Data Analyst Intern", "London, UK")) == "outside the US"


def test_html_to_text():
    raw = "&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;&lt;ul&gt;&lt;li&gt;SQL&lt;/li&gt;&lt;/ul&gt;"
    text = html_to_text(raw)
    assert "Hello & welcome" in text
    assert "- SQL" in text
    assert "<" not in text


def test_greenhouse_parsing():
    data = {"title": " IT Intern ", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
            "location": {"name": "Richmond, VA"}, "content": "&lt;p&gt;Do IT things&lt;/p&gt;",
            "first_published": "2026-11-01T10:00:00-05:00", "company_name": "Acme"}
    j = greenhouse._to_job(data, "acme")
    assert (j.company, j.title, j.location, j.posted) == ("Acme", "IT Intern", "Richmond, VA", "2026-11-01")
    assert j.description == "Do IT things"


def test_lever_parsing():
    data = {"text": "Data Intern", "hostedUrl": "https://jobs.lever.co/acme/abc",
            "categories": {"location": "Austin, TX", "allLocations": ["Austin, TX", "Remote"]},
            "descriptionPlain": "About the role.",
            "lists": [{"text": "Requirements", "content": "<li>SQL</li>"}],
            "createdAt": 1762000000000}
    j = lever._to_job(data, "acme")
    assert j.location == "Austin, TX; Remote"
    assert "About the role." in j.description and "Requirements:" in j.description
    assert j.posted.startswith("2025-")


def test_description_url_patterns():
    assert greenhouse.URL_PATTERN.search("https://job-boards.greenhouse.io/appian/jobs/123").groups() == ("appian", "123")
    uid = "6ed76ce8-4156-4b60-b120-403538bd66cd"
    assert lever.URL_PATTERN.search(f"https://jobs.lever.co/palantir/{uid}").groups() == ("palantir", uid)


def test_preferred_locations_and_bonus():
    from agent.filters import adjusted_score, is_preferred_location
    search = load_config()["search"]
    prefs = search["preferred_locations"]
    assert is_preferred_location("Richmond, VA", prefs)
    assert is_preferred_location("Arlington County, Arlington, VA", prefs)
    assert is_preferred_location("New York, NY; Washington, DC", prefs)
    assert not is_preferred_location("Seattle, WA", prefs)
    assert adjusted_score(70, "McLean, VA", search) == 80
    assert adjusted_score(70, "Austin, TX", search) == 70
    assert adjusted_score(95, "Richmond, VA", search) == 100


def test_data_science_now_excluded_but_business_systems_kept():
    f = make_filter()
    assert f.reason_to_drop(job("Data Science Intern")) == "excluded keyword"
    assert f.reason_to_drop(job("ERP Implementation Intern")) is None
    assert f.reason_to_drop(job("IT Audit Intern")) is None


def test_refilter_skips_found_jobs_that_no_longer_pass(tmp_path):
    from agent.finder import refilter_unscored
    from agent.tracker import Tracker
    t = Tracker(tmp_path / "t.db")
    keep = t.add("Acme", "Business Analyst Intern", status="found", location="Richmond, VA")
    drop = t.add("Acme", "Data Science Intern", status="found", location="Richmond, VA")
    assert refilter_unscored(t, make_filter()) == 1
    assert t.get(keep)["status"] == "found"
    assert t.get(drop)["status"] == "skipped"
    t.close()


def test_it_engineer_titles_pass_but_other_engineering_does_not():
    search = {"include_keywords": ["analyst"], "it_keywords": ["cloud", "network", "IT support"],
              "exclude_keywords": ["engineer", "engineering", "software engineer", "electrical"]}
    f = JobFilter(search, "Summer 2027")

    def check(title):
        return f.reason_to_drop(Job("X", title, "https://x", "Richmond, VA", "test"))

    assert check("Cloud Engineer Intern") is None
    assert check("IT Support Intern") is None
    assert check("Network Engineering Intern") is None
    assert check("Software Engineer Intern") == "excluded keyword"
    assert check("Electrical Engineering Intern") == "excluded keyword"
    assert check("Mechanical Engineer Intern") == "excluded keyword"
