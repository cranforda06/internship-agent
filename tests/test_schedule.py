"""Tests for the daily schedule. These never install anything on your Mac."""

import pytest

from agent import schedule


def test_parse_time():
    assert schedule.parse_time("7:00") == (7, 0)
    assert schedule.parse_time("07:30") == (7, 30)
    assert schedule.parse_time("7am") == (7, 0)
    assert schedule.parse_time("6:45pm") == (18, 45)
    assert schedule.parse_time("12am") == (0, 0)
    assert schedule.parse_time("12:15pm") == (12, 15)
    with pytest.raises(ValueError):
        schedule.parse_time("25:00")


def test_plist_runs_prepare_with_notify_using_project_python():
    plist = schedule.build_plist(7, 30)
    args = plist["ProgramArguments"]
    assert args[-2:] == ["prepare", "--notify"]
    assert args[0].endswith("venv/bin/python")
    assert args[1].endswith("main.py")
    assert plist["StartCalendarInterval"] == {"Hour": 7, "Minute": 30}
    assert plist["StandardOutPath"].endswith("data/logs/daily-prepare.log")   # inside data/, never committed


def test_format_time():
    assert schedule.format_time(7, 0) == "7:00 am"
    assert schedule.format_time(18, 5) == "6:05 pm"
    assert schedule.format_time(0, 0) == "12:00 am"
