#!/usr/bin/env python3
"""
Remote AI/ML/Automation internship & job finder — v2.

Pulls fresh listings from free sources, filters by role keywords,
flags postings that look like test/resume/project-based selection
(no-interview signals), skips jobs already in your application tracker,
and writes a daily digest.

Sources: RemoteOK API, Arbeitnow API, Remotive API, We Work Remotely RSS,
Hacker News "Who is hiring" threads. All free, no API keys needed.

Usage:
    python3 fetch_jobs.py            # fetch + filter + write digest.md
    python3 fetch_jobs.py --reset     # forget seen jobs (full re-scan)
"""
from __future__ import annotations

import html
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE_FILE = BASE / "seen.json"
DIGEST_FILE = BASE / "digest.md"

UA = {"User-Agent": "Mozilla/5.0 (job-finder; personal use; contact via user)"}
TIMEOUT = 25

# ---------------------------------------------------------------- roles
ROLE_KEYWORDS = [
    # AI / ML
    "ai engineer", "ml engineer", "machine learning", "deep learning",
    "artificial intelligence", "llm", "large language model", "nlp",
    "natural language processing", "generative ai", "genai",
    "computer vision", "data scientist", "mlops", "prompt engineer",
    "ai/ml", "ml/ai",
    # automation
    "automation engineer", "test automation", "qa automation",
    "rpa", "robotic process automation", "sdet",
]

# Signals that selection may be test/resume/project-based, not interviews.
NO_INTERVIEW_SIGNALS = [
    "no interview", "without interview", "no interviews", "skip the interview",
    "no calls", "no phone calls", "async hiring", "asynchronous hiring",
    "take-home", "take home", "home assignment", "paid trial", "trial task",
    "trial project", "test task", "test project", "coding challenge",
    "portfolio review", "based on your portfolio", "based on portfolio",
    "resume screening", "no rounds", "single round", "one round only",
    "text-based", "written assessment",
]
# Signals of classic multi-round interview loops (downrank).
INTERVIEW_HEAVY_SIGNALS = [
    "multiple rounds", "several rounds", "rounds of interviews",
    "panel interview", "onsite interview", "on-site interview",
    "culture fit interview", "behavioral interview",
]

# Titles that are clearly not engineering/automation work. They stay in the
# digest (the keyword may still match), but they never headline the
# no-interview section — that slot is for roles he'd actually take.
NON_ENGINEERING_TITLES = [
    "sales", "account executive", "account manager", "business development",
    "partnership", "growth manager", "growth marketing", "marketing",
    "customer success", "customer enablement", "product designer",
    "graphic designer", "visual designer", "accounting", "accountant",
    "recruiter", "talent acquisition",
]

def looks_engineering(title: str) -> bool:
    t = (title or "").lower()
    return not any(
        re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", t)
        for k in NON_ENGINEERING_TITLES
    )

# Internship markers, matched on the TITLE only, with letter boundaries so
# "internal" and "international" never count as "intern". Deliberately
# conservative: a missed internship costs less than a mislabelled senior role.
INTERN_TITLE_RE = re.compile(
    r"(?<![a-z])intern(s|ship|ships)?(?![a-z])"
    r"|(?<![a-z])co-?op(?![a-z])"
    r"|(?<![a-z])trainee(?![a-z])"
    r"|(?<![a-z])apprentice(ship)?(?![a-z])"
    r"|working student|werkstudent|praktikum"
    r"|graduate (trainee|program|programme)"
    r"|summer intern",
    re.IGNORECASE,
)

def is_internship(job: dict) -> bool:
    return bool(INTERN_TITLE_RE.search(job.get("title") or ""))

UNPAID_SIGNALS = ["unpaid", "volunteer", "no stipend", "without pay", "not paid"]
PAID_SIGNALS = ["paid", "stipend", "salary", "compensation", "$", "€", "₹", "usd", "/hr",
                "/hour", "per hour", "/month", "per month", "/year", "equity"]


# ---------------------------------------------------------------- helpers
def get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def load_seen() -> set:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except Exception:
            return set()
    return set()


