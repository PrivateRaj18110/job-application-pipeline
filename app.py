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
import csv
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
from starlette.middleware.trustedhost import TrustedHostMiddleware
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
import portfolio_builder
import cold_emailer
import tracker

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

outreach_state = {
    "status": "idle",  # "idle" | "running" | "daemon"
    "current_step": "Outreach Ready",
    "last_run_time": None,
    "last_run_result": None,
    "last_error": None,
}

outreach_task: Optional[asyncio.Task] = None
outreach_stop_event = asyncio.Event()


# ---------------------------------------------------------------------------
# FastAPI Application Setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Autonomous Job Pipeline Visual Dashboard",
    description="End-to-End Visual Orchestrator for Job Discovery, Tailoring, and Submission",
    version="2.0.0",
)

# The dashboard holds private data (contacts, emails, the tracker). Only the dashboard's own pages may
# call the API: a wildcard origin would let any website open in the browser read it from localhost.
LOCAL_ORIGINS = ["http://127.0.0.1:8000", "http://localhost:8000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Rejects requests whose Host is not this machine (blocks DNS-rebinding attacks on the local server)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

# Mount static asset routes
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
app.mount("/logs/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")
portfolio_builder.PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/portfolio", StaticFiles(directory=str(portfolio_builder.PORTFOLIO_DIR), html=True), name="portfolio")


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


class CvUpdateRequest(BaseModel):
    cv: Dict[str, Any]


class ContactRequest(BaseModel):
    name: str = ""
    email: str
    company: str = ""
    role: str = ""
    job_url: str = ""
    notes: str = ""


class ContactUpdateRequest(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    job_url: Optional[str] = None
    notes: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    status: Optional[str] = None


class CsvImportRequest(BaseModel):
    csv_text: str


class OutreachRunRequest(BaseModel):
    auto_send: bool = False


class OutreachDaemonRequest(BaseModel):
    interval_minutes: int = 60
    auto_send: bool = True


class CopilotQuestion(BaseModel):
    question: str


class TrackerUpdate(BaseModel):
    stage: Optional[str] = None
    notes: Optional[str] = None


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


def _set_outreach_step(text: str):
    outreach_state["current_step"] = text


async def _execute_outreach_worker(auto_send: bool):
    """Runs a single cold outreach cycle (draft, then send if auto_send)."""
    global outreach_task
    outreach_state.update(status="running", last_error=None,
                          last_run_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        summary = await cold_emailer.run_outreach_cycle(
            auto_send=auto_send, stop_event=outreach_stop_event, on_step=_set_outreach_step
        )
        outreach_state["last_run_result"] = summary
        outreach_state["current_step"] = "Outreach Cycle Finished (Idle)"
    except asyncio.CancelledError:
        outreach_state["current_step"] = "Outreach Cancelled"
        outreach_state["last_error"] = "Cancelled by user"
    except Exception as e:
        logger.error("[EMAIL] Outreach cycle failed: %s", e, exc_info=True)
        outreach_state["current_step"] = f"Failed: {str(e)[:80]}"
        outreach_state["last_error"] = str(e)
    finally:
        outreach_state["status"] = "idle"
        outreach_task = None


async def _execute_outreach_daemon_worker(req: OutreachDaemonRequest):
    """Runs outreach cycles on an interval until stopped."""
    global outreach_task
    outreach_state.update(status="daemon", current_step=f"Outreach Daemon Active (Interval: {req.interval_minutes}m)",
                          last_run_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info(">>> Outreach daemon started (interval %d min, auto-send %s)", req.interval_minutes, req.auto_send)
    try:
        await cold_emailer.run_daemon(
            interval_minutes=req.interval_minutes, auto_send=req.auto_send,
            stop_event=outreach_stop_event, on_step=_set_outreach_step,
        )
    except asyncio.CancelledError:
        pass
    finally:
        outreach_state["status"] = "idle"
        outreach_state["current_step"] = "Outreach Daemon Stopped"
        outreach_task = None
        logger.info("<<< Outreach daemon stopped.")


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
        "smtp_configured": cold_emailer.smtp_configured(),
    }

    try:
        profile = portfolio_builder.load_cv().get("profile", {})
    except Exception:
        profile = {}

    try:
        outreach_stats = cold_emailer.get_stats()
    except ValueError:
        outreach_stats = {}

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
            "name": profile.get("name") or apply_bot.DEFAULT_APPLICANT.get("full_name", "Alex Rivera"),
            "role": profile.get("title") or "Senior Quantitative Systems & Machine Learning Engineer",
            "email": profile.get("email") or apply_bot.DEFAULT_APPLICANT.get("email", "alex.rivera.dev@example.com"),
            "location": profile.get("location") or apply_bot.DEFAULT_APPLICANT.get("location", "San Francisco, CA"),
        },
        "outreach": dict(outreach_state, stats=outreach_stats),
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


# ---------------------------------------------------------------------------
# Portfolio & Structured CV Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/cv")
async def get_cv():
    """Returns cv.json plus the portfolio build state."""
    try:
        cv = portfolio_builder.load_cv()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="cv.json not found.")
    built_at = None
    if portfolio_builder.PORTFOLIO_CV_FILE.exists():
        try:
            with open(portfolio_builder.PORTFOLIO_CV_FILE, "r", encoding="utf-8") as f:
                built_at = json.load(f).get("generated_at")
        except Exception:
            pass
    return {
        "cv": cv,
        "built_at": built_at,
        "pdf_url": "/portfolio/resume.pdf" if portfolio_builder.PORTFOLIO_PDF_FILE.exists() else None,
    }


@app.post("/api/cv")
async def save_cv(req: CvUpdateRequest):
    """Validates and saves cv.json, then rebuilds the portfolio site and CV PDF."""
    try:
        portfolio_builder.save_cv(req.cv)
        result = await asyncio.to_thread(portfolio_builder.build_portfolio, req.cv)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "message": "CV saved and portfolio rebuilt.", **result}


