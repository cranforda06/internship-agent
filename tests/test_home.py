"""Tests for the home page: clicking Apply / I submitted it / Later / Skip.

The real browser filling is swapped for a fake, so these only check that the
buttons drive the agent correctly. Nothing is opened or submitted.
"""

import json
import socket
import threading
import time

import requests

from agent import review
from agent.apply import runner
from agent.home import ApplySession, run_home
from agent.tracker import Tracker


class FakePlaywright:
    """Stands in for Playwright: a 'browser' with one blank 'page'."""
    def __enter__(self):
        page = type("Page", (), {"is_closed": lambda self: False})()
        context = type("Context", (), {"pages": [page], "close": lambda self: None})()
        self.chromium = type("Chromium", (), {"launch_persistent_context": lambda self, *a, **k: context})()
        return self

    def __exit__(self, *exc):
        return False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def setup(tmp_path, links):
    resume = tmp_path / "resume.md"
    resume.write_text("# Pat Doe\n")
    db = tmp_path / "t.db"
    t = Tracker(db)
    ids = []
    for i, link in enumerate(links):
        job = t.add(f"Company{i}", "IT Intern", link=link, status="approved")
        t.update_details(job, tailored_dir=str(tmp_path), fit_score=80,
                         tailor_report=json.dumps({"pdf": None, "pages": 1}))
        ids.append(job)
    config = {"resume_path": resume, "tracker_path": db, "apply": {"open_resume_automatically": False}}
    return config, t, ids


def start(config, tracker):
    port = free_port()
    result = {}

    def run():
        result["counts"] = run_home(config, tracker, None, {}, "", port=port, open_browser=False,
                                    playwright_factory=FakePlaywright)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):           # wait for the page to start
        try:
            requests.get(base + "/now", timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.1)
    return base, thread, result


def click(base, path):
    return requests.post(base + path, data={"token": review.TOKEN}, timeout=10)


def wait_for(base, state_text, seconds=5):
    for _ in range(int(seconds * 10)):
        if state_text in requests.get(base + "/now", timeout=5).json()["html"]:
            return True
        time.sleep(0.1)
    return False


def test_home_page_apply_then_submitted_and_skip(tmp_path, monkeypatch):
    filled = []

    def fake_fill(page, row, tracker, claude, profile, resume_text, settings, log=print, workday_keys=None):
        filled.append(row["id"])
        log("  ✓ Every required question was filled in.")

    monkeypatch.setattr(runner, "fill_job", fake_fill)
    config, t, (first, second) = setup(tmp_path, ["https://example.com/a", "https://example.com/b"])
    base, thread, result = start(config, t)

    home = requests.get(base + "/").text
    assert "Ready to apply (2)" in home and "Apply" in home
    assert requests.post(base + f"/apply/{first}").status_code == 403     # no token -> refused

    click(base, f"/apply/{first}")
    assert wait_for(base, "I submitted it")
    assert "Every required question was filled in" in requests.get(base + "/now").json()["html"]
    assert "disabled" in requests.get(base + "/").text   # other Apply buttons wait their turn
    click(base, "/now/outcome/y")
    assert t.get(first)["status"] == "applied"

    click(base, f"/apply/{second}")
    assert wait_for(base, "I submitted it")
    click(base, "/now/outcome/s")
    assert t.get(second)["status"] == "skipped"

    click(base, "/finish")
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert filled == [first, second]
    assert result["counts"] == {"submitted": 1, "later": 0, "skipped": 1}
    t.close()


def test_home_page_workday_buttons_reach_the_filler(tmp_path, monkeypatch):
    got = []

    def fake_workday(page, row, tracker, claude, profile, resume_text, settings, log=print, workday_keys=None):
        while True:                       # like workday.assist: run until "d"
            key = workday_keys.get(timeout=10)
            if key == "d":
                return
            got.append(key)

    monkeypatch.setattr(runner, "fill_job", fake_workday)
    config, t, (job,) = setup(tmp_path, ["https://acme.wd5.myworkdayjobs.com/en-US/careers/job/x"])
    base, thread, result = start(config, t)

    click(base, f"/apply/{job}")
    assert wait_for(base, "Upload resume again")      # Workday gets its extra buttons
    click(base, "/now/key/upload")
    click(base, "/now/key/fill")
    click(base, "/now/outcome/n")                     # later: stays approved
    assert got == ["u", ""]
    assert t.get(job)["status"] == "approved"

    click(base, "/finish")
    thread.join(timeout=10)
    assert result["counts"] == {"submitted": 0, "later": 1, "skipped": 0}
    t.close()


def test_buttons_do_nothing_at_the_wrong_time():
    s = ApplySession()
    assert not s.report_outcome("y")       # nothing is being applied to
    assert s.request_apply(1)
    assert not s.request_apply(2)          # a double click doesn't open a second job
    assert not s.finish()                  # can't finish in the middle of a job