def save_seen(seen: set) -> None:
    STATE_FILE.write_text(json.dumps(sorted(seen), indent=1))


def role_hits(text: str) -> list[str]:
    t = text.lower()
    hits = []
    for kw in ROLE_KEYWORDS:
        # word boundaries stop "rpa" matching "representative"
        # and "llm" matching "will manage"
        if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", t):
            hits.append(kw)
    return hits


def no_interview_score(text: str) -> tuple[int, list[str]]:
    t = text.lower()
    hits = [s for s in NO_INTERVIEW_SIGNALS if s in t]
    penalty = sum(1 for s in INTERVIEW_HEAVY_SIGNALS if s in t)
    return max(0, len(hits) - penalty), hits


def pay_status(text: str) -> str:
    t = text.lower()
    if any(s in t for s in UNPAID_SIGNALS):
        return "unpaid"
    if any(s in t for s in PAID_SIGNALS):
        return "paid"
    return "unknown"


def is_remote_ok(text: str) -> bool:
    """Keep remote-friendly or location-agnostic postings; drop explicit on-site."""
    t = text.lower()
    # "work from home 2 days per week" is hybrid, not remote — but it
    # contains the "work from home" signal below, so catch it first.
    # (Fiducial, Nov 7 digest: this exact phrasing slipped the filter.)
    if "fully remote" not in t:
        if re.search(r"work from home (up to )?\d+ days?", t):
            return False
        # Nov 11: same capped-remote / mostly-onsite signals as the
        # eligibility check — "1–2 remote days a week", "80–100% on-site".
        if re.search(r"\b\d+\s*[-–]\s*\d+\s+remote days?", t):
            return False
        if re.search(r"remote (up to )?\d+ days? (a|per) week", t):
            return False
        if re.search(r"\b([5-9]\d|100)\s?% on-?site\b", t):
            return False
        if "commute" in t:
            return False
    if any(s in t for s in ["remote", "work from home", "wfh", "distributed",
                            "anywhere", "worldwide", "async"]):
        return True
    # drop obvious on-site-only postings
    if re.search(r"\b(on-?site|in-?office|hybrid)\b", t) and "remote" not in t:
        return False
    return True  # no location info -> keep, let the user judge


# ---------------------------------------------------------------- sources
def fetch_remoteok() -> list[dict]:
    jobs = []
    try:
        data = get_json("https://remoteok.com/api")
    except Exception as e:
        print(f"[remoteok] fetch failed: {e}", file=sys.stderr)
        return jobs
    for j in data:
        if not isinstance(j, dict) or "id" not in j:
            continue  # first item is a legal notice, not a job
        text = " ".join([j.get("position", ""), j.get("description", ""),
                         " ".join(j.get("tags", []))])
        text = strip_html(text)
        hits = role_hits(text)
        if not hits:
            continue
        jobs.append({
            "id": f"rok-{j['id']}",
            "title": j.get("position", "Untitled"),
            "company": j.get("company", ""),
            "url": j.get("url", ""),
            "text": text,
            "hits": hits,
            "source": "RemoteOK",
        })
    return jobs


def fetch_arbeitnow() -> list[dict]:
    jobs = []
    try:
        data = get_json("https://www.arbeitnow.com/api/job-board-api")
    except Exception as e:
        print(f"[arbeitnow] fetch failed: {e}", file=sys.stderr)
        return jobs
    for j in data.get("data", []):
        text = " ".join([j.get("title", ""), j.get("description", "")])
        text = strip_html(text)
        hits = role_hits(text)
        if not hits:
            continue
        jobs.append({
            "id": f"an-{j.get('slug', '')}",
            "title": j.get("title", "Untitled"),
            "company": j.get("company_name", ""),
            "url": j.get("url") or f"https://www.arbeitnow.com/jobs/{j.get('slug', '')}",
            "text": text,
            "hits": hits,
            "source": "Arbeitnow",
        })
    return jobs


