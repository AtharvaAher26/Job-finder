#!/usr/bin/env python3
"""
Application tracker — know exactly where every application stands.

Usage:
    python3 tracker.py add --company "Acme" --role "ML Engineer" --url https://...
    python3 tracker.py list                      # all applications
    python3 tracker.py list --status applied     # filter by status
    python3 tracker.py update 3 --status interview --notes "Tue 4pm"
    python3 tracker.py due                       # follow-ups due (>7 days, no update)
    python3 tracker.py stats                     # pipeline summary

Statuses: saved, applied, test, interview, offer, rejected, ghosted
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

FILE = Path(__file__).resolve().parent / "applications.json"
STATUSES = ["saved", "applied", "test", "interview", "offer", "rejected", "ghosted"]
FOLLOWUP_DAYS = 7


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def load() -> dict:
    if FILE.exists():
        try:
            data = json.loads(FILE.read_text())
            if isinstance(data, dict) and "apps" in data:
                return data
        except Exception:
            pass
    return {"apps": []}


def save(data: dict) -> None:
    FILE.write_text(json.dumps(data, indent=2))


def next_id(apps: list[dict]) -> int:
    return max([a.get("id", 0) for a in apps] + [0]) + 1


def fmt(app: dict) -> str:
    return (f"[{app['id']}] {app['role']} @ {app['company']} — "
            f"{app['status']} (updated {app['updated']})"
            + (f"\n    {app['url']}" if app.get("url") else "")
            + (f"\n    notes: {app['notes']}" if app.get("notes") else ""))


def cmd_add(args: argparse.Namespace) -> None:
    data = load()
    if args.url and any(a.get("url") == args.url for a in data["apps"]):
        print("already tracked (same URL).")
        return
    app = {
        "id": next_id(data["apps"]),
        "company": args.company,
        "role": args.role,
        "url": args.url or "",
        "status": "saved",
        "notes": args.notes or "",
        "added": today(),
        "updated": today(),
    }
    data["apps"].append(app)
    save(data)
    print(f"tracked as #{app['id']}: {app['role']} @ {app['company']}")
    print("when you apply, run: python3 tracker.py update "
          f"{app['id']} --status applied")


def cmd_list(args: argparse.Namespace) -> None:
    apps = load()["apps"]
    if args.status:
        apps = [a for a in apps if a["status"] == args.status]
    if not apps:
        print("nothing tracked yet.")
        return
    for a in sorted(apps, key=lambda x: x["id"]):
        print(fmt(a))


def cmd_update(args: argparse.Namespace) -> None:
    data = load()
    app = next((a for a in data["apps"] if a["id"] == args.id), None)
    if not app:
        print(f"no application #{args.id}")
        sys.exit(1)
    if args.status:
        if args.status not in STATUSES:
            print(f"status must be one of: {', '.join(STATUSES)}")
            sys.exit(1)
        app["status"] = args.status
    if args.notes:
        app["notes"] = (app.get("notes", "") + " | " + args.notes).strip(" |")
    app["updated"] = today()
    save(data)
    print(f"#{app['id']} -> {app['status']}")


def cmd_due(_: argparse.Namespace) -> None:
    apps = load()["apps"]
    due = []
    for a in apps:
        if a["status"] in ("rejected", "offer", "ghosted"):
            continue
        try:
            days = (date.fromisoformat(today())
                    - date.fromisoformat(a["updated"])).days
        except ValueError:
            continue
        if days >= FOLLOWUP_DAYS:
            due.append((days, a))
    if not due:
        print("no follow-ups due. 🎉")
        return
    print(f"{len(due)} follow-up(s) due (no update in {FOLLOWUP_DAYS}+ days):")
    for days, a in sorted(due, reverse=True):
        print(f"  {days}d ago — {fmt(a)}")


def cmd_stats(_: argparse.Namespace) -> None:
    apps = load()["apps"]
    if not apps:
        print("nothing tracked yet.")
        return
    counts: dict[str, int] = {}
    for a in apps:
        counts[a["status"]] = counts.get(a["status"], 0) + 1
    print(f"total: {len(apps)}")
    for s in STATUSES:
        if counts.get(s):
            print(f"  {s:10s} {counts[s]}")
    active = sum(counts.get(s, 0) for s in ("saved", "applied", "test", "interview"))
    print(f"active pipeline: {active}")


def main() -> None:
    p = argparse.ArgumentParser(description="Track your job applications.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="track a new application")
    a.add_argument("--company", required=True)
    a.add_argument("--role", required=True)
    a.add_argument("--url", default="")
    a.add_argument("--notes", default="")
    a.set_defaults(fn=cmd_add)

    l = sub.add_parser("list", help="list tracked applications")
    l.add_argument("--status", choices=STATUSES)
    l.set_defaults(fn=cmd_list)

    u = sub.add_parser("update", help="update status/notes")
    u.add_argument("id", type=int)
    u.add_argument("--status", choices=STATUSES)
    u.add_argument("--notes", default="")
    u.set_defaults(fn=cmd_update)

    d = sub.add_parser("due", help="show follow-ups due")
    d.set_defaults(fn=cmd_due)

    s = sub.add_parser("stats", help="pipeline summary")
    s.set_defaults(fn=cmd_stats)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