@app.post("/api/portfolio/build")
async def build_portfolio_site():
    """Rebuilds the portfolio site and CV PDF from the saved cv.json."""
    try:
        result = await asyncio.to_thread(portfolio_builder.build_portfolio)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "message": "Portfolio rebuilt.", **result}


@app.post("/api/cv/sync-master")
async def sync_master_resume_from_cv():
    """Regenerates master_resume.md (the tailoring ground truth) from cv.json."""
    try:
        path = await asyncio.to_thread(portfolio_builder.sync_master_resume)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "message": "master_resume.md regenerated from cv.json.", "path": path}


# ---------------------------------------------------------------------------
# Cold Outreach Endpoints
# ---------------------------------------------------------------------------
def _contact_or_404(contact_id: str) -> Dict[str, Any]:
    try:
        return cold_emailer.get_contact(contact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Contact not found.")


@app.get("/api/contacts")
async def list_contacts():
    """Returns all outreach contacts (newest first) with stats and the current email settings."""
    try:
        contacts = cold_emailer.load_contacts()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "contacts": list(reversed(contacts)),
        "stats": cold_emailer.get_stats(contacts),
        "statuses": cold_emailer.STATUSES,
        "settings": cold_emailer.public_settings(),
        "opt_out_line": cold_emailer.OPT_OUT_LINE,
    }


@app.post("/api/contacts")
async def create_contact(req: ContactRequest):
    try:
        contact = cold_emailer.add_contact(req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "contact": contact}


@app.post("/api/contacts/import")
async def import_contacts(req: CsvImportRequest):
    try:
        result = cold_emailer.import_contacts_csv(req.csv_text)
    except (ValueError, csv.Error) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", **result}


@app.put("/api/contacts/{contact_id}")
async def edit_contact(contact_id: str, req: ContactUpdateRequest):
    _contact_or_404(contact_id)
    try:
        contact = cold_emailer.update_contact(contact_id, req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "contact": contact}


@app.delete("/api/contacts/{contact_id}")
async def remove_contact(contact_id: str):
    _contact_or_404(contact_id)
    cold_emailer.delete_contact(contact_id)
    return {"status": "success", "message": "Contact deleted."}


@app.post("/api/contacts/{contact_id}/draft")
async def draft_contact_email(contact_id: str):
    """Generates (or regenerates) the first email for one contact."""
    _contact_or_404(contact_id)
    try:
        contact = await asyncio.to_thread(cold_emailer.draft_contact, contact_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "success", "contact": contact}


