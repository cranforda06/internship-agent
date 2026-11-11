"""The home page's website: a small website that runs only on your computer.

Open it with:  python main.py home
It lists the jobs whose resumes were tailored ("queued"). For each one you
see the posting, the fit score, and your tailored resume with every change
marked, then choose Approve, Edit, or Skip. Approved jobs get an Apply
button (see agent/home.py).

It only listens on 127.0.0.1 (your own machine), so nobody else can open it.
"""

import difflib
import html
import json
import re
import secrets
from pathlib import Path

from flask import Flask, abort, redirect, request, send_file

from agent import render
from agent.filters import age_text
from agent.sources.trust import classify
from agent.tailor import code_checks

# A random password for this session's buttons, so other websites you have
# open can't press them for you.
TOKEN = secrets.token_hex(16)

STYLE = """
:root { --bg:#f6f7f9; --card:#fff; --text:#1d2330; --muted:#5d6676; --line:#dfe3ea;
        --green:#e3f6e8; --greenb:#2f8f4e; --yellow:#fff4d6; --yellowb:#a87b00;
        --red:#fde7e7; --redb:#b42318; --blue:#2457c5; }
* { box-sizing: border-box; }
body { margin:0; font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       background:var(--bg); color:var(--text); }
header { background:#1d2330; color:#fff; padding:14px 24px; display:flex; gap:20px; align-items:center; }
header a { color:#fff; text-decoration:none; font-weight:600; }
main { max-width:1300px; margin:0 auto; padding:20px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; margin-bottom:14px; }
.row { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
.muted { color:var(--muted); font-size:13px; }
.pill { display:inline-block; padding:2px 9px; border-radius:99px; font-size:12px; font-weight:600; }
.ok { background:var(--green); color:var(--greenb); } .warn { background:var(--yellow); color:var(--yellowb); }
.bad { background:var(--red); color:var(--redb); }
.grid { display:grid; grid-template-columns: 1fr 1.25fr; gap:16px; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
.resume div { padding:2px 8px; border-left:3px solid transparent; white-space:pre-wrap; font-size:14px; }
.resume .changed { background:var(--yellow); border-color:var(--yellowb); }
.resume .new { background:var(--red); border-color:var(--redb); }
.resume .was { color:var(--muted); font-size:12px; padding-left:20px; }
.removed { color:var(--muted); text-decoration:line-through; font-size:13px; }
button, .btn { font:inherit; font-weight:600; border:0; border-radius:8px; padding:9px 16px; cursor:pointer;
               text-decoration:none; display:inline-block; }
.approve { background:#2f8f4e; color:#fff; } .skip { background:#e6e8ec; color:#1d2330; }
.edit { background:#2457c5; color:#fff; }
textarea { width:100%; min-height:600px; font:13px/1.45 ui-monospace, Menlo, monospace; padding:10px;
           border:1px solid var(--line); border-radius:8px; }
details summary { cursor:pointer; font-weight:600; }
.posting { white-space:pre-wrap; font-size:13px; max-height:420px; overflow:auto; }
a { color:var(--blue); }
ul { margin:6px 0; padding-left:20px; }
.now { border:2px solid var(--blue); }
.notes { font:12px/1.5 ui-monospace, Menlo, monospace; background:var(--bg); border-radius:8px;
         padding:8px 10px; margin:8px 0; max-height:260px; overflow:auto; white-space:pre-wrap; }
.btns { margin-top:10px; display:flex; gap:8px; flex-wrap:wrap; }
button:disabled { opacity:.45; cursor:not-allowed; }
"""


def page(title, body, heading="Internship agent"):
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width, initial-scale=1'><title>{html.escape(title)}</title>"
            f"<style>{STYLE}</style></head><body><header><a href='/'>{html.escape(heading)}</a>"
            f"<span class='muted' style='color:#aab'>Only you can see this page.</span></header>"
            f"<main>{body}</main></body></html>")


