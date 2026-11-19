import pytest

from agent.sources import descriptions


@pytest.fixture
def requested(monkeypatch):
    calls = []

    def fake_get_json(url, timeout=20):
        calls.append(url)
        if "wday/cxs" in url:
            return {"jobPostingInfo": {"jobDescription": "<p>Workday job</p>"}}
        if "hcmRestApi" in url:
            return {"items": [{"ExternalDescriptionStr": "<p>Oracle job</p>"}]}
        if "ashbyhq" in url:
            return {"jobs": [{"id": "e1dfd8b7-fb8a-4ce9-957f-0706b13195c7", "descriptionPlain": "Ashby job"}]}
        if "smartrecruiters" in url:
            return {"jobAd": {"sections": {"jobDescription": {"title": "About", "text": "<p>SR job</p>"}}}}
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(descriptions, "get_json", fake_get_json)
    return calls


def test_workday(requested):
    url = "https://vanguard.wd5.myworkdayjobs.com/en-US/vanguard_external/job/Charlotte-NC/IT-Intern_181765"
    assert descriptions.fetch_description(url) == "Workday job"
    assert requested == ["https://vanguard.wd5.myworkdayjobs.com/wday/cxs/vanguard/vanguard_external/job/Charlotte-NC/IT-Intern_181765"]


def test_oracle(requested):
    url = "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210773869"
    assert descriptions.fetch_description(url) == "Oracle job"
    assert 'Id=%22210773869%22,siteNumber=CX_1001' in requested[0]


def test_ashby(requested):
    url = "https://jobs.ashbyhq.com/telus-digital/e1dfd8b7-fb8a-4ce9-957f-0706b13195c7/application?embed=true"
    assert descriptions.fetch_description(url) == "Ashby job"


def test_smartrecruiters(requested):
    url = "https://jobs.smartrecruiters.com/BoschGroup/744000146524429"
    assert descriptions.fetch_description(url) == "About\nSR job"


def test_unknown_site_returns_none(requested):
    assert descriptions.fetch_description("https://careers.example.com/job/1") is None
    assert requested == []


def test_failed_download_returns_none(monkeypatch):
    def broken(url, timeout=20):
        raise ConnectionError("site down")
    monkeypatch.setattr(descriptions, "get_json", broken)
    url = "https://boeing.wd1.myworkdayjobs.com/INTERN/job/USA/Data-Intern_JR1"
    assert descriptions.fetch_description(url) is None
