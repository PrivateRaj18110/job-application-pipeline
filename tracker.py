"""
Module: tracker.py
Private job-search tracker for the local dashboard. Merges, per company:
  - applications tracked by sheet_manager (found, tailored, applied, blocked),
  - cold emails from cold_emailer's contacts (sent, followed up, replied),
  - the stage and notes you set yourself (interview, offer, rejected, ...), kept in tracker.json.

Everything stays on this machine: tracker.json is gitignored and the dashboard binds to 127.0.0.1.
"""

import re
import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import cold_emailer
import sheet_manager

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TRACKER_FILE = BASE_DIR / "tracker.json"

# Stages you can set; "auto" means "work it out from applications and emails"
MANUAL_STAGES = {
    "auto": "Automatic",
    "interview": "Interviewing",
    "offer": "Offer",
    "rejected": "Rejected",
    "not_interested": "Not interested",
}
AUTO_STAGES = {
    "replied": "Replied",
    "applied": "Applied",
    "emailed": "Emailed",
    "needs_you": "Needs you",
    "in_progress": "In progress",
}
STAGE_LABELS = {**AUTO_STAGES, **{k: v for k, v in MANUAL_STAGES.items() if k != "auto"}}

STATUS_TIME = re.compile(r"\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\)")
_lock = threading.Lock()


def company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "unknown-company"


def application_state(status: str) -> str:
    """Groups the apply bot's free-text statuses."""
    s = (status or "").lower()
    if s.startswith("applied"):
        return "applied"
    if s.startswith("failed") or s.startswith("blocked") or "manual" in s:
        return "needs_you"
    if s.startswith("staged"):
        return "staged"
    if s.startswith("tailored"):
        return "tailored"
    return "pending"