def fetch_remotive() -> list[dict]:
    """Remotive public API — remote jobs, no key needed."""
    jobs = []
    try:
        data = get_json("https://remotive.com/api/remote-jobs?limit=200")
    except Exception as e:
        print(f"[remotive] fetch failed: {e}", file=sys.stderr)
        return jobs
    for j in data.get("jobs", []):
        text = " ".join([j.get("title", ""),
                         strip_html(j.get("description", "")),
                         " ".join(j.get("tags", []))])
        hits = role_hits(text)
        if not hits:
            continue
        salary = (j.get("salary") or "").strip()
        if salary and "salary" not in text.lower():
            text += " " + salary  # help the pay detector
        jobs.append({
            "id": f"rem-{j.get('id')}",
            "title": j.get("title", "Untitled"),
            "company": j.get("company_name", ""),
            "url": j.get("url", ""),
            "text": text,
            "hits": hits,
            "source": "Remotive",
        })
    return jobs


def fetch_wwr() -> list[dict]:
    """We Work Remotely public RSS feeds — no key needed."""
    jobs = []
    feeds = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    ]
    for feed_url in feeds:
        try:
            req = urllib.request.Request(feed_url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                root = ET.parse(resp).getroot()
        except Exception as e:
            print(f"[wwr] fetch failed ({feed_url}): {e}", file=sys.stderr)
            continue
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = strip_html(item.findtext("description") or "")
            text = f"{title} {desc}"
            hits = role_hits(text)
            if not hits:
                continue
            guid = (item.findtext("guid") or link).strip()
            gid = hashlib.md5(guid.encode()).hexdigest()[:12]
            company = title.split(":")[0].strip() if ":" in title else ""
            jobs.append({
                "id": f"wwr-{gid}",
                "title": title,
                "company": company,
                "url": link,
                "text": text,
                "hits": hits,
                "source": "WeWorkRemotely",
            })
    return jobs


def load_applied_urls() -> set:
    """URLs already in the application tracker — skip them in the digest."""
    p = BASE / "applications.json"
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text())
        return {a.get("url", "") for a in data.get("apps", []) if a.get("url")}
    except Exception:
        return set()


def fetch_hn() -> list[dict]:
    """Latest 'Ask HN: Who is hiring?' thread -> scan comments for matching posts."""
    jobs = []
    cutoff = int(datetime.now(timezone.utc).timestamp()) - 90 * 86400
    search = None
    for attempt in range(3):
        try:
            search = get_json(
                "https://hn.algolia.com/api/v1/search?"
                "query=Ask%20HN%3A%20Who%20is%20hiring%3F&tags=story&hitsPerPage=20"
                f"&numericFilters=created_at_i%3E{cutoff}"
            )
            break
        except Exception as e:
            if attempt == 2:
                print(f"[hn] fetch failed: {e}", file=sys.stderr)
                return jobs
            time.sleep(2)
    try:
        hits = [h for h in search.get("hits", [])
                if "who is hiring" in (h.get("title") or "").lower()]
        if not hits:
            return jobs
        thread = max(hits, key=lambda h: h.get("created_at_i", 0))
        thread_id = thread["objectID"]
        comments = get_json(
            f"https://hn.algolia.com/api/v1/search?"
            f"tags=comment,story_{thread_id}&hitsPerPage=1000"
        )
    except Exception as e:
        print(f"[hn] fetch failed: {e}", file=sys.stderr)
        return jobs
    for c in comments.get("hits", []):
        text = strip_html(c.get("comment_text") or "")
        if len(text) < 120:  # skip one-liners / replies
            continue
        hits = role_hits(text)
        if not hits:
            continue
        jobs.append({
            "id": f"hn-{c.get('objectID')}",
            "title": text[:90].split("|")[0].strip(),
            "company": "",
            "url": f"https://news.ycombinator.com/item?id={c.get('objectID')}",
            "text": text,
            "hits": hits,
            "source": "HN Who's Hiring",
        })
    return jobs


# ---------------------------------------------------------------- verification
# Headline picks (the 🎓 internships + 🎯 no-interview sections) get one live
# fetch each before the digest goes out: dead postings are demoted out of the
# headline sections and pay labels are re-checked against the full posting
# text instead of the short search snippet that produced them.
VERIFY_CAP = 12  # max page fetches per run — bounds the added runtime

