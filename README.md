# 🤖 JobFinder Bot

**Your personal job-hunting assistant** — scans 5 remote job boards every morning,
finds AI/ML & automation roles that match you, flags the ones with test-based
hiring (no interviews), tracks every application, and drills you for interviews.

100% free. No servers. No API keys for the job sources.

---

## ✨ What it does

| Module | What you get |
|---|---|
| 🔍 **Finder** | Daily digest of remote AI/ML/automation internships & jobs from 5 sources, delivered to Telegram at 9:00 AM IST |
| 🎯 **No-interview radar** | Flags postings that mention take-home assignments, paid trials, or test-based selection — so you can skip the interview grind |
| 💰 **Pay detector** | Labels every posting as paid, unpaid, or unknown |
| 📋 **Tracker** | Application pipeline: saved → applied → test → interview → offer, with follow-up reminders |
| 🎤 **Prep** | Interview question bank + 7-day study plan for AI/ML and automation roles |
| 📊 **CSV export** | Every digest also lands as `jobs.csv` — import straight into Google Sheets |

## 🧠 How it works

```
5 job sources ──► keyword filter ──► no-interview signals ──► Telegram digest
     │                  │                     │
RemoteOK API     AI/ML + automation     take-home, paid trial,
Arbeitnow API    role keywords          "no interview", ...
Remotive API     (word-boundary         ┌── highlighted first
WWR RSS           matched, so "rpa"     │
HN Who's Hiring   ≠ "representative")  ▼
                                   dedup via seen.json
                                   skip already-tracked jobs
```

- **Zero dependencies** — pure Python standard library. No `pip install` needed.
- **Smart dedup** — `seen.json` is committed back after every run, so you only ever see *new* jobs.
- **Tracker-aware** — jobs you've already added to the tracker are excluded from future digests automatically.

## 🚀 Quickstart (15 min, free)

**1. Create a Telegram bot** — message [@BotFather](https://t.me/BotFather), send `/newbot`, copy the token. Then message your new bot once (say `hi`).

**2. Get your chat ID** — open in a browser:
```
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```
Find `"chat":{"id":123456789` — that number is your chat ID.

**3. Push to GitHub** — upload `fetch_jobs.py`, `tracker.py`, `prep.py`,
`requirements.txt` to a repo, and `daily.yml` to `.github/workflows/`.

**4. Add secrets** — repo Settings → Secrets → Actions:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

**5. Test** — Actions tab → *Daily job digest* → *Run workflow*. Check Telegram. 📬

Runs automatically every day at **9:00 AM IST** after that.

## 💻 Usage

```bash
# ── Tracker ──────────────────────────────────────────
python3 tracker.py add --company "Acme" --role "ML Engineer" --url https://...
python3 tracker.py list                        # everything
python3 tracker.py update 3 --status interview --notes "Tue 4pm"
python3 tracker.py due                          # follow-ups due (7+ days silent)
python3 tracker.py stats                        # pipeline overview
# statuses: saved → applied → test → interview → offer / rejected / ghosted

# ── Interview prep ───────────────────────────────────
python3 prep.py                                 # 5 random practice questions
python3 prep.py --role ai_ml --n 10             # 10 AI/ML questions
python3 prep.py --role automation               # automation questions
python3 prep.py plan                            # 7-day study plan

# ── Finder (manual run) ──────────────────────────────
python3 fetch_jobs.py                           # fetch + digest.md + jobs.csv
python3 fetch_jobs.py --reset                   # forget seen jobs, full re-scan
```

## 🛠️ Customize

- **Keywords** — edit `ROLE_KEYWORDS` in `fetch_jobs.py`
- **Schedule** — edit the `cron:` line in `daily.yml` (UTC; IST = UTC+5:30)
- **Internships only** — add `"intern"` / `"internship"` to `ROLE_KEYWORDS`

## 📁 Project structure

```
├── fetch_jobs.py          # the finder — 5 sources, filters, digest, CSV, Telegram
├── tracker.py             # application tracker CLI (applications.json)
├── prep.py                # interview question bank + study plan
├── requirements.txt       # empty — stdlib only
└── .github/workflows/
    └── daily.yml          # 9:00 AM IST schedule + state persistence
```

## ⚠️ Honest notes

- The **no-interview flags are keyword heuristics** — always verify the actual
  hiring process in the posting before applying.
- LinkedIn, Internshala, and Naukri don't offer free APIs — use their email
  alerts as a second layer alongside this bot.
- GitHub Actions schedules can drift a few minutes — "9 AM" means *around* 9 AM.

## 📄 License

MIT — do whatever you want with it. Good luck landing the role. 🚀
