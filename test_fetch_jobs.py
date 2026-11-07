#!/usr/bin/env python3
"""Offline unit tests for the headline verification pass in fetch_jobs.py.

The network fetcher (fetch_page_text) is monkeypatched with fakes, so no
test touches the internet. Run:  python3 -m pytest test_fetch_jobs.py
"""
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_jobs as fj


def make_job(**kw):
    job = {
        "id": "t-1",
        "title": "ML Intern",
        "company": "Acme",
        "url": "https://example.com/jobs/1",
        "text": "snippet text",
        "hits": ["llm"],
        "source": "Test",
        "pay": "unknown",
        "type": "internship",
        "ni_score": 1,
        "ni_hits": [],
    }
    job.update(kw)
    return job


def patch_fetch(monkeypatch, func):
    monkeypatch.setattr(fj, "fetch_page_text", func)


# ---------------------------------------------------------------- live page
def test_live_page_marks_verified(monkeypatch):
    job = make_job()
    patch_fetch(monkeypatch, lambda url: "Join our team as an ML intern. "
                                         "Great role, apply today.")
    fj.verify_headlines([job])
    assert job["verified"] is True
    assert job["verify_note"] == ""
    assert job["pay"] == "unknown"  # no pay words in text -> unchanged


# ---------------------------------------------------------------- expired page
def test_expired_marker_demotes(monkeypatch):
    job = make_job()
    patch_fetch(monkeypatch, lambda url: "Sorry — this job is no longer "
                                         "accepting applications.")
    fj.verify_headlines([job])
    assert job["verified"] is False
    assert "closed" in job["verify_note"]
    # demotion path used by main(): partition splits it out of the section
    live, dead = fj.partition_verified([job])
    assert live == []
    assert dead == [job]


def test_http_404_marks_dead(monkeypatch):
    def gone(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    job = make_job()
    patch_fetch(monkeypatch, gone)
    fj.verify_headlines([job])
    assert job["verified"] is False
    assert "404" in job["verify_note"]


def test_http_403_stays_unchecked(monkeypatch):
    # a bot wall proves nothing about the posting — do not demote
    def walled(url):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
    job = make_job()
    patch_fetch(monkeypatch, walled)
    fj.verify_headlines([job])
    assert job["verified"] is None
    assert job["verify_note"] == ""


# ---------------------------------------------------------------- pay re-check
def test_pay_contradiction_corrects_label(monkeypatch):
    # snippet said "unpaid"; the full posting text offers a stipend and
    # contains no unpaid signals -> label must flip to paid, with a note
    job = make_job(pay="unpaid")
    patch_fetch(monkeypatch, lambda url: "This internship offers a stipend "
                                         "of $800 per month for six months.")
    fj.verify_headlines([job])
    assert job["verified"] is True
    assert job["pay"] == "paid"
    assert "corrected" in job["verify_note"]


def test_pay_unresolvable_keeps_snippet_label(monkeypatch):
    job = make_job(pay="unpaid")
    patch_fetch(monkeypatch, lambda url: "A friendly team and real projects.")
    fj.verify_headlines([job])
    assert job["pay"] == "unpaid"  # full text says nothing about pay
    assert job["verify_note"] == ""


# ---------------------------------------------------------------- failures
def test_fetch_exception_leaves_unchecked_and_does_not_crash(monkeypatch):
    def boom(url):
        raise TimeoutError("timed out")
    job = make_job()
    patch_fetch(monkeypatch, boom)
    fj.verify_headlines([job])  # must not raise
    assert job["verified"] is None
    assert job["verify_note"] == ""
    live, dead = fj.partition_verified([job])
    assert live == [job] and dead == []  # stays in its headline section


def test_missing_url_left_unchecked(monkeypatch):
    called = []
    patch_fetch(monkeypatch, lambda url: called.append(url) or "text")
    job = make_job(url="")
    fj.verify_headlines([job])
    assert job["verified"] is None
    assert called == []  # fetcher never invoked


# ---------------------------------------------------------------- cap
def test_cap_respected(monkeypatch):
    calls = []

    def counting(url):
        calls.append(url)
        return "An open role on a great team."

    jobs = [make_job(id=f"t-{i}", url=f"https://example.com/jobs/{i}")
            for i in range(fj.VERIFY_CAP + 3)]
    patch_fetch(monkeypatch, counting)
    fj.verify_headlines(jobs)
    assert len(calls) == fj.VERIFY_CAP
    assert all(j["verified"] is True for j in jobs[:fj.VERIFY_CAP])
    assert all(j["verified"] is None for j in jobs[fj.VERIFY_CAP:])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
