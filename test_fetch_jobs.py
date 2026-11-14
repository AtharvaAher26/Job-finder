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


# ---------------------------------------------------------------- eligibility
# Nov 13 extension — grounded in the two Paris internships headlined
# Nov 13 and withdrawn the same morning after reading the full
# postings (Mirakl: HR role, French C2, 2 remote days/month, Paris
# office; Meetdavis: AI Engineer Intern, "Read and write French",
# Paris team of 12, no remote stated).
def test_mirakl_like_demoted_on_french_and_monthly_remote_cap(monkeypatch):
    job = make_job(title="Data & People analytics Intern - January 2027",
                   company="Mirakl")
    patch_fetch(monkeypatch, lambda url: (
        "Currently pursuing a Bachelor's or Master's degree in HR. "
        "Availability for a 6-month internship starting in January 2027 "
        "is required. French: Fluent (C2 level required). English: "
        "Professional proficiency. Perks: 2 remote work days per month. "
        "Modern offices in the heart of Paris."))
    fj.verify_headlines([job])
    assert job["verified"] is False
    assert ("French" in job["verify_note"]
            or "remote days" in job["verify_note"])


def test_meetdavis_like_demoted_on_read_write_french(monkeypatch):
    job = make_job(title="AI Engineer Intern", company="Meetdavis")
    patch_fetch(monkeypatch, lambda url: (
        "AI Engineer Intern to build multi-agent systems for real-estate "
        "workflows. Read and write French: our sources and deliverables "
        "are in French. Competitive salary. Team of 12 in Paris."))
    fj.verify_headlines([job])
    assert job["verified"] is False
    assert "French" in job["verify_note"]


def test_french_plus_does_not_demote(monkeypatch):
    # "French is a plus" is a preference, not a requirement — a fully
    # remote posting with it must stay headlined.
    job = make_job(title="AI Engineer Intern", company="Acme")
    patch_fetch(monkeypatch, lambda url: (
        "Fully remote internship. French is a plus, not required. "
        "Stipend paid monthly."))
    fj.verify_headlines([job])
    assert job["verified"] is True


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


def test_adjoe_like_working_student_warns_not_demotes(monkeypatch):
    # Nov 14: adjoe Working Student - Data Science, Hamburg — text
    # states no blocker, no remote option, no office share; just a
    # Hamburg title, current enrolment, up to 20h/week in semester.
    # Must stay headlined (verified True) but carry the Working
    # Student location warning, so tomorrow's digest flags it.
    job = make_job(title="Working Student - Data Science",
                   company="adjoe")
    patch_fetch(monkeypatch, lambda url: (
        "You are currently pursuing a Bachelor's or Master's in Data "
        "Science, Computer Science, Mathematics, Statistics, or a "
        "related quantitative field. You are available to contribute "
        "up to 20 hours per week during the semester. Solid Python "
        "skills and hands-on familiarity with PyTorch, TensorFlow, "
        "scikit-learn, and gradient boosting libraries."))
    fj.verify_headlines([job])
    assert job["verified"] is True
    assert "Working Student" in job["verify_note"]


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


# ------------------------------------------------------------- Next Play source

NEXTPLAY_HTML = """
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
  {"@type": "ListItem", "position": 1,
   "name": "Applied AI Engineer at Legora",
   "url": "https://nextplay.so/jobs/aaaa1111-2222-3333-4444-555555555555"},
  {"@type": "ListItem", "position": 2,
   "name": "Account Executive at Xapien",
   "url": "https://nextplay.so/jobs/bbbb1111-2222-3333-4444-555555555555"}
]}
</script>
<script type="application/ld+json">{not valid json</script>
</head><body></body></html>
"""


def test_nextplay_parser_extracts_role_and_company():
    listings = fj.parse_nextplay_listings(NEXTPLAY_HTML)
    assert len(listings) == 2  # broken JSON-LD blob is skipped, not fatal
    assert listings[0] == {
        "title": "Applied AI Engineer",
        "company": "Legora",
        "url": "https://nextplay.so/jobs/aaaa1111-2222-3333-4444-555555555555",
    }
    assert listings[1]["title"] == "Account Executive"


