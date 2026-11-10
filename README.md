# internship-agent

Finds internships that fit your resume, tailors your resume to each one, and
fills in the applications. **You review everything and click Submit yourself.**
It never makes up experience.

## Every day

```bash
source venv/bin/activate
python main.py prepare    # find jobs and tailor your resume for the top 15 (~$2)
python main.py review     # approve, edit, or skip each one in your browser (Ctrl+C when done)
python main.py apply      # fills in each approved application; you check it and click Submit
```

After each job, `apply` asks if you submitted it: `y` yes, `n` later, `s` skip, `v` view resume.

**Workday jobs:** click *Apply* → *Autofill with Resume* and sign in. Then press
Enter in the terminal on each page to fill it, click *Next* yourself, and type
`d` when done.

**Run it automatically:** `python main.py schedule --time 7:00` runs `prepare`
every weekday and sends a notification when jobs are ready (even if your Mac was
asleep or off). `--off` turns it off.

## Other commands

| Command | What it does |
|---|---|
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
