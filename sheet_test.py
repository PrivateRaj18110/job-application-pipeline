"""
Script: sheet_test.py
Live Write-Test for Google Sheets Connectivity and Resume Tailoring Engine.

Steps:
1. Verifies credentials.json and GOOGLE_SHEET_ID.
2. Reads master_resume.md.
3. Inserts a mock job entry for 'Low-Latency Algorithmic Trading Engineer'.
4. Triggers resume_tailor.py to pull experience with:
   - C++ execution engines
   - Numba-accelerated Python
   - Broker API integrations (MetaTrader 5, FlatTrade)
   and generates a role-tailored PDF in /output.
5. Updates row status to 'Tailored (Live Test Complete)'.
6. Confirms row registration.
"""

import sys
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Reconfigure console output encoding
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv()

import sheet_manager
import resume_tailor


def run_live_test():
    print("=" * 80)
    print("🧪 STARTING LIVE GOOGLE SHEETS & RESUME TAILOR WRITE-TEST")
    print(f"Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # 1. Environment & Credentials Verification
    sheet_id = os.getenv("GOOGLE_SHEET_ID", sheet_manager.DEFAULT_SHEET_ID)
    creds_file = BASE_DIR / os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json")

    print(f"[*] Target Google Sheet ID : {sheet_id}")
    print(f"[*] Credentials File Path  : {creds_file}")

    creds_exist = creds_file.exists()
    if creds_exist:
        print("    ✅ credentials.json is present in the workspace.")
    else:
        print("    ⚠️ credentials.json is NOT detected in the workspace.")
        print("       (Operations will record to sheet_local_backup.json until credentials.json is supplied)")

    # 2. Verify Master Resume Ground Truth
    resume_path = BASE_DIR / "master_resume.md"
    print(f"\n[*] Reading Master Resume from: {resume_path}")
    assert resume_path.exists(), "master_resume.md not found!"
    with open(resume_path, "r", encoding="utf-8") as f:
        resume_text = f.read()

    has_cpp = "C++" in resume_text and "Execution Engine" in resume_text
    has_numba = "Numba" in resume_text
    has_brokers = "MetaTrader 5" in resume_text or "FlatTrade" in resume_text
    print(f"    - C++ Execution Engine experience detected : {'✅ YES' if has_cpp else '❌ NO'}")
    print(f"    - Numba acceleration experience detected    : {'✅ YES' if has_numba else '❌ NO'}")
    print(f"    - Broker APIs (MT5 / FlatTrade) detected   : {'✅ YES' if has_brokers else '❌ NO'}")

    # 3. Create Job Payload
    job_url = f"https://example.com/careers/quant/low-latency-trading-engineer-{int(datetime.now().timestamp())}"
    job_payload = {
        "title": "Low-Latency Algorithmic Trading Engineer",
        "company": "AlphaQuant Execution Labs",
        "job_url": job_url,
        "description": (
            "We are hiring a Low-Latency Algorithmic Trading Engineer. "
            "Key responsibilities include architecting high-performance C++ execution engines with lock-free data structures, "
            "optimizing quantitative signal models using Numba-accelerated Python, and maintaining robust broker API gateways "
            "including MetaTrader 5 (MT5) and FlatTrade with real-time WebSocket tick streaming. "
            "Strong background in multithreading, Linux socket programming, and automated order execution is essential."
        ),
    }

    # 4. Insert Job Entry into Sheet
    print(f"\n[*] Step 1: Inserting job entry into sheet manager...")
    print(f"    Role    : {job_payload['title']}")
    print(f"    Company : {job_payload['company']}")
    print(f"    URL     : {job_payload['job_url']}")

    logged = sheet_manager.log_new_job(job_payload)
    if logged:
        print("    ✅ Successfully logged new job row (Initial Status: 'Pending Tailoring')")
    else:
        print("    ❌ Failed to log new job row")
        return False

    # 5. Tailor Resume via resume_tailor.py & Compile PDF
    print(f"\n[*] Step 2: Triggering resume_tailor.py to extract trading engine experience...")
    pdf_path = resume_tailor.tailor_and_export(
        job_description=job_payload["description"],
        job_title="Low-Latency Algorithmic Trading Engineer",
    )
    print(f"    ✅ Tailored PDF resume compiled successfully:")
    print(f"       -> {pdf_path}")
    assert Path(pdf_path).exists(), f"PDF was not created at {pdf_path}"

    # 6. Update Google Sheet Status to 'Tailored (Live Test Complete)'
    target_status = "Tailored (Live Test Complete)"
    print(f"\n[*] Step 3: Updating row status to '{target_status}'...")
    updated = sheet_manager.update_status(
        job_url=job_url,
        new_status=target_status,
        resume_path=pdf_path,
    )

    if updated:
        print(f"    ✅ Successfully updated status to '{target_status}'")
    else:
        print(f"    ❌ Failed to update status")
        return False

    # 7. Final Verification
    print("\n" + "=" * 80)
    print("📊 WRITE-TEST RESULTS SUMMARY")
    print("=" * 80)
    print(f"Role               : {job_payload['title']}")
    print(f"Company            : {job_payload['company']}")
    print(f"Job URL            : {job_payload['job_url']}")
    print(f"Final Status       : {target_status}")
    print(f"PDF Location       : {pdf_path}")

    if creds_exist and sheet_manager.get_manager().worksheet:
        print("Google Sheets Mode : 🟢 LIVE GOOGLE SHEET (Connected & Synced)")
        print(f"Google Sheet URL   : https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
    else:
        print("Google Sheets Mode : 🟡 LOCAL SIMULATION BACKUP (sheet_local_backup.json)")
        print("                     To sync with the LIVE Google Sheet, download your Google Cloud")
        print("                     service account key as 'credentials.json' and place it in the")
        print("                     project workspace root.")

    print("=" * 80)
    return True


if __name__ == "__main__":
    success = run_live_test()
    if not success:
        sys.exit(1)
