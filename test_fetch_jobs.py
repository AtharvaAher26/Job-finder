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


# ---------------------------------------------------------------- eligibility
# Grounded in the three Nov 7 headline picks that all failed after the
# digest shipped (full posting texts re-read 2026-11-07).
def test_fiducial_like_demoted_on_visa(monkeypatch):
    job = make_job(title="Internship - Programming & Automation",
                   company="Fiducial")
    patch_fetch(monkeypatch, lambda url: (
        "WE CANNOT PROVIDE VISA SPONSORSHIP. Preferred starting date: ASAP. "
        "Location: Aerospace Innovation Hub, Delft, the Netherlands. "
        "Flexible working hours and the option to work from home 2 days per "
        "week where practical. 1000 euro monthly compensation."))
    fj.verify_headlines([job])
    assert job["verified"] is False
    assert "visa" in job["verify_note"]
    live, dead = fj.partition_verified([job])
    assert live == [] and dead == [job]


def test_distalmotion_like_demoted_on_degree(monkeypatch):
    job = make_job(title="Edge AI & Computer Vision Intern",
                   company="Distalmotion")
    patch_fetch(monkeypatch, lambda url: (
        "Requirements: Enrolled in a Master’s degree or final year of a "
        "Bachelor’s program in Computer Science, Robotics, Embedded Systems."))
    fj.verify_headlines([job])
    assert job["verified"] is False
    assert "Master" in job["verify_note"] or "final-year" in job["verify_note"]


def test_tomtom_like_demoted_on_dutch_enrolment_and_commute(monkeypatch):
    job = make_job(title="Software Engineering Intern - AI Platform",
                   company="Tomtom")
    patch_fetch(monkeypatch, lambda url: (
        "Being enrolled in a Dutch university until at least September 2027. "
        "Being located in Amsterdam or cities close by to be able to commute "
        "to the office at least twice a week."))
    fj.verify_headlines([job])
    assert job["verified"] is False
    assert "Dutch" in job["verify_note"]


# ---------------------------------------------------------------- eligibility
# Nov 11 extension — grounded in the three picks withdrawn that morning
# (greenteg AG, Sonio x2; full wording from the Nov 11 correction).
def test_greenteg_like_demoted_on_permit_and_onsite_pct(monkeypatch):
    job = make_job(title="Data Science Internship - Rümlang",
                   company="greenteg AG")
    patch_fetch(monkeypatch, lambda url: (
        "Data Science internship in Rümlang, Switzerland. Requires a valid "
        "Swiss work permit or EU/EFTA citizenship. This role is 80–100% "
        "on-site with only 1–2 remote days a week."))
    fj.verify_headlines([job])
    assert job["verified"] is False
    assert ("permit" in job["verify_note"] or "on-site" in job["verify_note"]
            or "remote days" in job["verify_note"])
    live, dead = fj.partition_verified([job])
    assert live == [] and dead == [job]


def test_sonio_like_demoted_on_master2_bac5(monkeypatch):
    job = make_job(title="Data Science Intern - Paris",
                   company="Sonio")
    patch_fetch(monkeypatch, lambda url: (
        "Candidates must be in Master 2 / Bac+5, enrolled for a 5–6 month "
        "internship in Paris."))
    fj.verify_headlines([job])
    assert job["verified"] is False
    assert "Master 2" in job["verify_note"]


def test_bac5_alone_demotes(monkeypatch):
    job = make_job(title="ML Intern", company="Acme")
    patch_fetch(monkeypatch, lambda url: (
        "Fully remote internship. Open to Bac+5 students only."))
    fj.verify_headlines([job])
    assert job["verified"] is False
    assert "Master 2" in job["verify_note"]


# ---------------------------------------------------------------- eligibility
# Nov 12 extension — grounded in the Axle Careers pick withdrawn that
# morning (Energy Markets - France CDD; full wording from the Nov 12
# correction). The Nov 11 extension would NOT have caught it: no permit
# wording, no on-site %, no Master 2 — just "based in France" plus a
# monthly London-office week.
def test_axle_like_demoted_on_based_in_and_office_week(monkeypatch):
    job = make_job(title="Energy Markets - France (CDD)",
                   company="Axle Careers")
    patch_fetch(monkeypatch, lambda url: (
        "You will speak fluent French and English. You will become our "
        "expert on French power markets. You'll be based in France. To "
        "maximise collaboration, we ask that you spend ~1 week per month "
        "working from our London office. Interview process: initial "
        "interview, take-home exercise, final interview (in-person)."))
    fj.verify_headlines([job])
    assert job["verified"] is False
    assert ("based in" in job["verify_note"]
            or "office" in job["verify_note"])