# Phrases boards show when a posting is gone. Deliberately narrow: a false
# "dead" verdict demotes a real job, which is worse than a missed demotion.
EXPIRED_MARKERS = [
    "job no longer available",
    "no longer available",
    "no longer accepting applications",
    "this job has expired",
    "job has expired",
    "posting has expired",
    "position has been filled",
    "position is no longer available",
    "this listing is no longer active",
    "applications are now closed",
    "job not found",
]

# Eligibility blockers for Atharva's rules: remote-only, India-based,
# 3rd-year B.E., internship target ~March 2027. Each pattern must name a
# concrete blocker, not a vibe — a false fail demotes a real job, so
# anything ambiguous is a warning (below), never a fail. Grounded in the
# three Nov 7 headline picks that all failed after the digest shipped:
# Fiducial (no visa sponsorship + 2 WFH days/week), Distalmotion
# (Master's / final-year Bachelor's enrolment), Tomtom (Dutch university
# enrolment + commute to the Amsterdam office twice a week).
# Nov 11 picks that slipped the Nov 7 check (greenteg AG, Sonio x2):
# a Swiss work-permit / EU-EFTA citizenship requirement, an on-site
# percentage ("80–100% on-site"), a capped remote allowance ("1–2
# remote days a week"), and the French "Master 2 / Bac+5" enrolment
# gate. The title-city signal from the Nov 11 note is deliberately NOT
# a pattern here: legit remote postings carry a city in the title too,
# and greenteg's body already states the on-site % that demotes it.
ELIGIBILITY_FAILS = [
    (re.compile(r"cannot provide visa sponsorship", re.I),
     "no visa sponsorship"),
    (re.compile(r"no visa sponsorship", re.I), "no visa sponsorship"),
    (re.compile(r"do not (provide|offer|sponsor)[^.]{0,40}visa", re.I),
     "no visa sponsorship"),
    (re.compile(r"visa sponsorship (is )?not (available|provided|offered)",
                re.I), "no visa sponsorship"),
    (re.compile(r"dutch university", re.I),
     "requires enrolment in a Dutch university"),
    (re.compile(r"university in the netherlands", re.I),
     "requires enrolment in a Dutch university"),
    (re.compile(r"enrolled in a master'?s (degree|program)", re.I),
     "requires Master's enrolment"),
    (re.compile(r"final year of a bachelor", re.I),
     "requires final-year Bachelor's enrolment"),
    (re.compile(r"commute to the office", re.I),
     "requires commuting to the office"),
    (re.compile(r"work from home (up to )?\d+ days? per week", re.I),
     "only some days work-from-home (onsite the rest of the week)"),
    (re.compile(r"\d+ days? (a|per) week in (the )?office", re.I),
     "requires office days each week"),
    # --- Nov 11 extension (greenteg AG, Sonio x2) ---
    # Work-permit / authorisation requirement. "We sponsor work
    # authorization" must NOT match: only requires/must-hold/need
    # wording demotes. Residual risk: "authorisation in the country
    # where you are based" would also match — rare in headline picks.
    (re.compile(r"(requires?|must hold|must have|need)[^.]{0,60}"
                r"work (permit|authori[sz]ation)", re.I),
     "requires a work permit / authorisation"),
    (re.compile(r"eu/efta citizenship", re.I),
     "requires EU/EFTA citizenship"),
    # Stated on-site share of 50% or more ("80–100% on-site"). The
    # "100%" arm also catches "80–100%" (en dash), where "80" alone
    # is not followed by "%".
    (re.compile(r"\b([5-9]\d|100)\s?% on-?site\b", re.I),
     "mostly on-site (50%+ on-site stated)"),
    # Capped remote allowance ("1–2 remote days a week", "remote
    # 2 days a week"). "Fully remote" postings never state a cap.
    (re.compile(r"\b\d+\s*[-–]\s*\d+\s+remote days?\b", re.I),
     "only a few remote days a week (onsite the rest)"),
    (re.compile(r"remote (up to )?\d+ days? (a|per) week", re.I),
     "only a few remote days a week (onsite the rest)"),
    (re.compile(r"\bonly \d+ remote days?\b", re.I),
     "only a few remote days a week (onsite the rest)"),
    # French enrolment gate: "in Master 2 / Bac+5" (Sonio). A bare
    # "Master's degree is a plus" does not match either pattern.
    (re.compile(r"\bmaster 2\b", re.I),
     "requires Master 2 enrolment (French Bac+5)"),
    (re.compile(r"\bbac\s*\+\s*5\b", re.I),
     "requires Master 2 enrolment (French Bac+5)"),
    # --- Nov 12 extension (Axle Careers, withdrawn same morning) ---
    # Candidate-directed base requirement: "You'll be based in France"
    # (Axle). Deliberately NOT a bare "based in <place>": legit remote
    # postings say "we're based in Berlin, fully remote worldwide".
    (re.compile(r"\b(you'll be|you will be|must be) based in\b", re.I),
     "requires being based in the stated country"),
    # Recurring office stint: "spend ~1 week per month working from
    # our London office" (Axle). A one-off visit / retreat does not
    # match: it needs the per-month cadence plus "office".
    (re.compile(r"\b\d+\s+weeks? per month[^.]{0,40}office\b", re.I),
     "requires regular time in the office each month"),
]

