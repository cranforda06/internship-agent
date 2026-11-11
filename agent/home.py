"""The home page: review jobs AND apply to them, all with buttons.

Open it with:  python main.py home   (python main.py go opens it too)

How it works, in two halves that talk through "queues" (to-do lists):
- The web page runs in the background. When you click a button, it just
  adds a note to a queue, like "apply to job 42" or "I submitted it".
- The main program reads those notes and does the real work: opening the
  browser and filling in the form, exactly like `python main.py apply`.

The agent still never clicks Submit: you do that in the browser, then click
"I submitted it" on this page.
"""

import queue
import threading
import time

from agent.review import TOKEN, esc, form_button


class ApplySession:
    """What's happening right now, shared by the web page and the main program."""

    MAX_NOTES = 40

    def __init__(self):
        self.lock = threading.Lock()
        self.commands = queue.Queue()   # from the page: ("apply", 42) or ("finish",)
        self.keys = queue.Queue()       # for Workday: "d" done, "u" upload again, "" fill again
        self.outcomes = queue.Queue()   # "y" submitted, "n" later, "s" skip
        self.state = "idle"             # idle -> filling -> ready -> idle
        self.job = None                 # the job being applied to
        self.site = ""
        self.notes = []                 # messages shown on the page while applying
        self.last = ""                  # result of the previous job
        self.finished = False

    def note(self, message):
        print(message)
        with self.lock:
            self.notes.append(message.strip())
            del self.notes[:-self.MAX_NOTES]

    @property
    def busy(self):
        return self.state != "idle"

    # --- called by the web page ---------------------------------------------
    def request_apply(self, job_id):
        with self.lock:
            if self.busy or self.finished:
                return False
            self.state = "filling"   # set now, so a double click doesn't open it twice
            self.notes, self.job, self.last = [], None, ""
        self.commands.put(("apply", job_id))
        return True

    def report_outcome(self, choice):
        with self.lock:
            if self.state != "ready":
                return False
            self.state = "saving"
        self.outcomes.put(choice)
        self.keys.put("d")   # tells a Workday job to stop watching the page
        return True

    def press(self, key):
        if self.state == "ready" and self.site == "workday":
            self.keys.put(key)

    def finish(self):
        with self.lock:
            if self.busy:
                return False
            self.finished = True
        self.commands.put(("finish",))
        return True

    # --- what the page shows ---------------------------------------------
    def panel_html(self):
        with self.lock:
            state, job, site, notes, last = self.state, self.job, self.site, list(self.notes), self.last
        notes_html = ("<div class='notes'>" + "".join(f"<div>{esc(n)}</div>" for n in notes) + "</div>"
                      if notes else "")
        if state == "idle":
            msg = f"<p>{esc(last)}</p>" if last else ""
            return (f"<b>Applying</b>{msg}<p class='muted'>Click <b>Apply</b> on a job below. It opens in a "
                    f"separate browser window, filled in as far as the agent can.</p>")
        if job is None or state == "filling":
            title = f"{esc(job['company'])} - {esc(job['role'])}" if job else "the job"
            return (f"<b>Opening {title} and filling it in…</b>"
                    f"<p class='muted'>This takes a few seconds. Watch the other browser window.</p>{notes_html}")
        if state == "saving":
            return "<b>Saving…</b>"
        jid = job["id"]
        steps = ("<ol><li>In the browser window: click <b>Apply</b>, then <b>Autofill with Resume</b>, and sign in.</li>"
                 "<li>Your resume uploads itself, and Workday fills in what it can from it. For the rest of a "
                 "page, click <b>Fill this page</b> below. Check each page, then click <b>Next</b> yourself.</li>"
                 "<li>On the last page, <b>you</b> click <b>Submit</b>. Then click <b>I submitted it</b> here.</li></ol>"
                 if site == "workday" else
                 "<p>This site isn't auto-filled, so it opened in <b>your normal browser</b>. Apply "
                 "there and upload the resume (<b>View resume</b> above). Then tell the agent below.</p>"
                 if site == "other" else
                 "<p>Check every field in the browser window, finish anything left, and click "
                 "<b>Submit</b> yourself. Then tell the agent below.</p>")
        workday_buttons = ""
        if site == "workday":
            workday_buttons = ("<div class='btns'>"
                               + form_button("/now/key/fill", "Fill this page", "edit") + " "
                               + form_button("/now/key/upload", "Upload resume again", "skip") + "</div>")
        return (f"<div class='row'><b>Applying: {esc(job['company'])} - {esc(job['role'])}</b>"
                f"<a href='/job/{jid}/pdf' target='_blank'>View resume ↗</a></div>{steps}{notes_html}"
                f"{workday_buttons}<div class='btns'>"
                + form_button("/now/outcome/y", "✓ I submitted it", "approve") + " "
                + form_button("/now/outcome/n", "Not yet: keep for later", "edit") + " "
                + form_button("/now/outcome/s", "Skip this job", "skip") + "</div>")