def _load_notes() -> Dict[str, Dict[str, str]]:
    if not TRACKER_FILE.exists():
        return {}
    try:
        return json.loads(TRACKER_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("[TRACKER] tracker.json is unreadable; starting with no stages or notes.")
        return {}


def update_company(key: str, stage: Optional[str] = None, notes: Optional[str] = None) -> Dict[str, str]:
    """Saves the stage you set (or 'auto') and your notes for one company."""
    if stage is not None and stage not in MANUAL_STAGES:
        raise ValueError(f"Unknown stage '{stage}'. Use one of: {', '.join(MANUAL_STAGES)}.")
    with _lock:
        data = _load_notes()
        entry = data.setdefault(key, {"stage": "auto", "notes": ""})
        if stage is not None:
            entry["stage"] = stage
        if notes is not None:
            entry["notes"] = notes.strip()
        entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
        tmp = TRACKER_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(TRACKER_FILE)
    return entry


def _contact_summary(contact: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    history = contact.get("history", [])
    sends = [h for h in history if h.get("type") in ("initial", "follow_up")]
    reply = next((h for h in history if h.get("type") == "reply"), None)
    follow_up_due = None
    follow_ups = sum(1 for h in sends if h["type"] == "follow_up")
    if contact.get("status") in ("sent", "followed_up") and sends and follow_ups < settings["max_followups"]:
        follow_up_due = (datetime.fromisoformat(sends[-1]["at"]) + timedelta(days=settings["followup_days"])).date().isoformat()
    return {
        "id": contact.get("id"),
        "name": contact.get("name") or contact.get("email"),
        "email": contact.get("email"),
        "role": contact.get("role", ""),
        "status": contact.get("status", "new"),
        "status_label": cold_emailer.STATUSES.get(contact.get("status", "new"), contact.get("status", "")),
        "first_sent_at": sends[0]["at"] if sends else "",
        "follow_ups": follow_ups,
        "replied_at": reply["at"] if reply else "",
        "follow_up_due": follow_up_due,
    }


def _events(applications: List[Dict[str, Any]], contacts: List[Dict[str, Any]], raw_contacts: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    events = []
    for app in applications:
        if app["date_found"]:
            events.append({"at": app["date_found"], "type": "found", "text": f"Found: {app['title']}"})
        stamp = STATUS_TIME.search(app["status"])
        if stamp and app["state"] in ("applied", "needs_you", "staged"):
            verb = {"applied": "Applied", "needs_you": "Needs you", "staged": "Form staged"}[app["state"]]
            events.append({"at": stamp.group(1).replace(" ", "T"), "type": app["state"], "text": f"{verb}: {app['title']}"})
    names = {c["id"]: c["name"] for c in contacts}
    labels = {"initial": "Email sent to", "follow_up": "Follow-up sent to", "reply": "Reply from", "error": "Email failed to"}
    for contact in raw_contacts:
        for h in contact.get("history", []):
            if h.get("type") in labels:
                events.append({"at": h["at"], "type": h["type"], "text": f"{labels[h['type']]} {names.get(contact.get('id'), '')}"})
    return sorted(events, key=lambda e: e["at"], reverse=True)


def build_overview() -> Dict[str, Any]:
    """Everything the Tracker tab shows: per-company records, totals and recent activity."""
    settings = cold_emailer.get_settings()
    notes = _load_notes()
    companies: Dict[str, Dict[str, Any]] = {}

    def company(name: str) -> Dict[str, Any]:
        key = company_key(name)
        return companies.setdefault(key, {"key": key, "name": name or "Unknown company", "applications": [],
                                          "contacts": [], "_raw_contacts": []})

    for row in sheet_manager.get_all_jobs():
        status = row.get("Application Status") or ""
        company(row.get("Company", ""))["applications"].append({
            "title": row.get("Job Title", ""),
            "url": row.get("Job URL", ""),
            "status": status,
            "state": application_state(status),
            "date_found": (row.get("Date Found") or "").replace(" ", "T"),
            "resume": Path(row["Tailored Resume Path"]).name if row.get("Tailored Resume Path") else "",
        })
    for contact in cold_emailer.load_contacts():
        record = company(contact.get("company", ""))
        record["contacts"].append(_contact_summary(contact, settings))
        record["_raw_contacts"].append(contact)
    for key, entry in notes.items():
        if key not in companies:  # a company you only added notes for
            companies[key] = {"key": key, "name": entry.get("name") or key, "applications": [], "contacts": [], "_raw_contacts": []}

    today = datetime.now().date().isoformat()
    for record in companies.values():
        apps, contacts = record["applications"], record["contacts"]
        states = {a["state"] for a in apps}
        statuses = {c["status"] for c in contacts}
        if "replied" in statuses:
            auto = "replied"
        elif "applied" in states:
            auto = "applied"
        elif statuses & {"sent", "followed_up"}:
            auto = "emailed"
        elif "needs_you" in states or "failed" in statuses:
            auto = "needs_you"
        else:
            auto = "in_progress"
        entry = notes.get(record["key"], {})
        manual = entry.get("stage", "auto")
        record["stage"] = manual if manual != "auto" else auto
        record["stage_source"] = "you" if manual != "auto" else "auto"
        record["stage_label"] = STAGE_LABELS[record["stage"]]
        record["notes"] = entry.get("notes", "")
        record["events"] = _events(apps, contacts, record.pop("_raw_contacts"))
        record["last_activity"] = record["events"][0]["at"] if record["events"] else entry.get("updated_at", "")
        dues = sorted(c["follow_up_due"] for c in contacts if c["follow_up_due"])
        record["next_follow_up"] = dues[0] if dues else ""
        record["follow_up_overdue"] = bool(dues and dues[0] <= today)

    records = sorted(companies.values(), key=lambda r: r["last_activity"], reverse=True)
    all_contacts = [c for r in records for c in r["contacts"]]
    emailed = [c for c in all_contacts if c["first_sent_at"]]
    replied = [c for c in all_contacts if c["replied_at"]]
    totals = {
        "companies": len(records),
        "applications": sum(len(r["applications"]) for r in records),
        "applied": sum(1 for r in records for a in r["applications"] if a["state"] == "applied"),
        "needs_you": sum(1 for r in records for a in r["applications"] if a["state"] == "needs_you"),
        "emails_sent": len(emailed),
        "follow_ups_sent": sum(c["follow_ups"] for c in all_contacts),
        "replies": len(replied),
        "reply_rate": round(len(replied) / len(emailed), 3) if emailed else None,
        "interviews": sum(1 for r in records if r["stage"] in ("interview", "offer")),
        "offers": sum(1 for r in records if r["stage"] == "offer"),
        "follow_ups_due": sum(1 for r in records if r["follow_up_overdue"]),
    }
    funnel = {stage: sum(1 for r in records if r["stage"] == stage) for stage in STAGE_LABELS}
    recent = sorted(({**e, "company": r["name"]} for r in records for e in r["events"]),
                    key=lambda e: e["at"], reverse=True)[:25]
    return {"totals": totals, "funnel": funnel, "stage_labels": STAGE_LABELS, "manual_stages": MANUAL_STAGES,
            "companies": records, "recent": recent}