def test_nextplay_parser_handles_missing_at_and_empty_input():
    html = ('<script type="application/ld+json">'
            '{"itemListElement": [{"name": "Solo Role", '
            '"url": "https://nextplay.so/jobs/x"}]}</script>')
    listings = fj.parse_nextplay_listings(html)
    assert listings[0]["title"] == "Solo Role"
    assert listings[0]["company"] == ""
    assert fj.parse_nextplay_listings("") == []
    assert fj.parse_nextplay_listings("<html>no ld+json here</html>") == []


# ------------------------------------------------------------- Himalayas source

HIMALAYAS_PAGE = {
    "jobs": [
        {
            "title": "Machine Learning Intern",
            "companyName": "Acme AI",
            "employmentType": "Internship",
            "categories": ["Machine-Learning", "AI"],
            "locationRestrictions": ["India"],
            "guid": "https://himalayas.app/companies/acme/jobs/ml-intern",
            "applicationLink":
                "https://himalayas.app/companies/acme/jobs/ml-intern"
                "?utm_source=api",
        },
        {
            "title": "Sales Executive",
            "companyName": "Widgets Inc",
            "employmentType": "Full Time",
            "categories": ["Sales"],
            "locationRestrictions": ["United States"],
            "guid":
                "https://himalayas.app/companies/widgets/jobs/sales-exec",
        },
    ],
    "nextCursor": "cursor-abc",
}


def test_himalayas_parser_maps_fields():
    listings = fj.parse_himalayas_jobs(HIMALAYAS_PAGE)
    assert len(listings) == 2
    first = listings[0]
    assert first["title"] == "Machine Learning Intern"
    assert first["company"] == "Acme AI"
    assert first["url"] == \
        "https://himalayas.app/companies/acme/jobs/ml-intern"
    assert "Internship" in first["context"]
    assert "India" in first["context"]


def test_himalayas_parser_dedupes_and_falls_back_to_application_link():
    page = {"jobs": [
        {"title": "Data Intern", "companyName": "Dup Co",
         "guid": "https://himalayas.app/jobs/dup"},
        {"title": "Data Intern (repost)", "companyName": "Dup Co",
         "guid": "https://himalayas.app/jobs/dup"},
        {"title": "NLP Intern", "companyName": "NoGuid Ltd",
         "applicationLink":
             "https://himalayas.app/jobs/nlp-intern?utm_source=api"},
    ]}
    listings = fj.parse_himalayas_jobs(page)
    assert [listing["title"] for listing in listings] == \
        ["Data Intern", "NLP Intern"]
    # utm query is stripped from the fallback link
    assert listings[1]["url"] == "https://himalayas.app/jobs/nlp-intern"


def test_himalayas_parser_skips_missing_fields():
    page = {"jobs": [
        {"companyName": "No Title Co",
         "guid": "https://himalayas.app/jobs/x"},
        {"title": "No URL Role", "companyName": "No Link Co"},
        "not a dict",
        {"title": "  ", "guid": "https://himalayas.app/jobs/blank"},
    ]}
    assert fj.parse_himalayas_jobs(page) == []
    assert fj.parse_himalayas_jobs({}) == []
    assert fj.parse_himalayas_jobs({"jobs": None}) == []
    assert fj.parse_himalayas_jobs({"jobs": []}) == []


def test_himalayas_fetch_paginates_filters_and_shapes(monkeypatch):
    pages = {
        None: HIMALAYAS_PAGE,
        "cursor-abc": {"jobs": [
            {"title": "LLM Engineering Intern", "companyName": "Beta Labs",
             "employmentType": "Internship",
             "guid":
                 "https://himalayas.app/companies/beta/jobs/llm-intern"},
        ], "nextCursor": None},
    }
    calls = []

    class FakeResp:
        def __init__(self, payload):
            self._body = fj.json.dumps(payload).encode()

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, **kwargs):
        calls.append(req.full_url)
        cursor = None
        if "cursor=" in req.full_url:
            cursor = req.full_url.split("cursor=", 1)[1]
        return FakeResp(pages[cursor])

    monkeypatch.setattr(fj.urllib.request, "urlopen", fake_urlopen)
    jobs = fj.fetch_himalayas()
    assert len(calls) == 2  # stopped when nextCursor ran out
    titles = [j["title"] for j in jobs]
    assert "Machine Learning Intern" in titles
    assert "LLM Engineering Intern" in titles
    assert "Sales Executive" not in titles  # keyword filter still applies
    job = jobs[0]
    assert job["source"] == "Himalayas"
    assert job["id"].startswith("himalayas-")
    assert job["company"] == "Acme AI"
    assert job["hits"]
