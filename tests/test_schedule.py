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
    assert args[2:] == ["prepare", "--notify", "--scheduled-at", "7:30", "--weekdays-only"]
    assert args[0].endswith("venv/bin/python")
    assert args[1].endswith("main.py")
    days = [i["Weekday"] for i in plist["StartCalendarInterval"]]
    assert days == [1, 2, 3, 4, 5]                       # Monday to Friday
    assert plist["RunAtLoad"] is True                    # also checks at login
    assert plist["StandardOutPath"].endswith("data/logs/daily-prepare.log")   # inside data/, never committed


def test_format_time():
    assert schedule.format_time(7, 0) == "7:00 am"
    assert schedule.format_time(18, 5) == "6:05 pm"
    assert schedule.format_time(0, 0) == "12:00 am"


def test_every_day_option():
    plist = schedule.build_plist(7, 0, weekdays_only=False)
    assert len(plist["StartCalendarInterval"]) == 7
    assert "--weekdays-only" not in plist["ProgramArguments"]


def test_should_run_once_per_weekday_after_the_time():
    from datetime import date, datetime
    monday_8am = datetime(2026, 11, 9, 8, 0)
    assert schedule.should_run(monday_8am, 7, 0, True, last_run_date=None)
    assert not schedule.should_run(monday_8am, 7, 0, True, last_run_date=date(2026, 11, 9))  # already ran
    assert not schedule.should_run(datetime(2026, 11, 9, 6, 30), 7, 0, True, None)            # too early
    saturday = datetime(2026, 11, 14, 9, 0)
    assert not schedule.should_run(saturday, 7, 0, True, None)                                 # weekend
    assert schedule.should_run(saturday, 7, 0, False, None)                                    # every-day mode
