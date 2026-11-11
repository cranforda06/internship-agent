"""A log of what happened while applying, saved to data/logs/apply.log.

It records what the agent did on each page (questions it found, which it
filled, why it waited) so problems can be looked into afterwards. It records
question names only, never your answers. data/ is never committed to git.
"""

from datetime import datetime

from agent.config import PROJECT_ROOT

LOG_PATH = PROJECT_ROOT / "data" / "logs" / "apply.log"


def write(line):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {line.rstrip()}\n")
    except OSError:
        pass   # a log problem should never stop an application


def logged(log):
    """Wrap a `log` function so everything it shows is also saved to the file."""
    def both(message):
        write(message.strip())
        log(message)
    return both
