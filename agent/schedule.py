"""Run "prepare" automatically every day, and notify you when it's done.

Uses launchd, the scheduler built into macOS (the same thing macOS uses for
its own background tasks). It's set up as a "launch agent" for your user
account only:
    ~/Library/LaunchAgents/com.internship-agent.prepare.plist
If your Mac is asleep at the scheduled time, macOS runs it when it wakes up.

Turn it on:   python main.py schedule --time 7:00
Turn it off:  python main.py schedule --off
Check it:     python main.py schedule
"""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from agent.config import PROJECT_ROOT

LABEL = "com.internship-agent.prepare"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = PROJECT_ROOT / "data" / "logs" / "daily-prepare.log"


def parse_time(text):
    """'7:00', '07:30', '7am', '6:45pm' -> (hour, minute) in 24-hour time."""
    t = text.strip().lower().replace(" ", "")
    suffix = t[-2:] if t.endswith(("am", "pm")) else ""
    t = t[:-2] if suffix else t
    hour_text, _, minute_text = t.partition(":")
    hour, minute = int(hour_text), int(minute_text or 0)
    if suffix == "pm" and hour != 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"'{text}' isn't a valid time. Try 7:00 or 6:30pm.")
    return hour, minute


def project_python():
    """The project's own Python (in venv/), which has all the packages."""
    venv_python = PROJECT_ROOT / "venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


LAST_RUN_PATH = PROJECT_ROOT / "data" / "logs" / "last-scheduled-run.txt"


def build_plist(hour, minute, weekdays_only=True):
    """The settings file macOS reads. Kept as a function so it can be tested.

    macOS starts the job (a) at the scheduled time (or when the Mac wakes up,
    if it was asleep), and (b) when you log in, in case the Mac was shut down
    at the scheduled time. The job itself then decides whether to actually
    run (see should_run), so it runs at most once per day.
    """
    days = range(1, 6) if weekdays_only else range(0, 7)    # macOS: 0 = Sunday, 1 = Monday
    args = [project_python(), str(PROJECT_ROOT / "main.py"), "prepare", "--notify",
            "--scheduled-at", f"{hour}:{minute:02d}"]
    if weekdays_only:
        args.append("--weekdays-only")
    return {
        "Label": LABEL,
        # Full paths, because scheduled jobs don't see your terminal's settings.
        "ProgramArguments": args,
        "WorkingDirectory": str(PROJECT_ROOT),
        "StartCalendarInterval": [{"Weekday": d, "Hour": hour, "Minute": minute} for d in days],
        "RunAtLoad": True,  # also check at login, to catch up if the Mac was off

        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }


def should_run(now, hour, minute, weekdays_only, last_run_date):
    """Decide if a scheduled start should actually do the work.

    Yes only if: it's a weekday (when weekdays_only), it's at or after the
    scheduled time, and it hasn't already run today.
    """
    if weekdays_only and now.weekday() >= 5:            # Python: 5 = Saturday, 6 = Sunday
        return False
    if (now.hour, now.minute) < (hour, minute):
        return False
    return last_run_date != now.date()


def last_run_date():
    from datetime import date
    try:
        return date.fromisoformat(LAST_RUN_PATH.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def record_run(today):
    LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_PATH.write_text(today.isoformat())


def _launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def install(hour, minute, weekdays_only=True):
    if sys.platform != "darwin":
        raise RuntimeError("Scheduling is set up for macOS only.")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{domain}/{LABEL}")          # remove an older version, if any
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(build_plist(hour, minute, weekdays_only), f)
    result = _launchctl("bootstrap", domain, str(PLIST_PATH))
    if result.returncode != 0:
        # Some macOS versions reject "bootstrap" with a vague "5: Input/output
        # error" but accept the older "load" command for the same file.
        fallback = _launchctl("load", "-w", str(PLIST_PATH))
        loaded = _launchctl("print", f"{domain}/{LABEL}").returncode == 0
        if fallback.returncode != 0 or not loaded:
            raise RuntimeError(f"macOS didn't accept the schedule: {result.stderr.strip()} "
                               f"{fallback.stderr.strip()}".strip())


def uninstall():
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if PLIST_PATH.exists():
        _launchctl("unload", "-w", str(PLIST_PATH))   # older command, in case it was loaded that way
    existed = PLIST_PATH.exists()
    PLIST_PATH.unlink(missing_ok=True)
    return existed


def current_schedule():
    """(hour, minute, weekdays_only) of the installed schedule, or None if it's off."""
    if not PLIST_PATH.exists():
        return None
    with open(PLIST_PATH, "rb") as f:
        plist = plistlib.load(f)
    interval = plist.get("StartCalendarInterval", {})
    first = interval[0] if isinstance(interval, list) else interval
    weekdays_only = "--weekdays-only" in plist.get("ProgramArguments", [])
    return first.get("Hour", 0), first.get("Minute", 0), weekdays_only


def last_log_lines(n=15):
    if not LOG_PATH.exists():
        return []
    return LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]


def notify(title, message):
    """Show a macOS notification. Does nothing on other systems."""
    if sys.platform != "darwin":
        return
    def quote(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    subprocess.run(["osascript", "-e",
                    f"display notification {quote(message)} with title {quote(title)} sound name \"Glass\""],
                   check=False, capture_output=True)


def format_time(hour, minute):
    suffix = "am" if hour < 12 else "pm"
    return f"{(hour % 12) or 12}:{minute:02d} {suffix}"
