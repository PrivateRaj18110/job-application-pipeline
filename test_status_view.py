"""
Test Suite: test_status_view.py
Offline verification of the view-only status page and the private remote link (no network, no real data).
Validates:
1. On the private remote host only the status page and its summary are reachable; everything else is refused
2. On this machine the full dashboard still works, and /status serves the status page
3. Unknown hosts are rejected
4. The summary lists jobs newest first with their company, counts today's applications, and exposes no settings
"""

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REMOTE = "phone-test.tailnet-example.ts.net"
os.environ["DASHBOARD_ALLOWED_HOSTS"] = REMOTE  # must be set before the dashboard is imported

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient

import app as dashboard
import cold_emailer
import sheet_manager
import tracker

TODAY = datetime.now().strftime("%Y-%m-%d")
JOBS = [
    {"Date Found": "2026-11-01 08:00:00", "Job Title": "Backend Engineer", "Company": "Beta Labs", "Job URL": "https://beta.dev/jobs/2",
     "Tailored Resume Path": "", "Application Status": "Blocked - CAPTCHA / Questionnaire (2026-11-01 08:05:00)"},
    {"Date Found": f"{TODAY} 09:00:00", "Job Title": "AI Engineer", "Company": "Acme AI", "Job URL": "https://acme.ai/jobs/1",
     "Tailored Resume Path": "output/Resume_acme.pdf", "Application Status": f"Applied ({TODAY} 09:30:00)"},
]
SUMMARY_KEYS = {"generated_at", "pipeline", "outreach", "today", "totals", "funnel", "stage_labels", "applications", "companies", "recent"}


def with_fakes(fn):
    def run():
        saved = (sheet_manager.get_all_jobs, cold_emailer.load_contacts, tracker.TRACKER_FILE)
        sheet_manager.get_all_jobs = lambda: [dict(j) for j in JOBS]
        cold_emailer.load_contacts = lambda: []
        tracker.TRACKER_FILE = Path(tempfile.mkdtemp(prefix="status_test_")) / "tracker.json"
        try:
            fn()
        finally:
            sheet_manager.get_all_jobs, cold_emailer.load_contacts, tracker.TRACKER_FILE = saved
    run.__name__ = fn.__name__
    return run


@with_fakes
def test_remote_link_is_view_only():
    remote = TestClient(dashboard.app, base_url=f"http://{REMOTE}")
    page = remote.get("/")
    assert page.status_code == 200 and "Job search status" in page.text, "The link opens the status page"
    assert remote.get("/api/summary").status_code == 200
    refused = [("POST", "/api/run"), ("POST", "/api/outreach/run"), ("POST", "/api/daemon/start"), ("GET", "/api/contacts"),
               ("GET", "/api/tracker"), ("PUT", "/api/tracker/acme-ai"), ("GET", "/api/status"), ("GET", "/api/cv"),
               ("GET", "/api/resume"), ("GET", "/static/index.html"), ("GET", "/portfolio/cv.json"), ("HEAD", "/")]
    for method, path in refused:
        status = remote.request(method, path).status_code
        assert status == 403, f"{method} {path} returned {status} on the remote link"
    print(f"  [PASS] Remote link serves only the status page and summary; {len(refused)} other requests refused")


@with_fakes
def test_local_dashboard_unchanged():
    local = TestClient(dashboard.app, base_url="http://127.0.0.1:8000")
    assert "Control Center" in local.get("/").text, "On the laptop / is still the full dashboard"
    assert "Job search status" in local.get("/status").text
    assert local.get("/api/tracker").status_code == 200
    print("  [PASS] Full dashboard unchanged on this machine; /status available here too")


def test_unknown_host_rejected():
    other = TestClient(dashboard.app, base_url="http://evil.example.com")
    assert other.get("/api/summary").status_code == 400 and other.get("/").status_code == 400
    print("  [PASS] Unknown hosts rejected")


@with_fakes
def test_summary_content():
    summary = TestClient(dashboard.app, base_url=f"http://{REMOTE}").get("/api/summary").json()
    assert set(summary) == SUMMARY_KEYS, set(summary) ^ SUMMARY_KEYS
    assert [a["company"] for a in summary["applications"]] == ["Acme AI", "Beta Labs"], "Newest first"
    assert summary["today"]["applied"] == 1
    assert (summary["totals"]["applied"], summary["totals"]["needs_you"]) == (1, 1)
    assert all(set(c) == {"name", "stage", "stage_label", "contacts", "next_follow_up", "follow_up_overdue", "last_activity"}
               for c in summary["companies"]), "Company records carry no notes or other fields"
    print("  [PASS] Summary: jobs newest first, today's count, totals, and only the fields the page needs")


def run_all_tests() -> bool:
    tests = [test_remote_link_is_view_only, test_local_dashboard_unchanged, test_unknown_host_rejected, test_summary_content]
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
        print(f"{'✅' if result == 'PASSED' else '❌'} {name:30}: {result}")
    return all(r == "PASSED" for r in results.values())


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