# Ambiguous signals: worth flagging on the pick, never enough to demote.
# "onsite interview" is a hiring step, not a workplace — excluded.
ELIGIBILITY_WARNINGS = [
    (re.compile(r"preferred starting date:\s*asap", re.I),
     "ASAP start (your target is ~March 2027)"),
    (re.compile(r"\bhybrid\b", re.I), "mentions hybrid working"),
    (re.compile(r"\bon-?site\b(?!\s+interview)", re.I),
     "mentions on-site working"),
]


def check_eligibility(text: str) -> tuple[str | None, list[str]]:
    """Check full posting text against Atharva's eligibility rules.

    Returns (fail_reason or None, [warning, ...]). Curly apostrophes
    (Master’s) are normalised so the degree patterns still match.
    """
    low = (text or "").lower().replace("’", "'").replace("‘", "'")
    for pattern, reason in ELIGIBILITY_FAILS:
        if pattern.search(low):
            return reason, []
    warnings = [reason for pattern, reason in ELIGIBILITY_WARNINGS
                if pattern.search(low)]
    return None, warnings


def fetch_page_text(url: str) -> str:
    """Fetch a posting page (redirects followed) and return its visible text.
    Raises on HTTP/network errors — the caller decides what they mean."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read(2_000_000).decode("utf-8", "replace")
    return strip_html(raw)


def verify_headlines(jobs: list[dict]) -> None:
    """Verify up to VERIFY_CAP headline picks in place.

    Sets j["verified"]: True = page fetched, still looks open, and no
    eligibility blocker found in the full text,
    False = page gone / posting looks expired / hard eligibility blocker,
    None = could not check (network error, bot wall, no URL, or beyond
    the cap).
    Sets j["verify_note"] explaining dead verdicts, eligibility blocks,
    warnings and pay corrections.
    May also correct j["pay"] from the full posting text.
    Never raises — a failed check leaves the pick exactly where it was.
    """
    for j in jobs:
        j.setdefault("verified", None)
        j.setdefault("verify_note", "")
    for j in jobs[:VERIFY_CAP]:
        _verify_one(j)


def _verify_one(j: dict) -> None:
    url = j.get("url") or ""
    if not url.startswith("http"):
        return  # nothing fetchable — leave unchecked
    try:
        text = fetch_page_text(url)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            j["verified"] = False
            j["verify_note"] = f"posting page returned HTTP {e.code}"
        # other HTTP errors (403 bot walls, 500s) prove nothing — unchecked
        return
    except Exception:
        return  # timeout / DNS / TLS — unchecked, never crash the digest
    low = text.lower()
    marker = next((m for m in EXPIRED_MARKERS if m in low), None)
    if marker:
        j["verified"] = False
        j["verify_note"] = f"posting looks closed (“{marker}” on the page)"
        return
    j["verified"] = True
    notes: list[str] = []
    # Eligibility check against the full text: location, visa, enrolment
    # country/level and start date are what the Nov 7 digest missed.
    # A hard blocker demotes the pick exactly like a closed posting;
    # warnings stay on the pick as a flag for Atharva to judge.
    fail, warnings = check_eligibility(text)
    if fail:
        j["verified"] = False
        j["verify_note"] = (f"doesn't fit your rules: {fail} "
                            f"(full posting text)")
        return
    if warnings:
        notes.append("check before applying: " + "; ".join(warnings))
    # Pay re-check against the full text: a snippet can miss the stipend
    # paragraph (or catch an "unpaid" mention that isn't about this role).
    full_pay = pay_status(text)
    if full_pay != "unknown" and full_pay != j.get("pay"):
        notes.append(f"pay corrected from snippet label "
                     f"{j.get('pay')} → {full_pay} (full posting text)")
        j["pay"] = full_pay
    j["verify_note"] = "; ".join(notes)


def partition_verified(jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split a section into (still headline-worthy, verified-dead)."""
    live = [j for j in jobs if j.get("verified") is not False]
    dead = [j for j in jobs if j.get("verified") is False]
    return live, dead


