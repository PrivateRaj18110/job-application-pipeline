"""
Module: scheduler.py
Unattended Background Automation Runner & Job Scheduler.

Manages automated scraping, deduplication, LLM-based zero-hallucination tailoring,
automated submission with anti-bot mitigations, Google Sheet state logging,
and randomized rate-limiting pacing intervals.

Operates strictly within the local workspace directory:
c:/Users/Light/Documents/antigravity/lively-carson
"""

import sys
import os
import json
import random
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

# Set UTF-8 encoding for Windows console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure local imports work reliably
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import scraper
import sheet_manager
import resume_tailor
import apply_bot

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Scheduler")

TARGETS_FILE = BASE_DIR / "targets.json"


def load_targets_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Reads target configuration from targets.json."""
    path = config_path or TARGETS_FILE
    if not path.exists():
        logger.warning("Targets file not found at %s. Creating default template.", path)
        default_config = {
            "settings": {
                "default_scrape_interval_minutes": 60,
                "min_delay_between_applications_seconds": 30,
                "max_delay_between_applications_seconds": 90,
                "max_jobs_per_target": 5,
            },
            "targets": [
                {
                    "name": "Synthetic Mock Board",
                    "type": "mock",
                    "url": "https://example.com/careers/mock",
                    "enabled": True,
                    "role_keywords": ["Python", "Machine Learning", "Vision", "Flutter"],
                }
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2)
        return default_config

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def process_job_pipeline(
    job: Dict[str, str],
    auto_submit: bool = True,
    headless: bool = True,
    min_delay: int = 30,
    max_delay: int = 90,
) -> Dict[str, Any]:
    """
    Executes the full pipeline for an individual job:
    Deduplicate -> Log -> Tailor Resume -> Auto-Submit -> Log Final Status -> Pacing Delay.
    """
    title = job.get("title", "Untitled Role")
    company = job.get("company", "Unknown Employer")
    job_url = job.get("job_url", "")
    description = job.get("description", "")

    result = {
        "job_url": job_url,
        "title": title,
        "company": company,
        "status": "Skipped",
        "pdf_path": "",
        "screenshot_path": "",
    }

    print("\n" + "-" * 75)
    logger.info("Evaluating: '%s' at '%s'", title, company)
    logger.info("URL: %s", job_url)

    # 1. State Check & Deduplication
    if sheet_manager.check_if_job_exists(job_url):
        logger.info("[SKIP] Duplicate job already registered in Google Sheets: %s", job_url)
        result["status"] = "Skipped - Duplicate"
        return result

    # 2. Log Initial State in Google Sheets
    logger.info("[LOG] Logging new job entry into Google Sheet with status 'Pending Tailoring'")
    sheet_manager.log_new_job(job)

    # 3. LLM Resume Tailoring (Zero Hallucinations)
    logger.info("[LLM] Generating role-tailored resume (Zero Hallucination protocol)...")
    try:
        sanitized_role = f"{company}_{title}"
        pdf_path = resume_tailor.tailor_and_export(description, job_title=sanitized_role)
        result["pdf_path"] = pdf_path
        logger.info("[PDF] Tailored PDF resume compiled: %s", pdf_path)
        sheet_manager.update_status(job_url, "Tailored", resume_path=pdf_path)
    except Exception as e:
        logger.error("Resume tailoring failed for %s: %s", job_url, e)
        err_status = f"Failed - Needs Manual Check ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
        sheet_manager.update_status(job_url, err_status)
        result["status"] = "Failed - Needs Manual Check"
        return result

    # 4. Automated Submission Engine
    logger.info("[APPLY] Executing Playwright apply_bot (Auto-Submit=%s)...", auto_submit)
    success, status_tag, screenshot_path = await apply_bot.apply_to_job(
        target_url=job_url,
        pdf_path=pdf_path,
        auto_submit=auto_submit,
        headless=headless,
    )
    result["screenshot_path"] = screenshot_path

    # 5. Format Timestamped Status
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    final_status = f"{status_tag} ({timestamp})"
    logger.info("[RESULT] Application process concluded: %s", final_status)
    if screenshot_path:
        logger.info("[AUDIT] Visual screenshot saved: %s", screenshot_path)

    sheet_manager.update_status(job_url, final_status, resume_path=pdf_path)
    result["status"] = status_tag

    # 6. Anti-Bot Mitigation: Randomized Pacing Delay
    if min_delay > 0:
        pacing_seconds = random.randint(min_delay, max(min_delay, max_delay))
        logger.info("[PACING] Anti-bot delay: sleeping %d seconds before proceeding...", pacing_seconds)
        await asyncio.sleep(pacing_seconds)

    return result


async def run_single_cycle(
    use_mock: bool = False,
    auto_submit: bool = True,
    headless: bool = True,
    min_delay: Optional[int] = None,
    max_delay: Optional[int] = None,
) -> Dict[str, int]:
    """
    Executes a single end-to-end cycle across all configured target job boards.
    """
    config = load_targets_config()
    settings = config.get("settings", {})
    targets = config.get("targets", [])

    delay_min = min_delay if min_delay is not None else settings.get("min_delay_between_applications_seconds", 30)
    delay_max = max_delay if max_delay is not None else settings.get("max_delay_between_applications_seconds", 90)
    max_jobs_per_target = settings.get("max_jobs_per_target", 5)

    stats = {
        "targets_evaluated": 0,
        "jobs_discovered": 0,
        "skipped_duplicates": 0,
        "successfully_applied": 0,
        "blocked_or_failed": 0,
    }

    print("=" * 80)
    print("[CYCLE START] UNATTENDED PIPELINE EXECUTION CYCLE")
    print(f"Timestamp    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Auto-Submit  : {'ENABLED' if auto_submit else 'DISABLED (Dry Run)'}")
    print(f"Pacing Delay : {delay_min}s to {delay_max}s")
    print("=" * 80)

    if use_mock:
        logger.info("Executing cycle in MOCK / TEST mode.")
        mock_jobs = scraper.get_mock_jobs()
        stats["targets_evaluated"] = 1
        stats["jobs_discovered"] = len(mock_jobs)

        for job in mock_jobs:
            res = await process_job_pipeline(
                job,
                auto_submit=auto_submit,
                headless=headless,
                min_delay=delay_min,
                max_delay=delay_max,
            )
            st = res.get("status", "")
            if "Skipped" in st:
                stats["skipped_duplicates"] += 1
            elif "Applied" in st or "Staged" in st:
                stats["successfully_applied"] += 1
            else:
                stats["blocked_or_failed"] += 1

        _print_cycle_summary(stats)
        return stats

    # Live Mode: Cycle through active targets in targets.json
    for target in targets:
        if not target.get("enabled", True):
            continue

        target_name = target.get("name", "Target Board")
        target_url = target.get("url", "")
        keywords = target.get("role_keywords", [])
        target_type = target.get("type", "generic")

        logger.info("\n>>> Scanning Target: %s (%s) [Keywords: %s]", target_name, target_url, keywords)
        stats["targets_evaluated"] += 1

        if target_type == "mock":
            jobs = scraper.get_mock_jobs(role_keywords=keywords)
        else:
            jobs = await scraper.scrape_jobs(
                target_url=target_url,
                max_jobs=max_jobs_per_target,
                role_keywords=keywords,
                headless=headless,
            )

        stats["jobs_discovered"] += len(jobs)
        logger.info("Discovered %d matching positions for %s", len(jobs), target_name)

        for job in jobs:
            res = await process_job_pipeline(
                job,
                auto_submit=auto_submit,
                headless=headless,
                min_delay=delay_min,
                max_delay=delay_max,
            )
            st = res.get("status", "")
            if "Skipped" in st:
                stats["skipped_duplicates"] += 1
            elif "Applied" in st or "Staged" in st:
                stats["successfully_applied"] += 1
            else:
                stats["blocked_or_failed"] += 1

    _print_cycle_summary(stats)
    return stats


def _print_cycle_summary(stats: Dict[str, int]):
    print("\n" + "=" * 80)
    print("[CYCLE SUMMARY] EXECUTION STATS")
    print(f"Targets Scanned     : {stats['targets_evaluated']}")
    print(f"Jobs Discovered     : {stats['jobs_discovered']}")
    print(f"Duplicates Skipped  : {stats['skipped_duplicates']}")
    print(f"Successfully Applied: {stats['successfully_applied']}")
    print(f"Blocked / Needs Rev : {stats['blocked_or_failed']}")
    print("=" * 80)


async def start_daemon(
    interval_minutes: Optional[int] = None,
    use_mock: bool = False,
    auto_submit: bool = True,
    headless: bool = True,
    min_delay: Optional[int] = None,
    max_delay: Optional[int] = None,
):
    """
    Runs the automated pipeline continuously as an unattended background service.
    Repeats cycles on a scheduled interval.
    """
    config = load_targets_config()
    settings = config.get("settings", {})
    interval = interval_minutes or settings.get("default_scrape_interval_minutes", 60)

    logger.info("Starting Unattended Pipeline Daemon (Interval: every %d minutes)...", interval)
    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            logger.info("=== Starting Scheduled Pipeline Cycle #%d ===", cycle_count)
            start_time = datetime.now()

            await run_single_cycle(
                use_mock=use_mock,
                auto_submit=auto_submit,
                headless=headless,
                min_delay=min_delay,
                max_delay=max_delay,
            )

            sleep_duration = interval * 60
            next_run = datetime.now().timestamp() + sleep_duration
            next_run_str = datetime.fromtimestamp(next_run).strftime("%Y-%m-%d %H:%M:%S")
            logger.info("Cycle #%d finished. Sleeping for %d minutes. Next scheduled cycle at %s.", cycle_count, interval, next_run_str)
            await asyncio.sleep(sleep_duration)

    except asyncio.CancelledError:
        logger.info("Daemon received cancellation. Shutting down gracefully.")
    except KeyboardInterrupt:
        logger.info("Daemon terminated by user interrupt.")


if __name__ == "__main__":
    # Test single-cycle run
    asyncio.run(run_single_cycle(use_mock=True, auto_submit=False, min_delay=1, max_delay=2))
