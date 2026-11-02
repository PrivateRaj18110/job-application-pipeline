"""
Test Suite: test_outreach.py
Offline verification of the portfolio builder and cold email engine.
Validates:
1. cv.json validation and markdown rendering (portfolio_builder.py)
2. Contact store: validation, dedupe, CSV import (cold_emailer.py)
3. Template drafting without an LLM
4. Dry-run sending writes .eml previews and never counts as "emailed"
5. Live sending (with a fake SMTP sender): threading, do-not-contact, follow-ups, daily limit

Nothing here touches the network: contacts live in a temp folder, the LLM is disabled,
and SMTP / IMAP calls are replaced with in-memory fakes.
"""

import os
import sys
import asyncio
import tempfile
from datetime import datetime, timedelta
from email import message_from_bytes, policy
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import portfolio_builder
import cold_emailer

# Offline sandbox: no LLM, temp contact store, no tracker lookups, no network
os.environ["LLM_PROVIDER"] = "none"
TMP_DIR = Path(tempfile.mkdtemp(prefix="outreach_test_"))
cold_emailer.CONTACTS_FILE = TMP_DIR / "contacts.json"
cold_emailer.EMAIL_PREVIEW_DIR = TMP_DIR / "emails"
cold_emailer._job_context = lambda job_url: ("", None)
cold_emailer.check_replies = lambda settings=None: 0

SENT_MESSAGES = []
cold_emailer._smtp_send = lambda msg, settings: SENT_MESSAGES.append(msg)

CV = portfolio_builder.load_cv()


def print_banner(title: str):
    print("\n" + "=" * 70)
    print(f"[*] RUNNING TEST: {title}")
    print("=" * 70)


def reset_store():
    if cold_emailer.CONTACTS_FILE.exists():
        cold_emailer.CONTACTS_FILE.unlink()
    SENT_MESSAGES.clear()


def set_live_env(daily_limit: int = 15):
    os.environ.update({
        "SMTP_USER": "tester@example.com",
        "SMTP_APP_PASSWORD": "fake-app-password",
        "EMAIL_DRY_RUN": "false",
        "EMAIL_DAILY_LIMIT": str(daily_limit),
        "EMAIL_MIN_DELAY_SECONDS": "0",
        "EMAIL_MAX_DELAY_SECONDS": "0",
    })


def set_dry_run_env():
    for key in ("SMTP_USER", "SMTP_APP_PASSWORD"):
        os.environ.pop(key, None)
    os.environ["EMAIL_DRY_RUN"] = "true"


def test_cv_builder():
    assert portfolio_builder.validate_cv(CV) == [], "Bundled cv.json should be valid"
    bad = dict(CV, skills=[{"category": "X", "items": [{"name": "Y", "level": 9}]}])
    assert any("level" in e for e in portfolio_builder.validate_cv(bad)), "Out-of-range skill level not caught"
    assert portfolio_builder.validate_cv({"profile": {}}), "Missing sections not caught"

    md = portfolio_builder.cv_to_markdown(CV)
    for project in CV["projects"]:
        assert project["name"] in md, f"Project {project['name']} missing from markdown"
    if not CV["profile"].get("show_phone") and CV["profile"].get("phone"):
        assert CV["profile"]["phone"] not in md, "Phone leaked into public markdown"
    print(f"  [PASS] CV validates and renders ({len(md)} chars of markdown)")


def test_contact_store():
    reset_store()
    c = cold_emailer.add_contact({"name": "Priya Shah", "email": " Priya@Acme.example.com ", "company": "Acme"})
    assert c["email"] == "priya@acme.example.com" and c["status"] == "new"

    for bad_email, reason in (("not-an-email", "invalid"), ("PRIYA@acme.example.com", "duplicate")):
        try:
            cold_emailer.add_contact({"email": bad_email})
            raise AssertionError(f"{reason} email was accepted")
        except ValueError:
            pass

    csv_text = (
        "First Name,Last Name,E-mail,Organization,Job Title\n"
        "Sam,Lee,sam@globex.example.com,Globex,Backend Engineer\n"
        "Bad,Row,nope,Initech,QA\n"
        "Dup,Row,priya@acme.example.com,Acme,ML\n"
    )
    result = cold_emailer.import_contacts_csv(csv_text)
    assert result["added"] == 1 and len(result["skipped"]) == 2, f"Unexpected import result: {result}"
    sam = next(c for c in cold_emailer.load_contacts() if c["email"].startswith("sam@"))
    assert sam["name"] == "Sam Lee" and sam["company"] == "Globex" and sam["role"] == "Backend Engineer"
    print(f"  [PASS] Validation, dedupe and CSV aliases work (skipped: {result['skipped']})")


def test_template_draft():
    reset_store()
    c = cold_emailer.add_contact({"name": "Dana Ortiz", "email": "dana@quantfirm.example.com",
                                  "company": "QuantFirm", "role": "Quant Developer", "notes": "C++ low latency team"})
    drafted = cold_emailer.draft_contact(c["id"], CV)
    assert drafted["status"] == "drafted"
    assert "Hi Dana" in drafted["body"] and "QuantFirm" in drafted["body"]
    project_names = [p["name"] for p in CV["projects"]]
    assert any(name in drafted["body"] for name in project_names), "Draft should cite a real CV project"
    print(f"  [PASS] Template draft: '{drafted['subject']}'")


