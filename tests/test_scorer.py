import json
from types import SimpleNamespace

import pytest

from agent.llm import Claude
from agent.scorer import ScoreError, Scorer, score_found_jobs
from agent.tracker import Tracker


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
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


def make_claude(answers):
    claude = Claude(api_key="fake")
    claude.client = FakeClient(answers)
    return claude


def make_scorer(answers):
    return Scorer(make_claude(answers), resume_text="resume", model="claude-opus-5-5")


def test_score_parses_answer_and_tracks_cost():
    s = make_scorer([answer(80)])
    result = s.score("job")
    assert result["score"] == 80
    assert s.claude.cost_so_far == pytest.approx((1000 * 4 + 200 * 20) / 1_000_000)


def test_refusal_raises():
    s = make_scorer([("refusal", {})])
    with pytest.raises(ScoreError):
        s.score("job")


def test_score_found_jobs_marks_weak_matches_skipped(tmp_path):
    t = Tracker(tmp_path / "t.db")
    good = t.add("Acme", "Data Analyst Intern", status="found", description="SQL work", posted="2026-11-02")
    weak = t.add("Globex", "IT Intern", status="found", description="Help desk", posted="2026-11-01")
    config = {"scoring": {"min_fit_score": 65}}
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


def test_preferred_locations_scored_first_and_bonus_counts(tmp_path):
    t = Tracker(tmp_path / "t.db")
    far = t.add("Acme", "IT Intern", status="found", description="x", location="Austin, TX", posted="2026-11-05")
    near = t.add("Globex", "IT Intern", status="found", description="x", location="Richmond, VA", posted="2026-11-01")
    config = {"scoring": {"min_fit_score": 65},
              "search": {"preferred_locations": ["Richmond"], "preferred_location_bonus": 10}}
    score_found_jobs(config, t, make_scorer([answer(60)]), limit=1, log=lambda m: None)
    assert t.get(near)["fit_score"] == 60 and t.get(near)["status"] == "found"
    assert t.get(far)["fit_score"] is None
    t.close()


def test_stop_after_good(tmp_path):
    t = Tracker(tmp_path / "t.db")
    for i in range(5):
        t.add(f"Company{i}", "IT Intern", status="found", description="x", posted=f"2026-11-0{i+1}")
    config = {"scoring": {"min_fit_score": 65}}
    counts = score_found_jobs(config, t, make_scorer([answer(80)] * 5), limit=10,
                              log=lambda m: None, stop_after_good=2)
    assert counts["good"] == 2
    assert t.count_unscored() == 3
    t.close()
