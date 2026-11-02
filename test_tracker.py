"""
Test Suite: test_tracker.py
Offline verification of the private Company Tracker (no network, no real data touched).
Validates:
1. Apply-bot statuses are grouped correctly
2. Applications and emails merge per company, and the automatic stage follows the best signal
3. Follow-up due dates and totals
4. Stages and notes you set are saved, override the automatic stage, and unknown stages are refused
"""

import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import cold_emailer
import sheet_manager
import tracker

JOBS = [
    {"Date Found": "2026-11-01 10:00:00", "Job Title": "AI Engineer", "Company": "Acme AI", "Job URL": "https://acme.ai/jobs/1",
     "Tailored Resume Path": "output/Resume_acme.pdf", "Application Status": "Applied (2026-11-01 10:05:00)"},
    {"Date Found": "2026-11-01 11:00:00", "Job Title": "Backend Engineer", "Company": "Beta Labs", "Job URL": "https://beta.dev/jobs/2",
     "Tailored Resume Path": "", "Application Status": "Blocked - CAPTCHA / Questionnaire (2026-11-01 11:02:00)"},
]
CONTACTS = [
    {"id": "c1", "name": "Priya", "email": "priya@acme.ai", "company": "ACME AI", "role": "Recruiter", "status": "replied",
     "history": [{"type": "initial", "at": "2026-11-01T12:00:00"}, {"type": "reply", "at": "2026-11-02T09:00:00"}]},
    {"id": "c2", "name": "Ravi", "email": "ravi@gamma.io", "company": "Gamma", "role": "", "status": "sent",
     "history": [{"type": "initial", "at": "2026-10-20T12:00:00"}]},
]


def with_fakes(fn):
    def run():
        saved = (sheet_manager.get_all_jobs, cold_emailer.load_contacts, tracker.TRACKER_FILE)
        sheet_manager.get_all_jobs = lambda: [dict(j) for j in JOBS]
        cold_emailer.load_contacts = lambda: [dict(c) for c in CONTACTS]
        tracker.TRACKER_FILE = Path(tempfile.mkdtemp(prefix="tracker_test_")) / "tracker.json"
        try:
            fn()
        finally:
            sheet_manager.get_all_jobs, cold_emailer.load_contacts, tracker.TRACKER_FILE = saved
    run.__name__ = fn.__name__
    return run


def test_application_states():
    cases = {
        "Applied (2026-11-01 10:05:00)": "applied", "Applied (Pending Confirmation) (2026-11-01 10:05:00)": "applied",
        "Failed - Needs Manual Check (2026-11-01 10:05:00)": "needs_you", "Blocked - CAPTCHA / Questionnaire": "needs_you",
        "Staged (Dry-run verified) (2026-11-01 10:05:00)": "staged", "Tailored": "tailored", "Pending Tailoring": "pending",
    }
    for status, expected in cases.items():
        assert tracker.application_state(status) == expected, (status, tracker.application_state(status))
    print("  [PASS] Applied, blocked, failed, staged, tailored and pending statuses grouped")


@with_fakes
def test_merge_and_stages():
    overview = tracker.build_overview()
    by_key = {c["key"]: c for c in overview["companies"]}
    assert set(by_key) == {"acme-ai", "beta-labs", "gamma"}, by_key.keys()
    acme = by_key["acme-ai"]
    assert len(acme["applications"]) == 1 and len(acme["contacts"]) == 1, "'Acme AI' and 'ACME AI' must merge"
    assert acme["stage"] == "replied", "A reply outranks an application"
    assert by_key["beta-labs"]["stage"] == "needs_you"
    assert by_key["gamma"]["stage"] == "emailed"
    assert overview["recent"][0]["company"] == "Acme AI" and overview["recent"][0]["type"] == "reply"
    print("  [PASS] Applications and emails merged per company; automatic stages replied / needs you / emailed")


@with_fakes
def test_follow_ups_and_totals():
    overview = tracker.build_overview()
    gamma = next(c for c in overview["companies"] if c["key"] == "gamma")
    days = cold_emailer.get_settings()["followup_days"]
    assert gamma["contacts"][0]["follow_up_due"] == f"2026-10-{20 + days:02d}"
    assert gamma["follow_up_overdue"], "A follow-up due in the past is overdue"
    t = overview["totals"]
    assert (t["companies"], t["applied"], t["needs_you"], t["emails_sent"], t["replies"]) == (3, 1, 1, 2, 1), t
    assert t["reply_rate"] == 0.5
    print(f"  [PASS] Follow-up due {days} days after the last email; totals and reply rate correct")


@with_fakes
def test_manual_stage_and_notes():
    tracker.update_company("acme-ai", stage="interview", notes="  Round 1 on Friday  ")
    acme = next(c for c in tracker.build_overview()["companies"] if c["key"] == "acme-ai")
    assert acme["stage"] == "interview" and acme["stage_source"] == "you" and acme["notes"] == "Round 1 on Friday"
    tracker.update_company("acme-ai", stage="auto")
    acme = next(c for c in tracker.build_overview()["companies"] if c["key"] == "acme-ai")
    assert acme["stage"] == "replied" and acme["notes"] == "Round 1 on Friday", "Back to automatic keeps the notes"
    try:
        tracker.update_company("acme-ai", stage="hired-ish")
        raise AssertionError("Unknown stage must be refused")
    except ValueError:
        pass
    print("  [PASS] Your stage overrides the automatic one, notes persist, unknown stages refused")


def run_all_tests() -> bool:
    tests = [test_application_states, test_merge_and_stages, test_follow_ups_and_totals, test_manual_stage_and_notes]
    results = {}
    for fn in tests:
        print(f"\n[*] {fn.__name__}")
        try:
            fn()
            results[fn.__name__] = "PASSED"
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            results[fn.__name__] = f"FAILED: {e}"
    print("\n" + "=" * 60)
    for name, result in results.items():
        print(f"{'✅' if result == 'PASSED' else '❌'} {name:28}: {result}")
    return all(r == "PASSED" for r in results.values())


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