@app.post("/api/contacts/{contact_id}/send")
async def send_contact_now(contact_id: str):
    """Sends the current draft to one contact now (writes a preview instead when in dry-run mode)."""
    _contact_or_404(contact_id)
    result = await asyncio.to_thread(cold_emailer.send_contact_email, contact_id, "initial")
    if result["status"] in ("failed", "skipped"):
        return JSONResponse(status_code=400, content={"status": result["status"], "detail": result["detail"]})
    return {"status": result["status"], "message": result["detail"], "contact": result["contact"]}


@app.post("/api/outreach/run")
async def trigger_outreach_run(req: OutreachRunRequest):
    """Runs one outreach cycle in the background."""
    global outreach_task
    if outreach_state["status"] != "idle":
        return JSONResponse(status_code=409, content={"status": "conflict", "message": f"Outreach is currently {outreach_state['status']}."})
    outreach_stop_event.clear()
    outreach_task = asyncio.create_task(_execute_outreach_worker(req.auto_send))
    return {"status": "started", "message": f"Outreach cycle started (auto-send {'on' if req.auto_send else 'off'})."}


@app.post("/api/outreach/daemon/start")
async def start_outreach_daemon(req: OutreachDaemonRequest):
    global outreach_task
    if outreach_state["status"] != "idle":
        return JSONResponse(status_code=409, content={"status": "conflict", "message": f"Outreach is currently {outreach_state['status']}."})
    outreach_stop_event.clear()
    outreach_task = asyncio.create_task(_execute_outreach_daemon_worker(req))
    return {"status": "started", "message": f"Outreach daemon started (every {req.interval_minutes}m)."}


@app.post("/api/outreach/stop")
async def stop_outreach():
    """Stops a running outreach cycle or daemon."""
    if outreach_task and not outreach_task.done():
        outreach_stop_event.set()
        outreach_task.cancel()
        return {"status": "stopped", "message": "Outreach stopped."}
    return {"status": "idle", "message": "Outreach was not running."}


# ---------------------------------------------------------------------------
# Company Tracker (private: applications + emails + your stages, per company)
# ---------------------------------------------------------------------------
@app.get("/api/tracker")
async def get_tracker():
    return await asyncio.to_thread(tracker.build_overview)


@app.put("/api/tracker/{company_key}")
async def update_tracker(company_key: str, req: TrackerUpdate):
    try:
        return tracker.update_company(company_key, stage=req.stage, notes=req.notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Research Copilot (RAG over project docs with a local open-source LLM)
# ---------------------------------------------------------------------------
_copilot = None


def _get_copilot():
    """Loads the index once; rebuilt indexes are picked up after a server restart."""
    global _copilot
    if _copilot is None:
        from research_copilot.pipeline import Copilot
        _copilot = Copilot()
    return _copilot


@app.get("/api/copilot/status")
async def copilot_status():
    from research_copilot.config import INDEX_DIR, Settings
    from research_copilot.llm import Ollama, OllamaError

    settings = Settings()
    status = {"chat_model": settings.chat_model, "embed_model": settings.embed_model,
              "ollama": False, "models_ready": False, "index": None, "eval": None}
    try:
        models = await asyncio.to_thread(Ollama(settings).available_models)
        status["ollama"] = True
        status["models_ready"] = all(any(m.startswith(want) for m in models)
                                     for want in (settings.chat_model, settings.embed_model))
    except OllamaError as e:
        status["error"] = str(e)
    for name, key in (("manifest.json", "index"), ("eval_report.json", "eval")):
        path = INDEX_DIR / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            status[key] = data.get("summary", data)
    return status


@app.post("/api/copilot/ask")
async def copilot_ask(req: CopilotQuestion):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask a question first.")
    try:
        copilot = await asyncio.to_thread(_get_copilot)
        result = await asyncio.to_thread(copilot.ask, question[:500])
    except FileNotFoundError:
        raise HTTPException(status_code=409, detail="No index yet. Run: python -m research_copilot build")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Copilot failed: {e}")
    logger.info("[LLM] Copilot answered in %.1fs (%s): %s", result["generation_seconds"], result["model"], question[:80])
    return result


if __name__ == "__main__":
    import uvicorn

    print("=" * 80)
    print("Launching Autonomous Job Pipeline Visual Dashboard")
    print("Confined strictly to:", BASE_DIR)
    print("Dashboard URL: http://127.0.0.1:8000")
    print("=" * 80)
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