# ---------------------------------------------------------------- telegram
def _tg_post(token: str, method: str, fields: dict) -> None:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data, headers=UA, method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        resp.read()


def _tg_send_document(token: str, chat_id: str, path: Path, caption: str) -> None:
    """Upload a file via sendDocument using a hand-built multipart body (stdlib only)."""
    boundary = "----jobfinder-boundary-7d4a"
    buf = BytesIO()

    def field(name: str, value: str) -> None:
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        buf.write(f"{value}\r\n".encode())

    field("chat_id", chat_id)
    field("caption", caption[:1024])
    buf.write(f"--{boundary}\r\n".encode())
    buf.write(
        f'Content-Disposition: form-data; name="document"; '
        f'filename="{path.name}"\r\n'
        "Content-Type: text/markdown\r\n\r\n".encode()
    )
    buf.write(path.read_bytes())
    buf.write(f"\r\n--{boundary}--\r\n".encode())

    body = buf.getvalue()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data=body,
        headers={**UA,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        resp.read()


def notify_telegram(summary: str, no_interview: list[dict],
                    others_count: int, digest_path: Path) -> None:
    """Send digest to Telegram. Needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars."""
    raw_token = os.environ.get("TELEGRAM_BOT_TOKEN", "") or ""
    raw_chat = os.environ.get("TELEGRAM_CHAT_ID", "") or ""
    # Tokens never legitimately contain whitespace — remove ALL of it
    # (kills normal spaces, non-breaking spaces, zero-width chars, newlines).
    token = re.sub(r"\s+", "", raw_token)
    removed = len(raw_token) - len(token)
    # tolerate pasting "TELEGRAM_BOT_TOKEN=<token>" (e.g. from a .env line)
    token = re.sub(r"(?i)^telegram_bot_token=", "", token)
    chat_id = re.sub(r"\s+", "", raw_chat)
    chat_id = re.sub(r"(?i)^telegram_chat_id=", "", chat_id)
    if removed:
        print(f"[telegram] cleaned {removed} whitespace char(s) from token")
    if not token or not chat_id:
        print("[telegram] skipped — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return
    try:
        _tg_post(token, "sendMessage", {
            "chat_id": chat_id, "text": summary,
            "parse_mode": "Markdown", "disable_web_page_preview": "true",
        })
        _tg_send_document(token, chat_id, digest_path,
                          f"Full list: {len(no_interview)} no-interview picks + "
                          f"{others_count} more matches")
        print("[telegram] digest sent")
    except urllib.error.HTTPError as e:
        # Telegram's error body names the real cause, e.g. "chat not found"
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            detail = ""
        print(f"[telegram] failed: HTTP {e.code} — {detail}", file=sys.stderr)
    except Exception as e:
        print(f"[telegram] failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------- main
def main() -> None:
    print("[finder] build 2026-10-17a")  # version marker — check logs show this
    reset = "--reset" in sys.argv
    seen = set() if reset else load_seen()

    all_jobs: list[dict] = []
    for fetcher in (fetch_remoteok, fetch_arbeitnow, fetch_remotive,
                    fetch_wwr, fetch_hn):
        all_jobs.extend(fetcher())

    fresh = [j for j in all_jobs if j["id"] not in seen]
    for j in fresh:
        seen.add(j["id"])
    save_seen(seen)

    applied_urls = load_applied_urls()
    skipped_applied = sum(1 for j in fresh if j["url"] in applied_urls)
    fresh = [j for j in fresh if j["url"] not in applied_urls]

    matches = [j for j in fresh if is_remote_ok(j["text"])]
    for j in matches:
        j["ni_score"], j["ni_hits"] = no_interview_score(j["text"])
        j["pay"] = pay_status(j["text"])
        j["type"] = "internship" if is_internship(j) else "role"

    # Internships-only mode: --internships flag or INTERNSHIP_MODE=1 in env
    # (set it as a GitHub Actions variable/secret to make the daily digest
    # internship-first for the March application window).
    internships_only = ("--internships" in sys.argv
                        or os.environ.get("INTERNSHIP_MODE") == "1")
    if internships_only:
        matches = [j for j in matches if j["type"] == "internship"]

    internships = sorted(
        [j for j in matches if j["type"] == "internship"],
        key=lambda j: ({"paid": 0, "unknown": 1, "unpaid": 2}[j["pay"]],
                       -j["ni_score"]))

    no_interview = sorted(
        [j for j in matches
         if j["ni_score"] > 0 and looks_engineering(j["title"])],
        key=lambda j: -j["ni_score"])
    others = [j for j in matches
              if j["ni_score"] == 0 or not looks_engineering(j["title"])]
    if not internships_only:
        # Internships get their own section below — don't list them twice.
        no_interview = [j for j in no_interview if j["type"] != "internship"]
        others = [j for j in others if j["type"] != "internship"]

    # ---- headline verification: fetch each headline pick's posting live.
    # Dead postings are demoted to a subsection at the end; pay labels are
    # corrected from the full posting text. Unchecked picks stay in place.
    for j in matches:
        j.setdefault("verified", None)
        j.setdefault("verify_note", "")
    headline, _hids = [], set()
    for j in internships + no_interview:
        if j["id"] not in _hids:
            _hids.add(j["id"])
            headline.append(j)
    verify_headlines(headline)
    internships, _dead_i = partition_verified(internships)
    no_interview, _dead_n = partition_verified(no_interview)
    demoted, _dids = [], set()
    for j in _dead_i + _dead_n:
        if j["id"] not in _dids:
            _dids.add(j["id"])
            demoted.append(j)
    # a corrected pay label can change the paid-first ordering
    internships.sort(key=lambda j: ({"paid": 0, "unknown": 1, "unpaid": 2}[j["pay"]],
                                    -j["ni_score"]))
    n_verified = sum(1 for j in headline if j.get("verified") is True)
    print(f"[verify] {n_verified}/{len(headline)} headline picks verified live"
          + (f", {len(demoted)} demoted (closed or ineligible)" if demoted else ""))

    now = datetime.now(timezone.utc).astimezone().strftime("%d %b %Y, %I:%M %p %Z")
    lines = [f"# Job digest — {now}"
             + (" (internships only)" if internships_only else ""), "",
             f"Scanned {len(all_jobs)} postings across 5 sources, {len(fresh)} new, "
             f"{len(matches)} matched your roles"
             + (f" ({skipped_applied} skipped — already in your tracker)"
                if skipped_applied else "") + ".", ""]

    def render(jobs, heading):
        lines.append(f"## {heading} ({len(jobs)})")
        lines.append("")
        if not jobs:
            lines.append("_None this run._")
            lines.append("")
            return
        for j in jobs:
            pay = {"paid": "💰 paid", "unpaid": "🆓 unpaid",
                   "unknown": "❓ pay unknown"}[j["pay"]]
            co = f" @ {j['company']}" if j["company"] else ""
            tag = " 🎓" if j.get("type") == "internship" else ""
            lines.append(f"### {j['title']}{co}{tag}")
            verify = " · ✔ verified" if j.get("verified") is True else ""
            lines.append(f"- **Source:** {j['source']} · **Pay:** {pay}{verify}")
            lines.append(f"- **Matched:** {', '.join(j['hits'])}")
            if j.get("verify_note"):
                lines.append(f"- **Verify note:** {j['verify_note']}")
            if j["ni_hits"]:
                lines.append(f"- **No-interview signals:** {', '.join(j['ni_hits'])}")
            lines.append(f"- [Apply / details]({j['url']})")
            lines.append("")

    if internships and not internships_only:
        render(internships, "🎓 Internships (paid first)")
    render(no_interview, "🎯 Likely test/resume-based selection (no-interview signals)")
    render(others, "📌 Other matching roles (check selection process yourself)")

    if demoted:
        lines.append(f"## ⚠️ Demoted — closed, or doesn't fit your rules ({len(demoted)})")
        lines.append("")
        for j in demoted:
            co = f" @ {j['company']}" if j["company"] else ""
            tag = " 🎓" if j.get("type") == "internship" else ""
            lines.append(f"### {j['title']}{co}{tag}")
            lines.append(f"- **Source:** {j['source']} · "
                         f"{j.get('verify_note') or 'posting could not be verified'}")
            lines.append(f"- [Apply / details]({j['url']})")
            lines.append("")

    lines += ["---",
              "_✔ verified = the posting page was fetched live during this run and "
              "still looks open and no eligibility blocker was found in the "
              "full text; pay labels may have been corrected from the full text._",
              "_No-interview flags are keyword heuristics — always verify the actual "
              "hiring process in the posting before applying._"]
    DIGEST_FILE.write_text("\n".join(lines))

    # CSV export — opens directly in Google Sheets / Excel
    csv_path = BASE / "jobs.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Title", "Company", "Source", "Type", "Pay", "Verified",
                    "Matched keywords", "No-interview signals", "URL"])
        csv_rows, _cids = [], set()
        for j in internships + no_interview + others + demoted:
            if j["id"] not in _cids:
                _cids.add(j["id"])
                csv_rows.append(j)
        for j in csv_rows:
            verified = {True: "yes", False: "no"}.get(j.get("verified"), "unchecked")
            w.writerow([j["title"], j["company"], j["source"], j["type"], j["pay"],
                        verified,
                        "; ".join(j["hits"]), "; ".join(j["ni_hits"]),
                        j["url"]])
    print(f"csv -> {csv_path} ({len(matches)} rows)")
    print(f"done: {len(matches)} matches ({len(no_interview)} no-interview signals). "
          f"digest -> {DIGEST_FILE}")

    # Telegram summary (chunk-safe: one short message + the digest as a file)
    summary_lines = [
        f"💼 *Job digest — {len(matches)} new matches*"
        + (" (internships only)" if internships_only else ""),
        "",
    ]
    if internships:
        summary_lines.append("🎓 *Internships (paid first):*")
        for j in internships[:8]:
            co = f" @ {j['company']}" if j["company"] else ""
            pay = {"paid": "💰", "unpaid": "🆓 unpaid",
                   "unknown": "❓"}[j["pay"]]
            mark = " ✔" if j.get("verified") is True else ""
            summary_lines.append(f"• [{j['title']}{co}]({j['url']}) {pay}{mark}")
        summary_lines.append("")
    if no_interview:
        summary_lines.append("🎯 *Likely no-interview picks:*")
        for j in no_interview[:10]:
            co = f" @ {j['company']}" if j["company"] else ""
            mark = " ✔" if j.get("verified") is True else ""
            summary_lines.append(f"• [{j['title']}{co}]({j['url']}){mark}")
        summary_lines.append("")
    if headline:
        summary_lines.append(
            f"_✔ {n_verified} of {len(headline)} headline picks verified live"
            + (f"; {len(demoted)} looked closed and were demoted._"
               if demoted else "._"))
        summary_lines.append("")
    summary_lines.append(
        f"_{len(others)} more matches in the attached file. "
        "Verify hiring process before applying._"
    )
    notify_telegram("\n".join(summary_lines)[:3500],
                    no_interview, len(others), DIGEST_FILE)


if __name__ == "__main__":
    main()