def test_company_based_in_does_not_demote(monkeypatch):
    # "We're based in Berlin" describes the company, not the candidate —
    # a fully remote posting with it must stay headlined.
    job = make_job(title="AI Engineer Intern", company="Acme")
    patch_fetch(monkeypatch, lambda url: (
        "We're based in Berlin and fully remote worldwide. Stipend paid "
        "monthly."))
    fj.verify_headlines([job])
    assert job["verified"] is True


def test_biannual_retreat_does_not_demote(monkeypatch):
    # A twice-a-year team retreat is not a monthly office requirement.
    job = make_job(title="AI Engineer Intern", company="Acme")
    patch_fetch(monkeypatch, lambda url: (
        "Fully remote internship. Bi-annual retreats to strengthen team "
        "connection. Stipend paid monthly."))
    fj.verify_headlines([job])
    assert job["verified"] is True


def test_work_authorisation_offer_stays_headline(monkeypatch):
    # "We sponsor work authorization" is the opposite of a requirement —
    # it must not demote (cf. Nebius, Nov 5, which *required* it).
    job = make_job(title="AI Engineer Intern", company="Acme")
    patch_fetch(monkeypatch, lambda url: (
        "Fully remote internship. We sponsor work authorization and visas. "
        "Stipend paid monthly."))
    fj.verify_headlines([job])
    assert job["verified"] is True


def test_masters_plus_mention_does_not_demote(monkeypatch):
    job = make_job(title="AI Engineer Intern", company="Acme")
    patch_fetch(monkeypatch, lambda url: (
        "Fully remote internship. A Master's degree is a plus, not required. "
        "Work remotely 5 days a week."))
    fj.verify_headlines([job])
    assert job["verified"] is True


def test_genuine_remote_internship_stays_headline(monkeypatch):
    job = make_job(title="AI Engineer Intern", company="Acme",
                   pay="unknown")
    patch_fetch(monkeypatch, lambda url: (
        "Fully remote internship. Enrolled in a Bachelor's program in "
        "Computer Science. This internship offers a stipend of $800 per month."))
    fj.verify_headlines([job])
    assert job["verified"] is True
    assert job["pay"] == "paid"
    assert job["verify_note"] == "" or "corrected" in job["verify_note"]


def test_asap_start_only_is_warning_not_demotion(monkeypatch):
    job = make_job(title="ML Intern", company="Acme")
    patch_fetch(monkeypatch, lambda url: (
        "Fully remote internship. Preferred starting date: ASAP. "
        "Stipend paid monthly."))
    fj.verify_headlines([job])
    assert job["verified"] is True
    assert "ASAP" in job["verify_note"]


def test_onsite_interview_mention_does_not_warn(monkeypatch):
    job = make_job(title="ML Intern", company="Acme")
    patch_fetch(monkeypatch, lambda url: (
        "Fully remote internship. The selection process includes an onsite "
        "interview at our office."))
    fj.verify_headlines([job])
    assert job["verified"] is True
    assert "on-site" not in job["verify_note"]


def test_is_remote_ok_rejects_partial_wfh_and_commute():
    assert fj.is_remote_ok(
        "Flexible hours and the option to work from home 2 days per week") is False
    assert fj.is_remote_ok(
        "Located in Amsterdam to be able to commute to the office") is False
    assert fj.is_remote_ok("Fully remote, work from anywhere") is True
    assert fj.is_remote_ok("Remote-first team, async") is True


def test_is_remote_ok_rejects_remote_days_cap_and_onsite_pct():
    # Nov 11 (greenteg AG): capped remote days / mostly on-site in the
    # snippet itself, so the posting never reaches the digest at all.
    assert fj.is_remote_ok(
        "Data Science internship, 80–100% on-site with only 1–2 remote "
        "days a week") is False
    assert fj.is_remote_ok("Remote 2 days a week, office the rest") is False
    assert fj.is_remote_ok("Fully remote, work from anywhere") is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
