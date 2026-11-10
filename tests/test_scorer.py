"""Tests for scoring, using a FAKE Claude so they're free and work offline."""

import json
from types import SimpleNamespace

import pytest

from agent.scorer import ScoreError, Scorer, score_found_jobs
from agent.tracker import Tracker


class FakeClient:
    """Pretends to be the Anthropic client and returns canned answers."""

    def __init__(self, answers):
        self.answers = list(answers)  # each one: (stop_reason, score dict)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        stop_reason, payload = self.answers.pop(0)
        return SimpleNamespace(
            stop_reason=stop_reason,
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=json.dumps(payload))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
        )


def answer(score):
    return ("end_turn", {"score": score, "summary": "ok",
                         "matching_strengths": ["SQL"], "gaps": []})


def make_scorer(answers):
    s = Scorer(api_key="fake", resume_text="resume", model="claude-opus-5-5")
    s.client = FakeClient(answers)
    return s


def test_score_parses_answer_and_tracks_cost():
    s = make_scorer([answer(80)])
    result = s.score("job")
    assert result["score"] == 80
    assert s.cost() == pytest.approx((1000 * 4 + 200 * 20) / 1_000_000)


def test_refusal_raises():
    s = make_scorer([("refusal", {})])
    with pytest.raises(ScoreError):
        s.score("job")


def test_score_found_jobs_marks_weak_matches_skipped(tmp_path):
    t = Tracker(tmp_path / "t.db")
    good = t.add("Acme", "Data Analyst Intern", status="found", description="SQL work", posted="2026-11-02")
    weak = t.add("Globex", "IT Intern", status="found", description="Help desk", posted="2026-11-01")
    config = {"scoring": {"min_fit_score": 65}}
    # Newest posting is scored first, so Acme gets 80 and Globex gets 40.
    counts = score_found_jobs(config, t, make_scorer([answer(80), answer(40)]), limit=10, log=lambda m: None)

    assert counts == {"good": 1, "skipped": 1, "errors": 0}
    assert t.get(good)["status"] == "found" and t.get(good)["fit_score"] == 80
    assert t.get(weak)["status"] == "skipped"
    assert [r["id"] for r in t.scored_matches()] == [good]
    t.close()


def test_company_warning_finds_past_applications(tmp_path):
    t = Tracker(tmp_path / "t.db")
    t.add("Elmington", "Unknown role", status="applied")
    new = t.add("Elmington", "Business Analyst Intern", status="found")
    assert len(t.applied_at_company("Elmington", exclude_id=new)) == 1
    t.close()
