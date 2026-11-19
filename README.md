# internship-agent

A personal job-search pipeline that finds internships, ranks them against my resume,
and produces a tailored, fact-checked resume for each one. I review and submit every
application myself.

## What it does

1. **Find.** Pulls new postings every weekday from the SimplifyJobs internship list and
   directly from company career sites on Greenhouse, Lever, and Workday. Keyword
   filters drop non-internships, the wrong term, non-US roles, and anything older
   than 14 days.
2. **Score.** An LLM rates each posting 0–100 against my resume, with strengths and
   gaps. Jobs below a minimum are skipped; preferred locations get a small bonus.
3. **Tailor.** For each good match, the LLM rewrites the resume around the posting's
   key requirements: reordering, rewording, and trimming only.
4. **Fact-check.** Every tailored resume goes through two checks before I see it:
   - a second LLM pass that flags anything fabricated or exaggerated
   - plain Python checks that every number, job title, company, date, and contact
     line matches the original exactly
5. **Review and apply.** A local web page lists the matches, shows each tailored
   resume with every change highlighted, and shows the fit score before and after
   tailoring. Clicking *Apply* opens the real application and hands me the PDF. The
   agent never fills in or submits anything.
6. **Track.** A SQLite tracker records every application and which resume version was
   sent, and blocks duplicate applications to the same job.

## Design choices

- **Truthful by construction.** The tailoring step can't add skills, numbers, or
  titles. Anything it tries to invent is caught by code and shown on the review page.
- **A human in the loop.** Nothing is sent without my approval, and I submit every
  application.
- **Reputable sources only.** Public, read-only job feeds from the hiring systems
  themselves. No scraping of LinkedIn or Indeed, and it backs off when a site asks it
  to slow down.
- **Cheap to run.** Finding is free. Scoring and tailoring cost about $1–2 a day in API
  credits, and every run prints its cost.

## Tech

Python 3.12 · Anthropic API · Flask · SQLite · Playwright (PDF rendering) ·
python-docx · pytest · macOS launchd (weekday schedule)

## Project layout

| Path | Purpose |
|---|---|
| `agent/sources/` | SimplifyJobs, Greenhouse, Lever, and Workday feeds |
| `agent/filters.py`, `agent/finder.py` | Keyword filters and the find step |
| `agent/scorer.py` | Fit scoring |
| `agent/tailor.py` | Tailoring and the truthfulness checks |
| `agent/render.py` | Resume → PDF and Word |
| `agent/review.py`, `agent/home.py` | The local review and apply page |
| `agent/tracker.py` | SQLite tracker and duplicate detection |
| `agent/schedule.py` | Weekday schedule |
| `tests/` | 70 tests (no network or API calls) |

## Running it

```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env          # add an Anthropic API key
# put your resume in data/resume.md (see config.yaml for search settings)

python main.py go             # get today's jobs ready and open the review page
python main.py --help         # every command
```

Personal data (resume, tracker, generated resumes, API key) stays on the local machine
and is excluded from git.
