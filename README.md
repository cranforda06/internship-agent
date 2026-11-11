# internship-agent

Finds internships that fit your resume, tailors your resume to each one, and
fills in the applications. **You check every application and click Submit yourself.**
It never makes up experience.

## Every day

```bash
source venv/bin/activate
python main.py go
```

`go` does the whole day:
1. Finds jobs and tailors your resume for the top 15 (skipped if the schedule already did it today).
   Fit 75+ matches are approved automatically.
2. Opens the **home page** in your browser. Everything else is buttons:
   - **Waiting for your review:** *Open* a job, then *Approve* or *Skip* it.
   - **Ready to apply:** click *Apply*. The form opens in a separate browser window, filled in
     as far as the agent can. Check it, click Submit **yourself**, then click
     *I submitted it* (or *Not yet* / *Skip*) on the home page.
   - Click **Finish for today** when you're done.

Keep the terminal open while you work: it shows what the agent is doing.
Already prepared today? `python main.py home` opens just the home page.

**Workday jobs:** in the browser window, click *Apply* → *Autofill with Resume* and sign in.
Each page then fills itself a moment after it loads; check it and click *Next* yourself.
The home page also has *Fill this page again* and *Upload resume again* buttons.

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
| `python main.py home` | Open the home page (review and apply with buttons) |
| `python main.py apply 42` | Apply to just job #42, in the terminal |
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
