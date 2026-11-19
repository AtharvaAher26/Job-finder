# Contributing to Job-finder

Job-finder is a personal job-hunting assistant: it scans remote job boards
every morning, finds AI/ML & automation roles, flags postings with
test-based hiring (no interviews), and delivers a daily digest to Telegram
at 9:00 AM IST. It is 100% free — no servers, no API keys for the job
sources.

## Setup

Requires Python 3.11+. No third-party packages are needed — the script uses
only the Python standard library (`requirements.txt` exists so install
steps don't fail).

```bash
git clone https://github.com/AtharvaAher26/Job-finder.git
cd Job-finder
```

Copy `.env.example` to `.env` and fill in your own Telegram bot token and
chat ID. Never commit a real `.env` or any token.

## Tests

Tests are offline — the network fetcher is monkeypatched with fakes, so no
test touches the internet:

```bash
python -m pytest test_fetch_jobs.py
```

Run the suite before opening a pull request. New behaviour needs a test;
a fix needs a regression test that fails without it.

## Ground rules

- **Never modify the keyword lists.** `ROLE_KEYWORDS`,
  `NO_INTERVIEW_SIGNALS`, and `NON_ENGINEERING_TITLES` in `fetch_jobs.py`
  are the curated filter — changes there silently reclassify every
  posting, so they are off limits.
- **Pull --rebase before pushing.** A GitHub Actions bot commits
  `seen.json` daily; always `git pull --rebase` first so your push
  doesn't clash with it.
- **Keep it offline-testable.** The scanner must stay testable without
  network access; fixture-driven tests are the norm.
- **Dedup is a promise.** `seen.json` is committed back after every run,
  so users only ever see new jobs. Don't weaken the dedup.
- **No auto-submission.** Job-finder finds, tracks, and preps — it never
  applies for a job or completes an interview or test on anyone's behalf.

## Pull requests

- One focused change per PR, with a clear title and a short description of
  what changed and why.
- Don't commit secrets, API keys, or personal data (real tokens, chat IDs,
  or job applications) — fixtures and placeholders only.
