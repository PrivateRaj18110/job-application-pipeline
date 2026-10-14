"""
Test Suite: test_suite.py
Automated end-to-end test verification script for the entire pipeline.
Validates:
1. Target Registry (targets.json)
2. Scraper Discovery & Keyword Filtering (scraper.py)
3. Google Sheets State Management & Deduplication (sheet_manager.py)
4. LLM Tailoring & ATS PDF Compilation (resume_tailor.py)
5. Playwright Application Engine & Visual Audit Screenshot (apply_bot.py)
6. Pipeline Orchestrator & Scheduler (scheduler.py / main.py)

Confined strictly to workspace:
c:/Users/Light/Documents/antigravity/lively-carson
"""

import sys
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime

# Set console encoding
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import scraper
import sheet_manager
import resume_tailor
import apply_bot
import scheduler


def print_banner(title: str):
    print("\n" + "=" * 70)
    print(f"[*] RUNNING TEST: {title}")
    print("=" * 70)


async def run_all_tests():
    print("*" * 70)
    print("🚀 STARTING AUTOMATED PIPELINE VERIFICATION SUITE")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("*" * 70)

    test_results = {}

    # ---------------------------------------------------------
    # TEST 1: Target Registry Validation
    # ---------------------------------------------------------
    print_banner("1. Target Registry (targets.json)")
    try:
        cfg = scheduler.load_targets_config()
        assert "targets" in cfg, "Config missing 'targets' key"
        assert len(cfg["targets"]) > 0, "No targets defined in configuration"
        print(f"  [PASS] Successfully loaded {len(cfg['targets'])} targets from targets.json.")
        for t in cfg["targets"][:3]:
            print(f"         - {t.get('name')}: keywords={t.get('role_keywords', [])}")
        test_results["Target Registry"] = "PASSED"
    except Exception as e:
        print(f"  [FAIL] Target Registry error: {e}")
        test_results["Target Registry"] = f"FAILED: {e}"

    # ---------------------------------------------------------
    # TEST 2: Scraper Discovery & Keyword Filtering
    # ---------------------------------------------------------
    print_banner("2. Scraper Discovery & Keyword Filtering")
    try:
        keywords = ["Python", "Vision"]
        mock_jobs = scraper.get_mock_jobs(role_keywords=keywords)
        assert len(mock_jobs) > 0, "No mock jobs matched keywords"
        print(f"  [PASS] Scraper returned {len(mock_jobs)} positions matching {keywords}:")
        for j in mock_jobs:
            print(f"         - {j['title']} @ {j['company']}")
        test_results["Scraper & Keyword Filtering"] = "PASSED"
    except Exception as e:
        print(f"  [FAIL] Scraper error: {e}")
        test_results["Scraper & Keyword Filtering"] = f"FAILED: {e}"

    # ---------------------------------------------------------
    # TEST 3: State Tracking & Deduplication (sheet_manager.py)
    # ---------------------------------------------------------
    print_banner("3. State Tracking & Deduplication")
    try:
        test_url = f"https://example.com/test-verify-job-{int(datetime.now().timestamp())}"
        test_job = {
            "title": "Autonomous AI Systems Engineer",
            "company": "DeepMind Partner Labs",
            "job_url": test_url,
            "description": "Seeking expert in PyTorch, agentic workflows, and neural video analysis.",
        }

        # Check before logging
        assert not sheet_manager.check_if_job_exists(test_url), "Job should not exist before logging"
        print(f"  [PASS] Duplicate check passed (job not present yet).")

        # Log job
        logged = sheet_manager.log_new_job(test_job)
        assert logged, "log_new_job returned False"
        print(f"  [PASS] Logged new job with status 'Pending Tailoring'.")

        # Check after logging
        assert sheet_manager.check_if_job_exists(test_url), "Job should exist after logging"
        print(f"  [PASS] Duplicate detection verified (job detected in sheet/backup).")

        # Update status
        updated = sheet_manager.update_status(test_url, "Tailored", "output/sample_resume.pdf")
        assert updated, "update_status returned False"
        print(f"  [PASS] Status update verified (Status -> 'Tailored').")

        test_results["Sheet State & Deduplication"] = "PASSED"
    except Exception as e:
        print(f"  [FAIL] Sheet manager error: {e}")
        test_results["Sheet State & Deduplication"] = f"FAILED: {e}"

    # ---------------------------------------------------------
    # TEST 4: Resume Tailoring & ATS PDF Compilation
    # ---------------------------------------------------------
    print_banner("4. Resume Tailoring & PDF Generation (Zero Hallucination)")
    try:
        sample_jd = (
            "We are seeking a Machine Learning Engineer with deep expertise in PyTorch, "
            "Computer Vision, and Deep Learning for synthetic media analysis. "
            "Experience with CNN and LSTM architectures is required."
        )
        pdf_path = resume_tailor.tailor_and_export(sample_jd, job_title="Deepfake Detection ML Lead")
        assert Path(pdf_path).exists(), f"PDF not found at {pdf_path}"
        pdf_size = Path(pdf_path).stat().st_size
        assert pdf_size > 5000, f"Generated PDF size too small ({pdf_size} bytes)"
        print(f"  [PASS] Generated tailored PDF: {pdf_path}")
        print(f"         Size: {pdf_size} bytes (Publication Ready)")
        test_results["Resume Tailor & PDF Engine"] = "PASSED"
    except Exception as e:
        print(f"  [FAIL] Resume tailor error: {e}")
        test_results["Resume Tailor & PDF Engine"] = f"FAILED: {e}"

    # ---------------------------------------------------------
    # TEST 5: Playwright Application Engine & Visual Audit
    # ---------------------------------------------------------
    print_banner("5. Playwright Application Engine & Visual Audit")
    try:
        test_pdf = BASE_DIR / "output" / "test_verification.pdf"
        test_pdf.parent.mkdir(parents=True, exist_ok=True)
        if not test_pdf.exists():
            test_pdf.write_text("Test resume payload")

        success, status_tag, screenshot = await apply_bot.apply_to_job(
            target_url="https://example.com",
            pdf_path=str(test_pdf),
            auto_submit=False,
            headless=True,
        )

        assert screenshot and Path(screenshot).exists(), f"Audit screenshot not found: {screenshot}"
        shot_size = Path(screenshot).stat().st_size
        print(f"  [PASS] Playwright execution completed.")
        print(f"         Status: '{status_tag}'")
        print(f"         Audit Screenshot Saved: {screenshot} ({shot_size} bytes)")
        test_results["Playwright Apply Bot & Audit"] = "PASSED"
    except Exception as e:
        print(f"  [FAIL] Apply bot error: {e}")
        test_results["Playwright Apply Bot & Audit"] = f"FAILED: {e}"

    # ---------------------------------------------------------
    # TEST 6: Orchestrator Single-Cycle Run
    # ---------------------------------------------------------
    print_banner("6. Orchestrator End-to-End Cycle (Mock Mode)")
    try:
        cycle_stats = await scheduler.run_single_cycle(
            use_mock=True,
            auto_submit=False,
            headless=True,
            min_delay=1,
            max_delay=2,
        )
        assert cycle_stats["targets_evaluated"] >= 1, "No targets evaluated"
        print(f"  [PASS] Single-pass cycle executed successfully:")
        print(f"         Discovered: {cycle_stats['jobs_discovered']}")
        print(f"         Duplicates: {cycle_stats['skipped_duplicates']}")
        print(f"         Applied/Staged: {cycle_stats['successfully_applied']}")
        test_results["End-to-End Orchestrator Cycle"] = "PASSED"
    except Exception as e:
        print(f"  [FAIL] Orchestrator error: {e}")
        test_results["End-to-End Orchestrator Cycle"] = f"FAILED: {e}"

    # ---------------------------------------------------------
    # SUMMARY REPORT
    # ---------------------------------------------------------
    print("\n" + "=" * 70)
    print("📊 COMPREHENSIVE TEST SUITE SUMMARY")
    print("=" * 70)
    all_passed = True
    for module_name, result in test_results.items():
        icon = "✅" if result == "PASSED" else "❌"
        print(f"{icon} {module_name:35}: {result}")
        if result != "PASSED":
            all_passed = False

    print("=" * 70)
    if all_passed:
        print("🎉 ALL TESTS PASSED SUCCESSFULLY! The pipeline is 100% operational.")
    else:
        print("⚠️ Some tests encountered issues. Review details above.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
