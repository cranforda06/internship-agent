# internship-agent

Finds internships that fit your resume and tailors your resume to each one.
**You fill in and submit every application yourself.** It never makes up experience.

## Every day

```bash
source venv/bin/activate
python main.py go
```

`python main.py go` gets today's jobs ready (skipped if the schedule already did it),
then opens the **home page** in your browser:

1. **Waiting for your review:** click *Open* on a job, then *Approve* or *Skip* it.
2. **Ready to apply:** click *Apply*. The application opens in a new tab and your
   tailored resume pops up in Finder. Drag it into the upload box, fill out the
   application, and click Submit yourself.
3. Back on the home page, click *I submitted it*, *Not yet*, or *Skip*.
4. Click **Finish for today** when you're done.

`python main.py home` opens the home page without getting new jobs first.
Keep the terminal open while you work.

**Schedule:** `python main.py schedule --time 10:00` gets jobs ready every weekday
and sends a notification. It never applies. `--off` turns it off.

## Good to know

- Only postings from the last 14 days, newest first, Richmond and DC first.
- It keeps up to 25 jobs ready for you, at about $1–2 a day in API credits. Applying is free.
- Every tailored resume is saved in `output/resumes/`. `python main.py list` shows which
  one you sent to each job.

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
python -m playwright install chromium   # used to make the resume PDFs
```

1. Copy `.env.example` to `.env` and add your Anthropic API key.
2. Put your resume in `data/resume.md`.

Other settings are in `config.yaml`.

## Privacy

- Your resume, tracker, and API key stay on your computer.
- The agent never touches your applications: you fill in and submit each one.
