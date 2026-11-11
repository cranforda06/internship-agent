"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def apply_log_in_tmp(tmp_path, monkeypatch):
    """Tests write the apply log to a temporary file, never data/logs/apply.log."""
    from agent.apply import history
    monkeypatch.setattr(history, "LOG_PATH", tmp_path / "apply.log")
    return tmp_path / "apply.log"
