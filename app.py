"""
Module: app.py
Local Web Server & Visual Interactive Control Dashboard for the Job Application Pipeline.
Provides real-time monitoring, visual architecture flow, live streaming console,
job tracking table, target registry editor, master resume editor, and visual audit gallery.

Run with:
  python -m uvicorn app:app --host 127.0.0.1 --port 8000
"""

import os
import sys
import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from collections import deque
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Ensure console supports UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Create required directories
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR = BASE_DIR / "logs" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv()

import sheet_manager
import scheduler
import scraper
import resume_tailor
import apply_bot
import main as pipeline_main

# ---------------------------------------------------------------------------
# In-Memory Real-Time Log Buffer & Broadcaster
# ---------------------------------------------------------------------------
MAX_LOG_BUFFER = 1000
log_buffer: deque = deque(maxlen=MAX_LOG_BUFFER)
log_subscribers: List[asyncio.Queue] = []


class VisualDashboardLogHandler(logging.Handler):
    """Custom logging handler that buffers logs and broadcasts to SSE clients."""

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            log_entry = {
                "id": time.time(),
                "timestamp": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "formatted": msg,
            }
            log_buffer.append(log_entry)

            # Broadcast to any active SSE subscribers
            for queue in list(log_subscribers):
                try:
                    queue.put_nowait(log_entry)
                except Exception:
                    pass
        except Exception:
            self.handleError(record)


# Attach dashboard log handler to root logger
dashboard_handler = VisualDashboardLogHandler()
dashboard_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
)
logging.getLogger().addHandler(dashboard_handler)

logger = logging.getLogger("VisualDashboard")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Pipeline State Management
# ---------------------------------------------------------------------------
SERVER_START_TIME = time.time()

pipeline_state = {
    "status": "idle",  # "idle" | "running" | "daemon"
    "current_step": "System Ready",
    "active_mode": None,
    "last_run_time": None,
    "last_run_result": None,
    "last_error": None,
}

active_task: Optional[asyncio.Task] = None
daemon_task: Optional[asyncio.Task] = None
daemon_stop_event = asyncio.Event()


# ---------------------------------------------------------------------------
# FastAPI Application Setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Autonomous Job Pipeline Visual Dashboard",
    description="End-to-End Visual Orchestrator for Job Discovery, Tailoring, and Submission",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static asset routes
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
app.mount("/logs/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")


# ---------------------------------------------------------------------------
# Pydantic Request Models
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    mode: str = "single"  # "single" | "mock" | "url"
    url: Optional[str] = None
    auto_submit: bool = True
    headless: bool = True
    max_jobs: int = 3
    min_delay: int = 15
    max_delay: int = 45


class DaemonRequest(BaseModel):
    interval_minutes: int = 60
    use_mock: bool = False
    auto_submit: bool = True
    headless: bool = True


class ResumeUpdateRequest(BaseModel):
    content: str


