"""
Module: main.py
Master Orchestrator & CLI Runner for the Unattended Job Pipeline.

Modes:
  --daemon     : Runs continuously in the background, executing scheduled scans
                 and applications based on targets.json intervals.
  --run-once   : Performs an immediate single-pass execution across all enabled targets.
  --url <URL>  : Targets a specific job board or posting directly.
  --mock       : Uses verified mock positions for rapid testing and dry-runs.
  --auto-submit: Triggers live form submission (default uses AUTO_SUBMIT from .env).

Confined strictly to the workspace:
c:/Users/Light/Documents/antigravity/lively-carson
"""

import sys
import os
import argparse
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

# Ensure console supports UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure local imports are resolved from the current directory
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import scraper
import sheet_manager
import resume_tailor
import apply_bot
import scheduler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PipelineOrchestrator")


async def run_single_url_pipeline(
    target_url: str,
    max_jobs: int = 3,
    auto_submit: bool = True,
    headless: bool = True,
    min_delay: int = 15,
    max_delay: int = 45,
):
    """Executes the pipeline directly against a single target URL."""
    print("=" * 80)
    print(f"[START] DIRECT TARGET PIPELINE: {target_url}")
    print(f"Auto-Submit : {'ENABLED' if auto_submit else 'DISABLED (Dry Run)'}")
    print(f"Candidate   : Alex Rivera (Quantitative & ML Systems Engineer)")
    print("=" * 80)

    jobs = await scraper.scrape_jobs(target_url, max_jobs=max_jobs, headless=headless)
    if not jobs:
        logger.warning("No jobs were extracted from %s.", target_url)
        return

    logger.info("Found %d jobs. Processing each position...", len(jobs))
    for job in jobs:
        await scheduler.process_job_pipeline(
            job=job,
            auto_submit=auto_submit,
            headless=headless,
            min_delay=min_delay,
            max_delay=max_delay,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Automated Unattended Job Discovery, Tailoring & Application Pipeline"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously in background mode, cycling through targets on a schedule",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run a single complete pass across all targets in targets.json and exit",
    )
    parser.add_argument(
        "--url",
        type=str,
        default="",
        help="Target a specific job board or job URL directly instead of targets.json",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run using mock job data to verify discovery, tailoring, and submission offline",
    )
    parser.add_argument(
        "--auto-submit",
        action="store_true",
        default=None,
        help="Force automatic clicking of the submit button (overrides AUTO_SUBMIT in .env)",
    )
    parser.add_argument(
        "--no-auto-submit",
        action="store_true",
        help="Force safe dry-run mode (disables final submit button click)",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=5,
        help="Maximum jobs to process per target",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Scrape cycle interval in minutes (daemon mode only)",
    )
    parser.add_argument(
        "--min-delay",
        type=int,
        default=None,
        help="Minimum anti-bot delay between applications in seconds",
    )
    parser.add_argument(
        "--max-delay",
        type=int,
        default=None,
        help="Maximum anti-bot delay between applications in seconds",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Launch a visible browser window instead of headless mode",
    )

    args = parser.parse_args()

    # Determine auto-submit setting
    if args.no_auto_submit:
        auto_submit_flag = False
    elif args.auto_submit is not None:
        auto_submit_flag = args.auto_submit
    else:
        auto_submit_flag = os.getenv("AUTO_SUBMIT", "true").lower() in ("true", "1", "yes")

    headless_flag = not args.no_headless

    # Route execution based on flags
    if args.daemon:
        logger.info("Initializing unattended background daemon...")
        asyncio.run(
            scheduler.start_daemon(
                interval_minutes=args.interval,
                use_mock=args.mock,
                auto_submit=auto_submit_flag,
                headless=headless_flag,
                min_delay=args.min_delay,
                max_delay=args.max_delay,
            )
        )
    elif args.url:
        logger.info("Running direct URL target pass for %s...", args.url)
        min_del = args.min_delay if args.min_delay is not None else 10
        max_del = args.max_delay if args.max_delay is not None else 25
        asyncio.run(
            run_single_url_pipeline(
                target_url=args.url,
                max_jobs=args.max_jobs,
                auto_submit=auto_submit_flag,
                headless=headless_flag,
                min_delay=min_del,
                max_delay=max_del,
            )
        )
    else:
        # Default or --run-once mode: execute single cycle across targets
        logger.info("Running single-pass pipeline cycle...")
        min_del = args.min_delay if args.min_delay is not None else (1 if args.mock else 15)
        max_del = args.max_delay if args.max_delay is not None else (3 if args.mock else 30)

        asyncio.run(
            scheduler.run_single_cycle(
                use_mock=args.mock,
                auto_submit=auto_submit_flag,
                headless=headless_flag,
                min_delay=min_del,
                max_delay=max_del,
            )
        )


if __name__ == "__main__":
    main()
