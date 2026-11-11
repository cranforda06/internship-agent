# internship-agent

Finds internships that fit your resume, tailors your resume to each one, and
fills in the applications. **You check every application and click Submit yourself.**
It never makes up experience.

## Every day

```bash
source venv/bin/activate
python main.py go
```

`python main.py go` gets today's jobs ready (skipped if the schedule already did it),
then opens the **home page** in your browser:

- **Waiting for your review:** *Open* a job, then *Approve* or *Skip* it.
- **Ready to apply:** click *Apply*. The form opens in a separate window, filled in.
  Check it, click Submit **yourself**, then click *I submitted it*, *Not yet*, or *Skip*.
- Click **Finish for today** when you're done.

`python main.py home` opens the home page without getting new jobs first.
Keep the terminal open while you work.

**Workday jobs:** click *Apply* → *Autofill with Resume* and sign in. Your resume
uploads itself. Click *Fill this page* on the home page for any questions Workday
didn't fill, then check the page and click *Next* yourself.

**Schedule:** `python main.py schedule --time 10:00` gets jobs ready every weekday
and sends a notification. It never applies. `--off` turns it off.

## Good to know

- Only postings from the last 30 days, newest first, Richmond and DC first.
- It keeps up to 15 jobs ready for you, at about $1–2 a day in API credits.

## Other commands

| Command | What it does |
|---|---|
| `python main.py today` | What was found and tailored today |
| `python main.py jobs` | Best matches |
| `python main.py show 42` | Everything about job #42 |
| `python main.py list` | Your applications |
| `python main.py add` | Add an application you made yourself |
| `python main.py status 42 interview` | Update a job's status |

Run `python main.py --help` to see every command.

## Setup

```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

1. Copy `.env.example` to `.env` and add your Anthropic API key.
2. Put your resume in `data/resume.md`.
3. Fill in your answers in `data/profile.yaml` (created the first time you run `python main.py go`).

Other settings are in `config.yaml`.

## Privacy

- Your resume, profile, tracker, and API key stay on your computer.
- Demographic answers are never sent to Claude.
- The agent never clicks Submit and never stores passwords.