PANEL_SCRIPT = """
<script>
// Keep the "Applying" box up to date while the agent works. If the agent
// becomes free or busy, reload the page so the Apply buttons match.
const busyAtLoad = BUSY;
let shown = document.getElementById('now').innerHTML;
setInterval(async () => {
  try {
    const r = await fetch('/now');
    const d = await r.json();
    if (d.finished) { location.reload(); return; }
    if (d.busy !== busyAtLoad) { location.reload(); return; }
    if (d.html !== shown) { document.getElementById('now').innerHTML = shown = d.html; }
  } catch (e) {}
}, 1500);
</script>"""


def add_routes(app, session, tracker):
    """The buttons that drive applying."""
    from flask import abort, jsonify, redirect, request

    def check_token():
        if request.form.get("token") != TOKEN:
            abort(403)

    @app.get("/now")
    def now():
        return jsonify(html=session.panel_html(), busy=session.busy, finished=session.finished)

    @app.post("/apply/<int:job_id>")
    def apply(job_id):
        check_token()
        row = tracker.get(job_id)
        if not row or row["status"] != "approved":
            abort(404)
        session.request_apply(job_id)
        return redirect("/", code=303)

    @app.post("/now/outcome/<choice>")
    def outcome(choice):
        check_token()
        if choice not in ("y", "n", "s"):
            abort(404)
        session.report_outcome(choice)
        # Wait a moment for the main program to save it, so the lists are right.
        for _ in range(50):
            if session.state == "idle":
                break
            time.sleep(0.1)
        return redirect("/", code=303)

    @app.post("/now/key/<name>")
    def key(name):
        check_token()
        keys = {"fill": "", "upload": "u"}
        if name not in keys:
            abort(404)
        session.press(keys[name])
        return redirect("/", code=303)

    @app.post("/finish")
    def finish():
        check_token()
        session.finish()
        return redirect("/", code=303)


OUTCOME_TEXT = {"y": "Marked as applied ✓", "n": "Kept for later", "s": "Skipped"}


def run_home(config, tracker, claude, profile, resume_text, port=5050, open_browser=True,
             playwright_factory=None):
    """Show the home page and apply to whatever you click, until you click
    "Finish for today" (or press Ctrl+C in the terminal)."""
    import webbrowser

    from werkzeug.serving import make_server

    from agent.apply.runner import BrowserWindow, fill_job, site_for
    from agent.review import create_app
    from agent.tracker import Tracker

    if playwright_factory is None:
        from playwright.sync_api import sync_playwright as playwright_factory

    import logging
    logging.getLogger("werkzeug").setLevel(logging.WARNING)   # hide "GET /now" lines

    session = ApplySession()
    # The web page gets its own connection to the tracker, since it runs
    # at the same time as the main program.
    web_tracker = Tracker(config["tracker_path"])
    app = create_app(config, web_tracker, session=session)
    server = make_server("127.0.0.1", port, app)   # one request at a time (see tracker note)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    print(f"Home page: {url}")
    print("Review and apply there. Leave this terminal open; it shows what the agent is doing.")
    print("Click 'Finish for today' on the page when you're done (or press Ctrl+C here).")
    if open_browser:
        webbrowser.open(url)

    settings = config.get("apply", {})
    counts = {"submitted": 0, "later": 0, "skipped": 0}
    try:
        with playwright_factory() as p:
            window = BrowserWindow(p)
            try:
                while True:
                    try:
                        command = session.commands.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if command[0] == "finish":
                        break
                    row = tracker.get(command[1])
                    if not row or row["status"] != "approved":
                        session.state, session.last = "idle", "That job isn't approved any more."
                        continue
                    _apply_one(session, window, row, tracker, claude, profile, resume_text,
                               settings, counts, fill_job, site_for)
            finally:
                window.close()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        session.finished = True
        time.sleep(0.2)   # let an open page see "finished" before the server stops
        server.shutdown()
        web_tracker.close()
    return counts


def _apply_one(session, window, row, tracker, claude, profile, resume_text, settings, counts,
               fill_job, site_for):
    while not session.keys.empty():          # forget clicks left over from the last job
        session.keys.get_nowait()
    site = site_for(row["link"])
    with session.lock:
        session.job, session.site = dict(row), site
        # Workday fills page by page as you go, so its buttons are live right away.
        session.state = "ready" if site == "workday" else "filling"
    print(f"\n{row['company']} - {row['role']}")
    fill_job(window.page(), row, tracker, claude, profile, resume_text, settings,
             log=session.note, workday_keys=session.keys if site == "workday" else None)
    with session.lock:
        if session.state == "filling":
            session.state = "ready"
    print("  Check every field, click Submit in the browser yourself, then tell the home page.")

    while True:   # wait for your click (checking now and then, so Ctrl+C works)
        try:
            choice = session.outcomes.get(timeout=0.5)
            break
        except queue.Empty:
            continue
    if choice == "y":
        tracker.update_status(row["id"], "applied")
        counts["submitted"] += 1
    elif choice == "s":
        tracker.update_status(row["id"], "skipped")
        counts["skipped"] += 1
    else:
        counts["later"] += 1
    print(f"  {OUTCOME_TEXT[choice]}.")
    with session.lock:
        session.last = f"{row['company']} - {row['role']}: {OUTCOME_TEXT[choice]}"
        session.state, session.job, session.notes = "idle", None, []