def esc(text):
    return html.escape(str(text or ""))


def source_pill(row):
    """A small label saying whether the job link is on a verified site."""
    level, where = classify(row["link"], row["company"])
    if level == "hiring_system":
        return f"<span class='pill ok' title='An official hiring system the company uses'>✓ {esc(where)}</span>"
    if level == "company_site":
        return f"<span class='pill ok' title='{esc(where)}'>✓ company's own site</span>"
    return (f"<span class='pill bad' title='Make sure this is the company&#39;s real careers page'>"
            f"⚠ unverified site: {esc(where)}</span>")


def _short(location, limit=90):
    """Long location lists (some jobs list every state) get cut short."""
    location = location or ""
    return location if len(location) <= limit else location[:limit].rsplit(";", 1)[0] + "; and more"


def form_button(action, label, cls, disabled=False):
    return (f"<form method='post' action='{action}' style='display:inline'>"
            f"<input type='hidden' name='token' value='{TOKEN}'>"
            f"<button class='{cls}'{' disabled' if disabled else ''}>{label}</button></form>")


def _similarity(a, b):
    """How alike two lines are, 0 to 1. Takes the better of two measures:
    letters in order (catches rewording) and shared words in any order
    (catches reordered lists like a skills line)."""
    in_order = difflib.SequenceMatcher(None, a, b).ratio()
    wa, wb = set(re.findall(r"\w+", a.lower())), set(re.findall(r"\w+", b.lower()))
    any_order = len(wa & wb) / len(wa | wb) if wa | wb else 0
    return max(in_order, any_order)


def marked_resume(original, tailored):
    """Show the tailored resume, marking each line as same / reworded / new."""
    orig_lines = [l.strip() for l in original.splitlines() if l.strip()]
    used = set()
    out = []
    for line in [l.strip() for l in tailored.splitlines() if l.strip()]:
        if line in orig_lines:
            used.add(line)
            out.append(f"<div>{esc(line)}</div>")
            continue
        best = max(orig_lines, key=lambda o: _similarity(line, o), default=None)
        if best and _similarity(line, best) >= 0.5:
            used.add(best)
            out.append(f"<div class='changed'>{esc(line)}</div><div class='was'>was: {esc(best)}</div>")
        else:
            out.append(f"<div class='new'>{esc(line)}</div>")
    removed = [l for l in orig_lines if l not in used]
    return "".join(out), removed


