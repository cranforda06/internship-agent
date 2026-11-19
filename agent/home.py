import threading

from agent.review import TOKEN, esc, form_button

OUTCOME_TEXT = {"y": "Marked as applied ✓", "n": "Kept for later", "s": "Skipped"}


class ApplySession:
    def __init__(self, open_job=None):
        from agent import apply
        self.open_job = open_job or apply.open_job
        self.lock = threading.Lock()
        self.job = None
        self.warning = ""
        self.last = ""
        self.finished = False
        self.counts = {"submitted": 0, "later": 0, "skipped": 0}

    @property
    def busy(self):
        return self.job is not None

    def start(self, row, tracker):
        with self.lock:
            if self.busy or self.finished:
                return False
            self.job, self.last = dict(row), ""
        past = tracker.similar_application(row["company"], row["role"])
        self.warning = (f"This looks like a job you already applied to: {past['role']} ({past['status']})."
                        if past else "")
        self.open_job(row)
        return True

    def finish_job(self, choice, tracker):
        with self.lock:
            job = self.job
            if job is None:
                return False
            if choice == "y":
                tracker.update_status(job["id"], "applied")
                self.counts["submitted"] += 1
            elif choice == "s":
                tracker.update_status(job["id"], "skipped")
                self.counts["skipped"] += 1
            else:
                self.counts["later"] += 1
            self.last = f"{job['company']} - {job['role']}: {OUTCOME_TEXT[choice]}"
            self.job = None
        print(f"  {self.last}")
        return True

    def panel_html(self):
        job, last, warning = self.job, self.last, self.warning
        if job is None:
            msg = f"<p>{esc(last)}</p>" if last else ""
            return (f"<b>Applying</b>{msg}<p class='muted'>Click <b>Apply</b> on a job below. The application "
                    f"opens in your browser and your tailored resume pops up in Finder.</p>")
        jid = job["id"]
        warn = f"<p><span class='pill bad'>⚠ {esc(warning)}</span></p>" if warning else ""
        return (f"<div class='row'><b>Applying: {esc(job['company'])} - {esc(job['role'])}</b>"
                f"<span><a href='/job/{jid}/pdf' target='_blank'>View resume ↗</a> · "
                f"<a href='/job/{jid}/pdf?download=1'>Download resume</a></span></div>{warn}"
                f"<ol><li>The application opened in a new browser tab.</li>"
                f"<li>Your tailored resume is selected in Finder: <b>drag it into the upload box</b>.</li>"
                f"<li>Fill in the application and click <b>Submit</b> yourself.</li>"
                f"<li>Come back here and tell the agent what happened:</li></ol>"
                f"<div class='btns'>"
                + form_button("/now/outcome/y", "✓ I submitted it", "approve") + " "
                + form_button("/now/outcome/n", "Not yet: keep for later", "edit") + " "
                + form_button("/now/outcome/s", "Skip this job", "skip") + " "
                + form_button("/now/reopen", "Open it again", "skip") + "</div>")


def add_routes(app, session, tracker):
    from flask import abort, redirect, request

    def check_token():
        if request.form.get("token") != TOKEN:
            abort(403)

    @app.post("/apply/<int:job_id>")
    def apply(job_id):
        check_token()
        row = tracker.get(job_id)
        if not row or row["status"] != "approved":
            abort(404)
        session.start(row, tracker)
        return redirect("/", code=303)

    @app.post("/now/outcome/<choice>")
    def outcome(choice):
        check_token()
        if choice not in OUTCOME_TEXT:
            abort(404)
        session.finish_job(choice, tracker)
        return redirect("/", code=303)

    @app.post("/now/reopen")
    def reopen():
        check_token()
        if session.job:
            session.open_job(session.job)
        return redirect("/", code=303)

    @app.post("/finish")
    def finish():
        from agent.review import page
        check_token()
        if session.busy:
            return redirect("/", code=303)
        session.finished = True
        c = session.counts
        return page("Internship agent", f"<div class='card'><h2>All done for today ✓</h2>"
                    f"<p>Submitted: {c['submitted']} · Saved for later: {c['later']} · Skipped: {c['skipped']}</p>"
                    f"<p>You can close this tab.</p></div>", heading="Internship agent")


def run_home(config, tracker, port=5050, open_browser=True, open_job=None):
    import logging
    import webbrowser

    from werkzeug.serving import make_server

    from agent.review import create_app

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    session = ApplySession(open_job)
    app = create_app(config, tracker, session=session)
    server = make_server("127.0.0.1", port, app)
    server.timeout = 0.5
    url = f"http://127.0.0.1:{port}/"
    print(f"Home page: {url}")
    print("Review and apply there. Click 'Finish for today' on the page when you're done.")
    if open_browser:
        webbrowser.open(url)
    try:
        while not session.finished:
            server.handle_request()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return session.counts
