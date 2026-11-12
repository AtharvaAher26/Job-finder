# Source registry

Status of every job source the finder uses or has evaluated.
Integrated sources are fetched daily by `fetch_jobs.py`; watchlist sources
are checked manually — each entry says why it is not auto-fetched.

## Integrated (auto-fetched daily)
| Source | How | Since |
|---|---|---|
| RemoteOK | Public API | Oct 2026 |
| Arbeitnow | Public API | Oct 2026 |
| Remotive | Public API | Oct 2026 |
| We Work Remotely | RSS feeds (programming, devops) | Oct 2026 |
| Hacker News "Who's Hiring" | Algolia API on the monthly thread | Oct 2026 |
| **Next Play** (nextplay.so) | JSON-LD index parsed from the main board page (its Applied AI / Remote-first collection pages render client-side with no server data, so they are manual-watchlist) | **Nov 12, 2026** |

## From Atharva's Nov 12, 2026 list — evaluated, watchlist-only
| Site | Verdict |
|---|---|
| YC Job Board (workatastartup.com) | Real board, but bot-walled and login/JS-driven; no stable public feed. Manual watchlist. |
| Lenny's Jobs (lennysjobs.com) | Product/PM-focused board; listings link out to TrueUp company pages, no parseable listing feed. Low fit for AI/ML engineering internships. Manual watchlist. |
| Breakout List (breakoutlist.com) | A directory of breakout *companies*, not a listings feed — job links go to each company's own careers page. Useful for building a target-company list, not for daily fetching. |
| Founders You Should Know (foundersysk.com) | A founder showcase / talent community, not a job board with a listings feed. |
| a16z Build (Substack) | A newsletter, not a board. The actual a16z portfolio job board lives at jobs.a16z.com (third-party platform, no stable public feed) — manual watchlist. |
| Cosign (cosign.co/jobs) | A *single company's* careers page (Greenhouse/Lever). One employer, not a board; add only if that company becomes a named target. |

## Not a job source
| Site | Verdict |
|---|---|
| Ramp Vendor Reports (ramp.com/data) | Vendor-spend benchmark data for finance teams. Not jobs at all — excluded. |

## Rules for adding a source
1. It must expose a stable, key-free feed (API, RSS, or server-rendered
   structured data like JSON-LD). If it needs a login or a headless
   browser to read, it goes to the watchlist instead.
2. New fetchers ship with offline unit tests for their parser.
3. Every source flows through the same keyword filter, remote check,
   dedup, tracker-skip, and headline verification as all the others —
   no source gets a shortcut into the digest.