def test_dry_run_send():
    reset_store()
    set_dry_run_env()
    c = cold_emailer.add_contact({"name": "Lee Chen", "email": "lee@startup.example.com", "company": "Startup"})
    result = cold_emailer.send_contact_email(c["id"], cv=CV)
    assert result["status"] == "previewed", result
    assert not SENT_MESSAGES, "Dry run must never call SMTP"

    contact = result["contact"]
    assert contact["status"] == "previewed" and not cold_emailer._already_emailed(contact)
    eml_files = list(cold_emailer.EMAIL_PREVIEW_DIR.glob("*.eml"))
    assert eml_files, "No .eml preview written"
    msg = message_from_bytes(eml_files[-1].read_bytes(), policy=policy.default)
    text = msg.get_body(preferencelist=("plain",)).get_content()
    assert cold_emailer.OPT_OUT_LINE in text and CV["profile"]["name"] in text
    assert any(part.get_filename() for part in msg.iter_attachments()), "CV PDF not attached"
    print(f"  [PASS] Dry run wrote {eml_files[-1].name} with CV attached")


def test_live_send_rules():
    reset_store()
    set_live_env()
    c = cold_emailer.add_contact({"name": "Ana Silva", "email": "ana@bank.example.com", "company": "Bank", "role": "Quant Dev"})
    first = cold_emailer.send_contact_email(c["id"], cv=CV)
    assert first["status"] == "sent" and len(SENT_MESSAGES) == 1
    assert first["contact"]["thread_message_id"] == SENT_MESSAGES[0]["Message-ID"]

    again = cold_emailer.send_contact_email(c["id"], cv=CV)
    assert again["status"] == "skipped" and len(SENT_MESSAGES) == 1, "Initial email sent twice"

    settings = cold_emailer.get_settings()
    assert not cold_emailer._follow_up_due(cold_emailer.get_contact(c["id"]), settings), "Follow-up due too early"

    def age_history(contact):
        for h in contact["history"]:
            h["at"] = (datetime.now() - timedelta(days=settings["followup_days"] + 1)).isoformat(timespec="seconds")
    cold_emailer._mutate_contact(c["id"], age_history)
    assert cold_emailer._follow_up_due(cold_emailer.get_contact(c["id"]), settings)

    follow = cold_emailer.send_contact_email(c["id"], kind="follow_up", cv=CV)
    assert follow["status"] == "sent" and follow["contact"]["status"] == "followed_up"
    assert SENT_MESSAGES[-1]["In-Reply-To"] == SENT_MESSAGES[0]["Message-ID"], "Follow-up not threaded"
    assert SENT_MESSAGES[-1]["Subject"].startswith("Re: ")
    cold_emailer._mutate_contact(c["id"], age_history)
    assert not cold_emailer._follow_up_due(cold_emailer.get_contact(c["id"]), settings), "Max follow-ups ignored"

    blocked = cold_emailer.add_contact({"email": "nope@corp.example.com"})
    cold_emailer.update_contact(blocked["id"], {"status": "do_not_contact"})
    assert cold_emailer.send_contact_email(blocked["id"], cv=CV)["status"] == "skipped"
    assert len(SENT_MESSAGES) == 2
    print("  [PASS] No double sends, threaded follow-up, follow-up cap and do-not-contact respected")


def test_cycle_daily_limit():
    reset_store()
    set_live_env(daily_limit=1)
    for i in range(3):
        cold_emailer.add_contact({"name": f"Person {i}", "email": f"p{i}@co{i}.example.com", "company": f"Co{i}"})

    summary = asyncio.run(cold_emailer.run_outreach_cycle(auto_send=True))
    assert summary["drafted"] == 3 and summary["sent"] == 1 and summary["deferred"] == 2, summary
    summary_off = asyncio.run(cold_emailer.run_outreach_cycle(auto_send=False))
    assert summary_off["sent"] == 0 and len(SENT_MESSAGES) == 1, "Auto-send off still sent mail"
    print(f"  [PASS] Daily cap enforced: {summary}")


def run_all_tests():
    print("*" * 70)
    print("🚀 STARTING PORTFOLIO & OUTREACH VERIFICATION SUITE")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Sandbox: {TMP_DIR}")
    print("*" * 70)

    tests = [
        ("CV Builder & Validation", test_cv_builder),
        ("Contact Store & CSV Import", test_contact_store),
        ("Template Drafting (No LLM)", test_template_draft),
        ("Dry-Run Sending", test_dry_run_send),
        ("Live Sending Rules (Fake SMTP)", test_live_send_rules),
        ("Outreach Cycle Daily Limit", test_cycle_daily_limit),
    ]
    results = {}
    for name, fn in tests:
        print_banner(name)
        try:
            fn()
            results[name] = "PASSED"
        except Exception as e:
            print(f"  [FAIL] {type(e).__name__}: {e}")
            results[name] = f"FAILED: {e}"

    print("\n" + "=" * 70)
    print("📊 OUTREACH TEST SUMMARY")
    print("=" * 70)
    for name, result in results.items():
        icon = "✅" if result == "PASSED" else "❌"
        print(f"{icon} {name:35}: {result}")
    print("=" * 70)
    return all(r == "PASSED" for r in results.values())


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
