# internship-agent

Finds internships that fit your resume, tailors your resume to each one, and
fills in the applications. **You check every application and click Submit yourself.**
It never makes up experience.

## Every day

```bash
source venv/bin/activate
python main.py go
```

`go` does the whole day in order:
1. Finds jobs and tailors your resume for the top 15 (skipped if the schedule already did it today).
2. Approves fit 75+ matches automatically, then opens the review page for the rest.
   Approve or skip each, then click **Done reviewing**.
3. Fills in each approved application. You check it and click Submit, then answer
   in the terminal: `y` submitted, `n` later, `s` skip, `v` view resume.

The steps also work on their own: `prepare`, `review`, `apply`.

**Workday jobs:** click *Apply* → *Autofill with Resume* and sign in. Then press
Enter in the terminal on each page to fill it, click *Next* yourself, and type
`d` when done.

**Run it automatically:** `python main.py schedule --time 7:00` runs `prepare`
every weekday and sends a notification when jobs are ready (even if your Mac was
asleep or off). `--off` turns it off.

## Other commands

| Command | What it does |
|---|---|
| `python main.py today` | What the agent found, scored, and tailored today |
| `python main.py queue` | Jobs waiting for your review |
| `python main.py jobs` | Best matches (★ Richmond/DC, ⚠ applied there before) |
| `python main.py show 42` | Everything about job #42 |
| `python main.py apply 42` | Apply to just job #42 |
| `python main.py list` | Your applications |
| `python main.py add` | Add an application you made yourself |
| `python main.py status 42 interview` | Update a job's status |
| `python main.py schedule` | Check the daily schedule |

Run `python main.py --help` to see every command.

## Setup

```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

1. Copy `.env.example` to `.env` and add your Anthropic API key.
2. Put your resume in `data/resume.md`.
3. Fill in your standard answers in `data/profile.yaml` (created the first time you run `apply`).

Settings like how many jobs per day, preferred locations, and keywords are in `config.yaml`.

## Privacy

- Your resume, profile, tracker, and API key stay on your computer and are never committed to git.
- Demographic answers (race, gender, veteran, disability) are never sent to Claude.
- The agent never clicks Submit, never stores passwords, and leaves essays and consent boxes for you.
