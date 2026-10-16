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
            "url": f"https://www.arbeitnow.com/jobs/{j.get('slug', '')}",
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
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
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
    except Exception as e:
        print(f"[telegram] failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------- main
def main() -> None:
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

    no_interview = sorted([j for j in matches if j["ni_score"] > 0],
                          key=lambda j: -j["ni_score"])
    others = [j for j in matches if j["ni_score"] == 0]

    now = datetime.now(timezone.utc).astimezone().strftime("%d %b %Y, %I:%M %p %Z")
    lines = [f"# Job digest — {now}", "",
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
            lines.append(f"### {j['title']}{co}")
            lines.append(f"- **Source:** {j['source']} · **Pay:** {pay}")
            lines.append(f"- **Matched:** {', '.join(j['hits'])}")
            if j["ni_hits"]:
                lines.append(f"- **No-interview signals:** {', '.join(j['ni_hits'])}")
            lines.append(f"- [Apply / details]({j['url']})")
            lines.append("")

    render(no_interview, "🎯 Likely test/resume-based selection (no-interview signals)")
    render(others, "📌 Other matching roles (check selection process yourself)")

    lines += ["---",
              "_No-interview flags are keyword heuristics — always verify the actual "
              "hiring process in the posting before applying._"]
    DIGEST_FILE.write_text("\n".join(lines))

    # CSV export — opens directly in Google Sheets / Excel
    csv_path = BASE / "jobs.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Title", "Company", "Source", "Pay",
                    "Matched keywords", "No-interview signals", "URL"])
        for j in no_interview + others:
            w.writerow([j["title"], j["company"], j["source"], j["pay"],
                        "; ".join(j["hits"]), "; ".join(j["ni_hits"]),
                        j["url"]])
    print(f"csv -> {csv_path} ({len(matches)} rows)")
    print(f"done: {len(matches)} matches ({len(no_interview)} no-interview signals). "
          f"digest -> {DIGEST_FILE}")

    # Telegram summary (chunk-safe: one short message + the digest as a file)
    summary_lines = [
        f"💼 *Job digest — {len(matches)} new matches*",
        "",
    ]
    if no_interview:
        summary_lines.append("🎯 *Likely no-interview picks:*")
        for j in no_interview[:10]:
            co = f" @ {j['company']}" if j["company"] else ""
            summary_lines.append(f"• [{j['title']}{co}]({j['url']})")
        summary_lines.append("")
    summary_lines.append(
        f"_{len(others)} more matches in the attached file. "
        "Verify hiring process before applying._"
    )
    notify_telegram("\n".join(summary_lines)[:3500],
                    no_interview, len(others), DIGEST_FILE)


if __name__ == "__main__":
    main()
