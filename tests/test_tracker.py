"""Tests for the tracker. Run them with:  pytest

Each test gets a fresh, empty database in a temporary folder (tmp_path),
so tests never touch your real data/applications.db.
"""

import pytest

from agent.tracker import DuplicateError, Tracker, normalize_link, normalize_role


@pytest.fixture
def tracker(tmp_path):
    t = Tracker(tmp_path / "test.db")
    yield t
    t.close()


def test_add_and_list(tracker):
    tracker.add("Acme", "Data Analyst Intern", link="https://acme.com/jobs/1")
    rows = tracker.list_all()
    assert len(rows) == 1
    assert rows[0]["company"] == "Acme"
    assert rows[0]["status"] == "applied"


def test_same_link_is_duplicate(tracker):
    tracker.add("Acme", "Data Analyst Intern", link="https://acme.com/jobs/1")
    with pytest.raises(DuplicateError):
        tracker.add("Acme Corp", "Totally Different Title", link="https://acme.com/jobs/1/")


def test_same_company_and_role_is_duplicate_despite_formatting(tracker):
    tracker.add("Acme Inc.", "Data Analyst Intern - Summer 2027")
    with pytest.raises(DuplicateError):
        tracker.add("acme", "data analyst internship (Summer 2027)")


def test_different_roles_at_same_company_are_allowed(tracker):
    tracker.add("Acme", "Data Analyst Intern")
    tracker.add("Acme", "Business Analyst Intern")
    assert len(tracker.list_all()) == 2


def test_greenhouse_job_ids_are_kept_but_tracking_is_dropped():
    a = normalize_link("https://acme.com/careers?gh_jid=111&utm_source=linkedin")
    b = normalize_link("https://www.acme.com/careers/?gh_jid=111")
    c = normalize_link("https://acme.com/careers?gh_jid=222")
    assert a == b      # same job, different tracking junk
    assert a != c      # different job IDs must NOT match


def test_role_cleanup():
    assert normalize_role("IT Intern, Summer 2027") == "it"
    assert normalize_role("Systems Analyst Internship") == "analyst systems"  # sorted


def test_find_existing_returns_none_for_new_job(tracker):
    assert tracker.find_existing("Acme", "Data Analyst Intern") is None


def test_update_status(tracker):
    app_id = tracker.add("Acme", "IT Intern", status="found")
    tracker.update_status(app_id, "applied")
    row = tracker.list_all()[0]
    assert row["status"] == "applied"
    assert row["date_applied"] is not None  # applying fills in the date


def test_import_csv(tracker, tmp_path):
    csv_file = tmp_path / "past.csv"
    csv_file.write_text(
        "company,role,link,date,status\n"
        "Acme,Data Analyst Intern,,10/15/2026,applied\n"
        "Acme Inc,data analyst intern,,,\n"          # duplicate of line 2
        "Globex,IT Intern,,not-a-date,applied\n"      # bad date
        "Initech,Business Analyst Intern,,2026-09-01,rejected\n"
    )
    added, duplicates, errors = tracker.import_csv(csv_file)
    assert added == 2
    assert len(duplicates) == 1
    assert len(errors) == 1
    acme = tracker.find_existing("Acme", "Data Analyst Intern")
    assert acme["date_applied"] == "2026-10-15"


def test_job_ids_are_ignored_when_matching():
    # The same job, with and without the company's internal ID numbers.
    assert normalize_role("R171828 2027 Intern - Digital Strategy Analyst") == \
           normalize_role("Digital Strategy Analyst Intern")
    assert normalize_role("Business and Technology Intern (Req ID 216186)") == \
           normalize_role("Business and Technology Intern")
    assert normalize_role("10078973-WD 2027 Summer Analyst Program") == \
           normalize_role("Summer Analyst Program")


def test_different_roles_with_ids_stay_different():
    a = normalize_role("Summer Associate Internship (Business Systems Analyst) - 32314")
    b = normalize_role("Summer Associate Internship (Business Intelligence Analyst) - 32354")
    assert a != b


def test_keys_refresh_when_tracker_reopens(tmp_path):
    db = tmp_path / "test.db"
    t = Tracker(db)
    t.add("Acme", "R12345 Data Analyst Intern")
    # Pretend this row was saved under older, stale cleanup rules.
    t.conn.execute("UPDATE applications SET role_key = 'stale'")
    t.conn.commit()
    t.close()

    t = Tracker(db)  # reopening recomputes the keys
    assert t.find_existing("Acme", "Data Analyst Intern") is not None
    t.close()


def test_word_order_does_not_matter():
    assert normalize_role("Business Intelligence Analyst Summer Associate Intern") == \
           normalize_role("Summer Associate Internship (Business Intelligence Analyst) - 32354")


def test_similar_application_and_company_prefix(tmp_path):
    t = Tracker(tmp_path / "t.db")
    t.add("Navy Federal Credit Union", "Summer Associate Internship (Business Systems Analyst) - 32314")
    t.add("VCU Health", "R42650 Student Intern - IT", status="rejected")
    # Shorter company name + shorter title -> probably the same job.
    assert t.similar_application("Navy Federal", "Business Systems Analyst Intern") is not None
    # Different job at the same company -> not flagged.
    assert t.similar_application("Navy Federal", "Credit Risk Analyst Intern") is None
    # A one-word title is too vague to call a match.
    assert t.similar_application("Navy Federal", "Analyst Intern") is None
    # A different company that shares a word -> not flagged.
    assert t.similar_application("Federal Reserve", "Business Systems Analyst Intern") is None
    t.close()


def test_same_company():
    from agent.tracker import normalize_company, same_company
    assert same_company(normalize_company("Navy Federal"), normalize_company("Navy Federal Credit Union"))
    assert same_company(normalize_company("The Boeing Company"), normalize_company("Boeing"))
    assert not same_company(normalize_company("Federal Reserve Bank"), normalize_company("Navy Federal"))
