"""Tests for Phase 3: the truthfulness checks, the resume parser, and the
tailoring flow (with a fake Claude, so these are free and offline)."""

import json

from agent import render, tailor
from agent.tailor import code_checks
from agent.tracker import Tracker
from tests.test_scorer import make_claude

ORIGINAL = """# Pat Doe
Richmond, VA | pat@example.com

## Experience
### Production Manager — Acme (Richmond, VA) | September 2024 – Present
- Manage order-to-fulfillment for 50+ weekly shipments with 100% accuracy
- Partnered with a colleague to build DocClean, cutting prep time to under two hours

## Skills
- Tools: SQL, Excel, LucidChart
"""


def test_reordering_and_rewording_passes():
    tailored = """# Pat Doe
Richmond, VA | pat@example.com

## Skills
- Tools: LucidChart, SQL, Excel

## Experience
### Production Manager — Acme (Richmond, VA) | September 2024 – Present
- Partnered with a colleague to gather requirements and build DocClean
- Oversee order-to-fulfillment for 50 weekly shipments with 100% accuracy
"""
    assert code_checks(ORIGINAL, tailored) == []


def test_changed_contact_line_is_caught():
    tailored = ORIGINAL.replace("pat@example.com", "pat@other.com")
    assert any("contact" in p for p in code_checks(ORIGINAL, tailored))


def test_changed_job_title_is_caught():
    tailored = ORIGINAL.replace("### Production Manager", "### Operations Director")
    assert any("Entry line" in p for p in code_checks(ORIGINAL, tailored))


def test_invented_number_is_caught():
    tailored = ORIGINAL.replace("50+ weekly shipments", "75+ weekly shipments")
    assert code_checks(ORIGINAL, tailored) == ["Number not in your original resume: 75"]


def test_parser_reads_resume_layout():
    blocks = render.parse(ORIGINAL)
    kinds = [k for k, _ in blocks]
    assert kinds[:3] == ["name", "contact", "section"]
    entry = next(text for kind, text in blocks if kind == "entry")
    assert entry == ("Production Manager — Acme (Richmond, VA)", "September 2024 – Present")
    assert kinds.count("bullet") == 3


def test_tailor_queue_saves_files_and_queues_job(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "to_pdf", lambda md, path: (open(path, "w").close(), 1)[1])
    t = Tracker(tmp_path / "t.db")
    job = t.add("Acme", "Business Analyst Intern", status="found", description="SQL, requirements")
    t.update_details(job, fit_score=80, fit_summary="{}")

    claude = make_claude([
        ("end_turn", {"resume_markdown": ORIGINAL, "changes": ["Moved Skills up"]}),
        ("end_turn", {"issues": []}),
    ])
    config = {"search": {}, "tailoring": {"model": "claude-opus-5-5"}, "output_dir": tmp_path / "out"}
    assert tailor.tailor_queue(config, t, claude, ORIGINAL, count=5, log=lambda m: None) == 1

    row = t.get(job)
    assert row["status"] == "queued"
    report = json.loads(row["tailor_report"])
    assert report["changes"] == ["Moved Skills up"]
    assert report["needs_attention"] is False
    assert (tmp_path / "out").exists() and list((tmp_path / "out").glob("*/Pat_Doe_Resume.docx"))
    t.close()


def test_flagged_issue_marks_needs_attention(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "to_pdf", lambda md, path: 1)
    monkeypatch.setattr(render, "to_docx", lambda md, path: None)
    t = Tracker(tmp_path / "t.db")
    job = t.add("Acme", "IT Intern", status="found")
    claude = make_claude([
        ("end_turn", {"resume_markdown": ORIGINAL, "changes": []}),
        ("end_turn", {"issues": [{"tailored_text": "led DocClean", "problem": "was a team effort",
                                  "severity": "exaggerated"}]}),
    ])
    report, _ = tailor.tailor_job(claude, {"model": "claude-opus-5-5"}, ORIGINAL, t.get(job), tmp_path)
    assert report["needs_attention"] is True
    t.close()
