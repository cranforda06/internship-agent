import json

from agent import review
from agent.home import ApplySession
from agent.tracker import Tracker


def setup(tmp_path, statuses=("approved",)):
    resume = tmp_path / "resume.md"
    resume.write_text("# Pat Doe\npat@example.com\n\n## Skills\n- SQL\n")
    folder = tmp_path / "job"
    folder.mkdir()
    (folder / "resume.md").write_text("# Pat Doe\npat@example.com\n\n## Skills\n- SQL, Excel\n")
    pdf = folder / "Pat_Doe_Resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    t = Tracker(tmp_path / "t.db")
    ids = []
    for i, status in enumerate(statuses):
        job = t.add(f"Company{i}", "IT Intern", link=f"https://example.com/{i}", status=status)
        t.update_details(job, tailored_dir=str(folder), fit_score=80,
                         tailor_report=json.dumps({"pdf": str(pdf), "changes": ["x"], "ai_check_issues": [],
                                                   "code_check_problems": [], "pages": 1}))
        ids.append(job)
    opened = []
    session = ApplySession(open_job=lambda row: opened.append(row["link"]))
    client = review.create_app({"resume_path": resume}, t, session=session).test_client()
    return t, ids, client, session, opened


def click(client, path):
    return client.post(path, data={"token": review.TOKEN})


def test_review_approve_needs_token(tmp_path):
    t, (job,), client, _, _ = setup(tmp_path, statuses=("queued",))
    assert b"Company0" in client.get("/").data
    assert b"was: - SQL" in client.get(f"/job/{job}").data
    assert client.post(f"/job/{job}/approve").status_code == 403
    click(client, f"/job/{job}/approve")
    assert t.get(job)["status"] == "approved"
    t.close()


def test_apply_opens_the_job_then_submitted_and_skip(tmp_path):
    t, (first, second), client, session, opened = setup(tmp_path, statuses=("approved", "approved"))
    home = client.get("/").get_data(as_text=True)
    assert "Ready to apply (2)" in home
    assert client.post(f"/apply/{first}").status_code == 403

    click(client, f"/apply/{first}")
    assert opened == ["https://example.com/0"]
    home = client.get("/").get_data(as_text=True)
    assert "I submitted it" in home and "drag it into the upload box" in home
    assert "disabled" in home
    click(client, "/now/outcome/y")
    assert t.get(first)["status"] == "applied"

    click(client, f"/apply/{second}")
    click(client, "/now/reopen")
    assert opened[-2:] == ["https://example.com/1", "https://example.com/1"]
    click(client, "/now/outcome/s")
    assert t.get(second)["status"] == "skipped"
    assert session.counts == {"submitted": 1, "later": 0, "skipped": 1}

    assert b"All done for today" in click(client, "/finish").data
    assert session.finished
    t.close()


def test_not_yet_keeps_the_job_and_resume_downloads(tmp_path):
    t, (job,), client, session, _ = setup(tmp_path)
    click(client, f"/apply/{job}")
    download = client.get(f"/job/{job}/pdf?download=1")
    assert download.data.startswith(b"%PDF") and "attachment" in download.headers["Content-Disposition"]
    click(client, "/now/outcome/n")
    assert t.get(job)["status"] == "approved"
    assert session.counts["later"] == 1
    t.close()


def test_buttons_do_nothing_at_the_wrong_time(tmp_path):
    t, (job,), client, session, opened = setup(tmp_path)
    click(client, "/now/outcome/y")
    assert t.get(job)["status"] == "approved"
    click(client, f"/apply/{job}")
    click(client, f"/apply/{job}")
    assert len(opened) == 1
    click(client, "/finish")
    assert not session.finished
    t.close()


def test_lists_show_most_recently_posted_first(tmp_path):
    t, ids, client, _, _ = setup(tmp_path, statuses=("queued", "queued", "queued"))
    t.update_details(ids[0], posted="2026-11-01")
    t.update_details(ids[1], posted="2026-11-10")
    t.update_details(ids[2], posted="2026-11-05")
    home = client.get("/").get_data(as_text=True)
    assert home.index("Company1") < home.index("Company2") < home.index("Company0")
    t.close()


def test_shows_fit_before_and_after_tailoring(tmp_path):
    t, (job,), client, _, _ = setup(tmp_path, statuses=("queued",))
    report = json.loads(t.get(job)["tailor_report"])
    assert "→" not in client.get("/").get_data(as_text=True)
    report["tailored_fit_score"] = 87
    t.update_details(job, tailor_report=json.dumps(report))
    assert "fit 80 → 87 tailored" in client.get("/").get_data(as_text=True)
    page = client.get(f"/job/{job}").get_data(as_text=True)
    assert "Tailored resume</span><b>87</b>" in page and "+7" in page
    report["tailored_fit_score"] = 77
    t.update_details(job, tailor_report=json.dumps(report))
    assert "fit 80 (tailored: about the same)" in client.get("/").get_data(as_text=True)
    assert "about the same (-3)" in client.get(f"/job/{job}").get_data(as_text=True)
    t.close()