# ---------------------------------------------------------------------------
# Background Task Runners
# ---------------------------------------------------------------------------
async def _execute_pipeline_worker(req: RunRequest):
    """Executes the requested pipeline run in an async worker."""
    global pipeline_state, active_task
    pipeline_state["status"] = "running"
    pipeline_state["active_mode"] = req.mode
    pipeline_state["last_run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pipeline_state["last_error"] = None

    logger.info(">>> Starting Pipeline Run: Mode=%s, Auto-Submit=%s, Headless=%s", req.mode, req.auto_submit, req.headless)

    try:
        if req.mode == "mock":
            pipeline_state["current_step"] = "Executing Mock Pipeline Cycle..."
            summary = await scheduler.run_single_cycle(
                use_mock=True,
                auto_submit=req.auto_submit,
                headless=req.headless,
                min_delay=1,
                max_delay=3,
            )
            pipeline_state["last_run_result"] = summary
        elif req.mode == "url":
            if not req.url:
                raise ValueError("Direct URL mode requires a valid 'url' parameter.")
            pipeline_state["current_step"] = f"Processing Direct Target: {req.url}..."
            await pipeline_main.run_single_url_pipeline(
                target_url=req.url,
                max_jobs=req.max_jobs,
                auto_submit=req.auto_submit,
                headless=req.headless,
                min_delay=req.min_delay,
                max_delay=req.max_delay,
            )
            pipeline_state["last_run_result"] = {"mode": "url", "target": req.url, "status": "completed"}
        else:
            # "single" pass across targets.json
            pipeline_state["current_step"] = "Executing Single Pass across Career Targets..."
            summary = await scheduler.run_single_cycle(
                use_mock=False,
                auto_submit=req.auto_submit,
                headless=req.headless,
                min_delay=req.min_delay,
                max_delay=req.max_delay,
            )
            pipeline_state["last_run_result"] = summary

        logger.info("<<< Pipeline Run Completed Successfully.")
        pipeline_state["current_step"] = "Execution Finished (Idle)"
    except asyncio.CancelledError:
        logger.warning("[ABORT] Pipeline execution was cancelled by user.")
        pipeline_state["current_step"] = "Execution Cancelled"
        pipeline_state["last_error"] = "Cancelled by user"
    except Exception as e:
        logger.error("[ERROR] Pipeline execution failed: %s", e, exc_info=True)
        pipeline_state["current_step"] = f"Failed: {str(e)[:80]}"
        pipeline_state["last_error"] = str(e)
    finally:
        pipeline_state["status"] = "idle"
        active_task = None


async def _execute_daemon_worker(req: DaemonRequest):
    """Executes continuous scheduling daemon loop."""
    global pipeline_state, daemon_task
    pipeline_state["status"] = "daemon"
    pipeline_state["active_mode"] = "daemon"
    pipeline_state["current_step"] = f"Daemon Active (Interval: {req.interval_minutes}m)"
    logger.info(">>> Background Scheduler Daemon started with %d min interval", req.interval_minutes)

    cycle_count = 0
    try:
        while not daemon_stop_event.is_set():
            cycle_count += 1
            pipeline_state["last_run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pipeline_state["current_step"] = f"Daemon Cycle #{cycle_count} running..."
            logger.info("=== Daemon Scheduled Cycle #%d Started ===", cycle_count)

            try:
                await scheduler.run_single_cycle(
                    use_mock=req.use_mock,
                    auto_submit=req.auto_submit,
                    headless=req.headless,
                    min_delay=10 if req.use_mock else 30,
                    max_delay=20 if req.use_mock else 90,
                )
            except Exception as e:
                logger.error("Daemon cycle #%d encountered error: %s", cycle_count, e)

            pipeline_state["current_step"] = f"Daemon Sleeping until next cycle (Cycle #{cycle_count} done)"
            logger.info("Daemon cycle #%d completed. Sleeping for %d minutes...", cycle_count, req.interval_minutes)

            # Sleep in 1-second slices so stop requests are handled immediately
            sleep_duration = req.interval_minutes * 60
            for _ in range(sleep_duration):
                if daemon_stop_event.is_set():
                    break
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("[DAEMON] Scheduler loop cancelled.")
    finally:
        pipeline_state["status"] = "idle"
        pipeline_state["current_step"] = "Daemon Stopped"
        daemon_task = None
        logger.info("<<< Background Scheduler Daemon stopped.")


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the primary visual dashboard single-page interface."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse(
            "<html><body><h2>Dashboard frontend is initializing... Please refresh shortly.</h2></body></html>"
        )
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/status")
async def get_system_status():
    """Returns real-time pipeline status, candidate profile, and environment health."""
    # Count targets
    targets_cfg = scheduler.load_targets_config()
    targets_list = targets_cfg.get("targets", [])
    active_targets = sum(1 for t in targets_list if t.get("enabled", True))

    # Fetch jobs statistics
    all_jobs = sheet_manager.get_all_jobs()
    stats = {
        "total": len(all_jobs),
        "applied": 0,
        "tailored": 0,
        "pending": 0,
        "failed": 0,
        "skipped": 0,
    }
    for j in all_jobs:
        status_str = (j.get("Application Status") or j.get("status") or "").lower()
        if "applied" in status_str:
            stats["applied"] += 1
        elif "tailored" in status_str:
            stats["tailored"] += 1
        elif "pending" in status_str:
            stats["pending"] += 1
        elif "failed" in status_str or "manual" in status_str:
            stats["failed"] += 1
        elif "skipped" in status_str:
            stats["skipped"] += 1

    # Check environment configuration
    env_health = {
        "gemini_api_key": bool(os.getenv("GEMINI_API_KEY")),
        "openai_api_key": bool(os.getenv("OPENAI_API_KEY")),
        "google_sheet_configured": os.getenv("GOOGLE_SHEET_ID", "") not in ("", "your_google_sheet_id_here"),
        "service_account_exists": (BASE_DIR / os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json")).exists(),
        "auto_submit_enabled": os.getenv("AUTO_SUBMIT", "true").lower() in ("true", "1", "yes"),
    }

    # Count screenshots & PDFs
    screenshot_count = len(list(SCREENSHOTS_DIR.glob("*.png")))
    pdf_count = len(list(OUTPUT_DIR.glob("*.pdf")))

    return {
        "pipeline": {
            "status": pipeline_state["status"],
            "current_step": pipeline_state["current_step"],
            "active_mode": pipeline_state["active_mode"],
            "last_run_time": pipeline_state["last_run_time"],
            "last_error": pipeline_state["last_error"],
            "uptime_seconds": int(time.time() - SERVER_START_TIME),
        },
        "candidate": {
            "name": apply_bot.DEFAULT_APPLICANT.get("full_name", "Alex Rivera"),
            "role": "Senior Quantitative Systems & Machine Learning Engineer",
            "email": apply_bot.DEFAULT_APPLICANT.get("email", "alex.rivera.dev@example.com"),
            "location": apply_bot.DEFAULT_APPLICANT.get("location", "San Francisco, CA"),
        },
        "stats": stats,
        "counts": {
            "targets_total": len(targets_list),
            "targets_active": active_targets,
            "pdfs_generated": pdf_count,
            "screenshots_captured": screenshot_count,
        },
        "environment": env_health,
    }


@app.get("/api/jobs")
async def get_jobs_list():
    """Returns the list of all tracked jobs with associated PDF & screenshot links."""
    records = sheet_manager.get_all_jobs()
    all_screenshots = {f.stem: f.name for f in SCREENSHOTS_DIR.glob("*.png")}

    formatted_jobs = []
    for r in records:
        # Standardize keys from either Google Sheet format or local fallback
        title = r.get("Job Title") or r.get("title") or "Untitled Role"
        company = r.get("Company") or r.get("company") or "Unknown"
        url = r.get("Job URL") or r.get("job_url") or ""
        date_found = r.get("Date Found") or r.get("date") or ""
        status = r.get("Application Status") or r.get("status") or "Unknown"
        desc = r.get("Job Description (Context)") or r.get("description") or ""
        raw_pdf_path = r.get("Tailored Resume Path") or r.get("resume_path") or ""

        # Normalize PDF link
        pdf_filename = None
        if raw_pdf_path:
            p = Path(raw_pdf_path)
            if p.name and (OUTPUT_DIR / p.name).exists():
                pdf_filename = p.name

        # Check for matching screenshot
        screenshot_filename = None
        slug = apply_bot._make_job_slug(url or f"{company}_{title}")
        for stem, fname in all_screenshots.items():
            if slug in stem or stem in slug:
                screenshot_filename = fname
                break

        formatted_jobs.append({
            "title": title,
            "company": company,
            "job_url": url,
            "date_found": date_found,
            "status": status,
            "description": desc,
            "pdf_filename": pdf_filename,
            "pdf_url": f"/output/{pdf_filename}" if pdf_filename else None,
            "screenshot_filename": screenshot_filename,
            "screenshot_url": f"/logs/screenshots/{screenshot_filename}" if screenshot_filename else None,
        })

    # Return reverse chronological (newest first)
    return {"jobs": list(reversed(formatted_jobs))}


@app.get("/api/targets")
async def get_targets_config():
    """Returns targets configuration from targets.json."""
    return scheduler.load_targets_config()


@app.post("/api/targets")
async def save_targets_config(request: Request):
    """Saves updated targets configuration to targets.json."""
    try:
        data = await request.json()
        if "targets" not in data or "settings" not in data:
            raise HTTPException(status_code=400, detail="Invalid targets config structure.")

        with open(scheduler.TARGETS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info("[CONFIG] Updated targets.json with %d targets", len(data.get("targets", [])))
        return {"status": "success", "message": "Targets configuration updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/resume")
async def get_master_resume():
    """Returns master_resume.md text content."""
    content = resume_tailor.load_master_resume()
    return {"content": content}


@app.post("/api/resume")
async def save_master_resume(req: ResumeUpdateRequest):
    """Saves updated master resume markdown to master_resume.md."""
    try:
        resume_path = BASE_DIR / "master_resume.md"
        with open(resume_path, "w", encoding="utf-8") as f:
            f.write(req.content.strip())
        logger.info("[RESUME] Master resume updated (%d characters)", len(req.content))
        return {"status": "success", "message": "Master resume updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/run")
async def trigger_run(req: RunRequest):
    """Triggers an asynchronous pipeline execution."""
    global active_task
    if pipeline_state["status"] != "idle":
        return JSONResponse(
            status_code=409,
            content={"status": "conflict", "message": f"Pipeline is currently {pipeline_state['status']}."},
        )

    active_task = asyncio.create_task(_execute_pipeline_worker(req))
    return {
        "status": "started",
        "mode": req.mode,
        "message": f"Pipeline execution started in {req.mode} mode.",
    }


@app.post("/api/stop")
async def stop_pipeline():
    """Cancels active single-run pipeline execution."""
    global active_task
    if active_task and not active_task.done():
        active_task.cancel()
        return {"status": "cancelled", "message": "Pipeline run cancellation requested."}
    return {"status": "idle", "message": "No active pipeline run to stop."}


@app.post("/api/daemon/start")
async def start_daemon(req: DaemonRequest):
    """Starts the continuous background scheduler daemon."""
    global daemon_task, daemon_stop_event
    if pipeline_state["status"] == "daemon":
        return {"status": "already_running", "message": "Daemon is already running."}
    if pipeline_state["status"] == "running":
        return JSONResponse(
            status_code=409,
            content={"status": "conflict", "message": "A pipeline run is currently in progress."},
        )

    daemon_stop_event.clear()
    daemon_task = asyncio.create_task(_execute_daemon_worker(req))
    return {
        "status": "started",
        "interval_minutes": req.interval_minutes,
        "message": f"Scheduler daemon started (Interval: {req.interval_minutes}m).",
    }


@app.post("/api/daemon/stop")
async def stop_daemon():
    """Stops the continuous background scheduler daemon."""
    global daemon_task, daemon_stop_event
    if daemon_task and not daemon_task.done():
        daemon_stop_event.set()
        daemon_task.cancel()
        pipeline_state["status"] = "idle"
        pipeline_state["current_step"] = "Daemon Stopped"
        return {"status": "stopped", "message": "Scheduler daemon stopped."}
    return {"status": "idle", "message": "Daemon was not running."}


@app.get("/api/logs/history")
async def get_logs_history():
    """Returns buffered recent log records."""
    return {"logs": list(log_buffer)}


@app.get("/api/logs/stream")
async def stream_logs(request: Request):
    """Server-Sent Events (SSE) stream for real-time console logs."""

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        log_subscribers.append(queue)
        try:
            # First send recent history so console is instantly populated
            for entry in list(log_buffer)[-40:]:
                yield f"data: {json.dumps(entry)}\n\n"

            while True:
                # Disconnect check
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(entry)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat
                    yield ": ping\n\n"
        finally:
            if queue in log_subscribers:
                log_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/screenshots")
async def get_screenshots_gallery():
    """Returns list of all audit screenshots captured by apply_bot."""
    screenshots = []
    for file_path in sorted(SCREENSHOTS_DIR.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True):
        stat = file_path.stat()
        screenshots.append({
            "filename": file_path.name,
            "url": f"/logs/screenshots/{file_path.name}",
            "size_kb": round(stat.st_size / 1024, 1),
            "timestamp": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return {"screenshots": screenshots}


if __name__ == "__main__":
    import uvicorn

    print("=" * 80)
    print("Launching Autonomous Job Pipeline Visual Dashboard")
    print("Confined strictly to:", BASE_DIR)
    print("Dashboard URL: http://127.0.0.1:8000")
    print("=" * 80)
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