def create_app(config, tracker, session=None):
    """The home page's website: reviewing jobs (this file) plus the Apply
    buttons (agent/home.py)."""
    from agent.home import ApplySession, add_routes

    app = Flask(__name__)
    original_path = Path(config["resume_path"])
    session = session or ApplySession()
    add_routes(app, session, tracker)

    def check_token():
        if request.form.get("token") != TOKEN:
            abort(403)

    def get_row(job_id):
        row = tracker.get(job_id)
        if not row or not row["tailored_dir"]:
            abort(404)
        return row

    def job_card(r, apply_button=""):
        report = json.loads(r["tailor_report"] or "{}")
        pill = ("<span class='pill warn'>check flagged items</span>" if report.get("needs_attention")
                else "<span class='pill ok'>checks passed</span>")
        warn = ""
        if tracker.applied_at_company(r["company"], exclude_id=r["id"]):
            warn = " <span class='pill bad'>applied here before</span>"
        return (f"<div class='card row'><div><b>{esc(r['company'])}</b> - {esc(r['role'])}"
                f"<div class='muted'>{esc(_short(r['location']))} · fit {r['fit_score']} · "
                f"{esc(age_text(r['posted']))} · {source_pill(r)}</div></div>"
                f"<div>{pill}{warn} <a class='btn skip' href='/job/{r['id']}'>Open</a> {apply_button}</div></div>")

    def section(title, rows, button=lambda r: ""):
        out = [f"<h2>{title} ({len(rows)})</h2>"]
        if not rows:
            out.append("<p class='muted'>Nothing here.</p>")
        out += [job_card(r, button(r)) for r in rows]
        return out

    @app.get("/")
    def index():
        queued, approved = tracker.list_all(status="queued"), tracker.list_all(status="approved")
        busy = session.busy
        cards = [f"<div class='card now'>{session.panel_html()}</div>"]
        # Oldest approval first, the same order `apply` uses.
        cards += section("Ready to apply", list(reversed(approved)),
                         lambda r: form_button(f"/apply/{r['id']}", "Apply", "approve", disabled=busy))
        cards += section("Waiting for your review", queued)
        cards.append("<div class='card row'><span>Done for today? Jobs you didn't get to stay here "
                     "for next time.</span>"
                     + form_button("/finish", "Finish for today", "skip", disabled=busy) + "</div>")
        return page("Internship agent", "".join(cards))

    @app.get("/job/<int:job_id>")
    def job(job_id):
        r = get_row(job_id)
        folder = Path(r["tailored_dir"])
        tailored = (folder / "resume.md").read_text(encoding="utf-8")
        report = json.loads(r["tailor_report"] or "{}")
        fit = json.loads(r["fit_summary"] or "{}")
        resume_html, removed = marked_resume(original_path.read_text(encoding="utf-8"), tailored)

        issues = "".join(f"<li><span class='pill {'bad' if i['severity'] != 'minor' else 'warn'}'>"
                         f"{esc(i['severity'])}</span> \"{esc(i['tailored_text'])}\": {esc(i['problem'])}</li>"
                         for i in report.get("ai_check_issues", []))
        issues += "".join(f"<li><span class='pill bad'>code check</span> {esc(p)}</li>"
                          for p in report.get("code_check_problems", []))
        if report.get("pages", 1) > 1:
            issues += f"<li><span class='pill bad'>length</span> PDF is {report['pages']} pages</li>"
        checks = (f"<ul>{issues}</ul>" if issues else "<p><span class='pill ok'>All truthfulness checks passed</span></p>")
        past = tracker.applied_at_company(r["company"], exclude_id=r["id"])
        past_html = ("".join(f"<li>{esc(p['role'])} ({esc(p['status'])})</li>" for p in past))
        buttons = ""
        if r["status"] == "queued":
            buttons = (form_button(f"/job/{job_id}/approve", "Approve", "approve") + " " +
                       f"<a class='btn edit' href='/job/{job_id}/edit'>Edit resume</a> " +
                       form_button(f"/job/{job_id}/skip", "Skip", "skip"))
        elif r["status"] == "approved":
            buttons = ("<span class='pill ok'>Approved</span> " +
                       form_button(f"/job/{job_id}/unapprove", "Move back to review", "skip"))
            buttons += " " + form_button(f"/apply/{job_id}", "Apply", "approve", disabled=session.busy)

        body = f"""
        <div class='card row'><div><h2 style='margin:0'>{esc(r['company'])} - {esc(r['role'])}</h2>
          <div class='muted' title='{esc(r['location'])}'>{esc(_short(r['location']))} · {esc(age_text(r['posted']))} · {source_pill(r)} ·
          <a href='{esc(r['link'])}' target='_blank' rel='noopener'>read the posting ↗</a>
          <span>(just to read it: click Apply when you're ready to apply)</span></div></div>
          <div>{buttons}</div></div>
        {"<div class='card' style='border-color:#b42318'><b>⚠ You've applied at this company before:</b><ul>" + past_html + "</ul></div>" if past else ""}
        <div class='grid'>
          <div>
            <div class='card'><b>Fit {esc(fit.get('score'))}/100</b>
              {"" if fit.get('had_description', True) else "<span class='pill warn'>title only</span>"}
              <p>{esc(fit.get('summary'))}</p>
              <b>Strengths</b><ul>{"".join(f"<li>{esc(s)}</li>" for s in fit.get('matching_strengths', []))}</ul>
              <b>Gaps</b><ul>{"".join(f"<li>{esc(g)}</li>" for g in fit.get('gaps', []))}</ul></div>
            <div class='card'><b>Truthfulness checks</b>{checks}</div>
            <div class='card'><b>What changed</b><ul>{"".join(f"<li>{esc(c)}</li>" for c in report.get('changes', []))}</ul>
              {"<b>Removed lines</b>" + "".join(f"<div class='removed'>{esc(l)}</div>" for l in removed) if removed else ""}</div>
            <div class='card'><details><summary>Job posting</summary>
              <div class='posting'>{esc(r['description'] or 'Description not available - open the posting link.')}</div></details></div>
          </div>
          <div class='card'><div class='row'><b>Tailored resume</b>
              <span><a href='/job/{job_id}/pdf' target='_blank'>PDF ↗</a> · <a href='/job/{job_id}/docx'>Word</a></span></div>
            <p class='muted'><span class='pill warn'>yellow</span> reworded (original shown under it) ·
              <span class='pill bad'>red</span> not matched to any original line - check it</p>
            <div class='resume'>{resume_html}</div></div>
        </div>"""
        return page(f"{r['company']} - review", body)

    @app.get("/job/<int:job_id>/edit")
    def edit(job_id):
        r = get_row(job_id)
        text = (Path(r["tailored_dir"]) / "resume.md").read_text(encoding="utf-8")
        body = (f"<div class='card'><h2>Edit resume: {esc(r['company'])} - {esc(r['role'])}</h2>"
                f"<p class='muted'>Same layout as data/resume.md. Saving rebuilds the PDF and Word files "
                f"and re-runs the code checks.</p>"
                f"<form method='post' action='/job/{job_id}/edit'>"
                f"<input type='hidden' name='token' value='{TOKEN}'>"
                f"<textarea name='resume'>{esc(text)}</textarea><p>"
                f"<button class='approve'>Save</button> <a class='btn skip' href='/job/{job_id}'>Cancel</a></p>"
                f"</form></div>")
        return page("Edit resume", body)

    @app.post("/job/<int:job_id>/edit")
    def save_edit(job_id):
        check_token()
        r = get_row(job_id)
        folder = Path(r["tailored_dir"])
        text = request.form.get("resume", "").replace("\r\n", "\n").strip() + "\n"
        report = json.loads(r["tailor_report"] or "{}")
        (folder / "resume.md").write_text(text, encoding="utf-8")
        report["pages"] = render.to_pdf(text, report["pdf"])
        render.to_docx(text, report["docx"])
        report["code_check_problems"] = code_checks(original_path.read_text(encoding="utf-8"), text)
        report["edited_by_you"] = True
        (folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        tracker.update_details(job_id, tailor_report=json.dumps(report))
        return redirect(f"/job/{job_id}", code=303)

    def set_status(job_id, status):
        check_token()
        get_row(job_id)
        tracker.update_status(job_id, status)
        return redirect("/", code=303)

    @app.post("/job/<int:job_id>/approve")
    def approve(job_id):
        return set_status(job_id, "approved")

    @app.post("/job/<int:job_id>/skip")
    def skip(job_id):
        return set_status(job_id, "skipped")

    @app.post("/job/<int:job_id>/unapprove")
    def unapprove(job_id):
        return set_status(job_id, "queued")

    @app.get("/job/<int:job_id>/pdf")
    def pdf(job_id):
        report = json.loads(get_row(job_id)["tailor_report"] or "{}")
        return send_file(report["pdf"], mimetype="application/pdf",
                         as_attachment=bool(request.args.get("download")))

    @app.get("/job/<int:job_id>/docx")
    def docx(job_id):
        report = json.loads(get_row(job_id)["tailor_report"] or "{}")
        return send_file(report["docx"], as_attachment=True)

    return app
