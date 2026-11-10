# internship-agent

An AI-powered tool that finds internships that fit your resume, tailors your
resume to each one, and fills in the applications, while **you stay in
control**. It never invents experience and never clicks Submit for you.

## How it works

```
 find ──► score ──► tailor ──► review ──► apply ──► tracker
 (free)   (Claude)  (Claude)   (you)      (you click Submit)
```

1. **Find**: pulls Summer 2027 listings from the SimplifyJobs GitHub list and
   public Greenhouse/Lever boards, filters them by keyword, role, term,
   location, and posting age (30 days by default), and fetches full
   descriptions (Workday, Oracle, Greenhouse, Lever, Ashby, SmartRecruiters).
   Jobs that close are detected and skipped. Every job is labeled by source
   (official hiring system, company site, or ⚠ unverified).
2. **Score**: Claude rates each job's fit with your resume (0–100) and explains
   why. Richmond/DC-area jobs get a bonus and are scored first.
3. **Tailor**: Claude reorders and rewords your resume for the job, using only
   what's already in it. Two truthfulness checks (AI and code) flag anything
   that can't be traced back to your original resume.
4. **Review**: a page in your browser shows each job, its fit, and the tailored
   resume with every change marked. You approve, edit, or skip.
5. **Apply**: a browser opens and fills in the form (Greenhouse and Lever
   automatically, Workday page by page with you). You check it and click Submit.
6. **Tracker**: every job is recorded, so you never apply to the same one twice.

## Daily workflow

```bash
source venv/bin/activate        # once per terminal window

python main.py prepare          # find, score, and tailor your top 5 (~$0.80)
python main.py review           # approve / edit / skip in your browser; Ctrl+C when done
python main.py apply            # fill in each approved application; you click Submit
```

When `apply` finishes a job it asks **Did you submit it?** Answer `y` (submitted),
`n` (keep for later), `s` (skip), or `v` (view the resume again).

**Automatic daily prep (optional):** `python main.py schedule --time 7:00` makes
your Mac run `prepare` every day at 7:00 (or when it next wakes up) and show a
notification when your jobs are ready. `python main.py schedule` shows its status
and last log; `python main.py schedule --off` turns it off. It never applies to
anything by itself.

For **Workday** jobs: click *Apply* → *Autofill with Resume* and sign in yourself,
then press **Enter** in the terminal on each page to fill it, and click *Next*
yourself. Type `d` when you're done with the job.

## Commands

### Daily
| Command | What it does |
|---|---|
| `python main.py prepare` | The daily routine: finds new jobs, scores until it has enough good matches, and tailors resumes for the best ones. Options: `--count 3` (how many), `--no-find` (skip downloading). |
| `python main.py review` | Opens the review page in your browser (only on your computer). Approve, edit, or skip each tailored job. Option: `--port 5050`. |
| `python main.py apply` | Fills in every approved application. `python main.py apply 97` does only job #97. Never clicks Submit. |
| `python main.py queue` | Lists tailored jobs waiting for your review, with ✓/⚠ for the truthfulness checks. |
| `python main.py schedule --time 7:00` | Runs `prepare` automatically every day and notifies you. `--off` turns it off; no options shows status and the last log. |

### Finding and scoring (one step at a time)
| Command | What it does |
|---|---|
| `python main.py find` | Downloads new listings, filters them, and gets their descriptions. Free. |
| `python main.py score` | Scores waiting jobs with Claude. Option: `--limit 25`. Prints what the run cost. |
| `python main.py jobs` | Shows scored matches, best first. ★ = Richmond/DC area. ⚠ = you've applied at that company before. |
| `python main.py show 42` | Everything about job #42: fit score, strengths, gaps, and its tailored resume report. |
| `python main.py tailor 42` | Tailors your resume for job #42 on its own (~$0.08). |

### Your application tracker
| Command | What it does |
|---|---|
| `python main.py list` | Your applications. `--all` also shows jobs the agent found or skipped; `--status applied` filters. |
| `python main.py add` | Adds an application you made yourself (asks you questions, or use `--company`, `--role`, `--link`, `--status`, `--date`). |
| `python main.py import file.csv` | Adds past applications from a CSV with columns `company, role, link, date, status, notes`. |
| `python main.py status 42 interview` | Changes job #42's status. |
| `python main.py resume` | Checks that your resume file loads. |

**Statuses:** `found` → `queued` (tailored) → `approved` → `applied` → `assessment` / `interview` / `offer` / `rejected` / `closed`, or `skipped`.

## Setup

1. Python 3.12 virtual environment:
   ```bash
   python3.12 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
2. **API key:** copy `.env.example` to `.env` and paste your Anthropic API key.
3. **Resume:** put your resume in `data/resume.md` (Markdown: `# Name`, `## Section`,
   `### Title — Org | Dates`, `- bullets`). Check it with `python main.py resume`.
4. **Profile:** run `python main.py apply` once to create `data/profile.yaml`,
   then fill in your standard form answers. Blank answers are left for you on
   each form.
5. **Past applications:** `python main.py import your_file.csv` so the agent skips them.

## Settings (`config.yaml`)

- **search**: keywords to include/exclude, preferred locations and their bonus.
  - `max_posting_age_days` (default 30): skip postings older than this.
  - `only_verified_sites` (default false): `true` drops jobs that aren't on an
    official hiring system or the company's own site; `false` keeps them but
    flags them with ⚠.
- **greenhouse_boards / lever_boards**: extra companies to check directly.
- **scoring**: model, minimum fit score (default 65).
- **tailoring**: model and effort.
- **daily**: how many jobs `prepare` gets ready (default 5) and the most it will score per run.
- **apply**: model for form answers; whether to open the resume in Preview automatically.

## Privacy and safety

- `data/` (resume, profile, tracker, browser logins), `output/` (tailored resumes),
  and `.env` (API key) are in `.gitignore` and never committed.
- Voluntary self-identification answers (race, gender, veteran, disability) are
  matched to forms by code on your computer and are **never sent to Claude**.
- Form answers come only from your profile and resume. Code rejects invented
  text and non-option choices, and always leaves essays, consents, and pay
  questions for you.
- The agent never clicks Submit or Next, and never stores passwords. Sign in
  yourself; the agent's browser remembers you.

## Cost

Each command prints what it cost. Roughly, with Opus: scoring ~$0.025/job,
tailoring ~$0.08/resume, form answers ~$0.02/form, so **~$0.80–0.90/day for 5
applications**. Switching scoring to `claude-haiku-5-5` in `config.yaml` makes
scoring ~50× cheaper.

## Tests

```bash
pytest
```
Form-filling tests run on fake local copies of Greenhouse, Lever, and Workday
forms. They never touch a real employer's site.
