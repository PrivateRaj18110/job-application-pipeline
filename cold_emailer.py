"""
Module: cold_emailer.py
Cold outreach engine. Stores recruiter / hiring-manager contacts, drafts a personal email for each one
from cv.json (zero-hallucination LLM prompt with a template fallback), sends it over SMTP with the CV
attached, sends one polite follow-up, and stops automatically once a contact replies (IMAP check).

Guardrails for unattended sending:
- Daily send cap (EMAIL_DAILY_LIMIT) and randomized pacing between sends
- Each address gets one first email plus at most EMAIL_MAX_FOLLOWUPS follow-ups, threaded as replies
- A reply in the inbox, or the "Do not contact" status, stops all further mail to that address
- EMAIL_DRY_RUN=true (or missing SMTP credentials) writes .eml previews to output/emails/ instead of sending

Run with:
  python cold_emailer.py --run-once            # draft new contacts (and send if EMAIL_AUTO_SEND=true)
  python cold_emailer.py --run-once --send     # send during this run even if EMAIL_AUTO_SEND=false
  python cold_emailer.py --daemon --interval 60
  python cold_emailer.py --import contacts.csv
"""

import io
import os
import re
import csv
import sys
import ssl
import json
import uuid
import random
import asyncio
import imaplib
import logging
import smtplib
import argparse
import threading
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable

from dotenv import load_dotenv

import resume_tailor
import portfolio_builder

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CONTACTS_FILE = BASE_DIR / "contacts.json"
EMAIL_PREVIEW_DIR = BASE_DIR / "output" / "emails"

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
IMAP_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

STATUSES = {
    "new": "New",
    "drafted": "Draft ready",
    "previewed": "Previewed (dry run)",
    "sent": "Sent",
    "followed_up": "Followed up",
    "replied": "Replied",
    "failed": "Failed",
    "do_not_contact": "Do not contact",
}
CLOSED_STATUSES = {"replied", "do_not_contact"}
EDITABLE_FIELDS = {"name", "company", "role", "job_url", "notes", "subject", "body", "status"}

OPT_OUT_LINE = "If this isn't relevant, just let me know and I won't follow up."

CSV_HEADER_ALIASES = {
    "name": ["name", "full name", "full_name", "contact", "contact name"],
    "first_name": ["first name", "first_name", "firstname"],
    "last_name": ["last name", "last_name", "lastname", "surname"],
    "email": ["email", "e-mail", "email address", "mail"],
    "company": ["company", "organization", "organisation", "employer", "company name"],
    "role": ["role", "title", "position", "job title"],
    "job_url": ["job_url", "job url", "url", "link", "job link", "posting"],
    "notes": ["notes", "note", "comment", "comments"],
}

EMAIL_SYSTEM_PROMPT = """You write short, genuine cold emails from a job seeker to a recruiter or hiring manager.

FACT RULES (ZERO HALLUCINATION):
1. The CANDIDATE CV (JSON) is the ONLY source of facts about the candidate. Never invent employers, projects, metrics, skills, degrees or dates.
2. Mention at most two projects or experiences from the CV, choosing the ones closest to the role.
3. Do not claim to know anything about the company beyond what the CONTACT and JOB CONTEXT sections say.

STYLE:
- Body of 90-140 words, plain text, no markdown, no emojis, no buzzword stacks.
- Greet the contact by first name when one is given, otherwise "Hi there".
- One clear ask: a short call, or a pointer to the right person for the role.
- Say the CV is attached. Include the portfolio link if one is given.
- Do NOT add a sign-off or signature; one is appended automatically.

OUTPUT FORMAT (exactly):
SUBJECT: <subject line under 70 characters>
BODY:
<email body>
"""

FOLLOW_UP_SYSTEM_PROMPT = """You write a brief, polite follow-up to a cold email that a job seeker sent earlier and got no reply to.

RULES:
- 40-70 words, plain text, no markdown, no guilt-tripping.
- Add one new, true detail from the CANDIDATE CV that the original email did not mention, if there is one.
- Never invent facts. Do NOT add a sign-off or signature; one is appended automatically.

OUTPUT FORMAT (exactly):
BODY:
<email body>
"""

_store_lock = threading.RLock()
_send_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("true", "1", "yes")


def get_settings() -> Dict[str, Any]:
    """Reads outreach settings from the environment at call time."""
    return {
        "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "587")),
        "smtp_user": os.getenv("SMTP_USER", "").strip(),
        "smtp_password": os.getenv("SMTP_APP_PASSWORD", "").strip(),
        "imap_host": os.getenv("IMAP_HOST", "imap.gmail.com"),
        "from_name": os.getenv("EMAIL_FROM_NAME", "").strip(),
        "auto_send": _env_bool("EMAIL_AUTO_SEND", False),
        "dry_run": _env_bool("EMAIL_DRY_RUN", True),
        "daily_limit": int(os.getenv("EMAIL_DAILY_LIMIT", "15")),
        "followup_days": int(os.getenv("EMAIL_FOLLOWUP_DAYS", "5")),
        "max_followups": int(os.getenv("EMAIL_MAX_FOLLOWUPS", "1")),
        "min_delay": int(os.getenv("EMAIL_MIN_DELAY_SECONDS", "60")),
        "max_delay": int(os.getenv("EMAIL_MAX_DELAY_SECONDS", "180")),
    }


def smtp_configured(settings: Optional[Dict[str, Any]] = None) -> bool:
    settings = settings or get_settings()
    password = settings["smtp_password"]
    return bool(settings["smtp_user"] and password and not password.startswith("your_"))


def public_settings() -> Dict[str, Any]:
    """Settings safe to show in the dashboard (no credentials)."""
    settings = get_settings()
    return {
        "smtp_configured": smtp_configured(settings),
        "smtp_user": settings["smtp_user"],
        "auto_send": settings["auto_send"],
        "dry_run": settings["dry_run"] or not smtp_configured(settings),
        "daily_limit": settings["daily_limit"],
        "followup_days": settings["followup_days"],
        "max_followups": settings["max_followups"],
    }


# ---------------------------------------------------------------------------
# Contact Store (contacts.json)
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _label(contact: Dict[str, Any]) -> str:
    return contact.get("name") or contact.get("email", "")


def load_contacts() -> List[Dict[str, Any]]:
    with _store_lock:
        if not CONTACTS_FILE.exists():
            return []
        try:
            with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            # Refuse to continue rather than overwrite a damaged contact list
            raise ValueError(f"{CONTACTS_FILE.name} is not valid JSON ({e}). Fix or remove it.") from e


def _save_contacts(contacts: List[Dict[str, Any]]) -> None:
    tmp_path = CONTACTS_FILE.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(contacts, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, CONTACTS_FILE)


def get_contact(contact_id: str) -> Dict[str, Any]:
    for contact in load_contacts():
        if contact["id"] == contact_id:
            return contact
    raise KeyError(f"Contact {contact_id} not found.")


def _mutate_contact(contact_id: str, apply: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    """Loads, modifies and saves one contact under the store lock."""
    with _store_lock:
        contacts = load_contacts()
        for contact in contacts:
            if contact["id"] == contact_id:
                apply(contact)
                contact["updated_at"] = _now()
                _save_contacts(contacts)
                return dict(contact)
    raise KeyError(f"Contact {contact_id} not found.")


def add_contact(data: Dict[str, Any]) -> Dict[str, Any]:
    email = _clean(data.get("email")).lower()
    if not EMAIL_RE.match(email):
        raise ValueError(f"'{email}' is not a valid email address.")

    with _store_lock:
        contacts = load_contacts()
        if any(c["email"] == email for c in contacts):
            raise ValueError(f"{email} is already in your contacts.")
        contact = {
            "id": uuid.uuid4().hex[:12],
            "name": _clean(data.get("name")),
            "email": email,
            "company": _clean(data.get("company")),
            "role": _clean(data.get("role")),
            "job_url": _clean(data.get("job_url")),
            "notes": _clean(data.get("notes")),
            "status": "new",
            "subject": "",
            "body": "",
            "thread_message_id": "",
            "last_error": "",
            "history": [],
            "created_at": _now(),
            "updated_at": _now(),
        }
        contacts.append(contact)
        _save_contacts(contacts)

    logger.info("[EMAIL] Added contact %s (%s)", _label(contact), contact["company"] or "no company")
    return contact


def update_contact(contact_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    changes = {k: _clean(v) for k, v in fields.items() if k in EDITABLE_FIELDS and v is not None}
    if "status" in changes and changes["status"] not in STATUSES:
        raise ValueError(f"Unknown status '{changes['status']}'.")

    def apply(contact: Dict[str, Any]) -> None:
        contact.update(changes)
        edited_draft = "subject" in changes or "body" in changes
        if edited_draft and contact["status"] == "new" and contact["subject"] and contact["body"]:
            contact["status"] = "drafted"

    return _mutate_contact(contact_id, apply)


def delete_contact(contact_id: str) -> None:
    with _store_lock:
        contacts = load_contacts()
        remaining = [c for c in contacts if c["id"] != contact_id]
        if len(remaining) == len(contacts):
            raise KeyError(f"Contact {contact_id} not found.")
        _save_contacts(remaining)


def import_contacts_csv(csv_text: str) -> Dict[str, Any]:
    """Adds contacts from CSV text. Needs an email column; other columns are matched by common names."""
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        raise ValueError("The CSV is empty.")

    column_for: Dict[str, str] = {}
    for header in reader.fieldnames:
        key = (header or "").strip().lower()
        for field, aliases in CSV_HEADER_ALIASES.items():
            if key in aliases and field not in column_for:
                column_for[field] = header
    if "email" not in column_for:
        raise ValueError("The CSV needs an 'email' column.")

    added, skipped = 0, []
    for line_no, row in enumerate(reader, start=2):
        data = {field: row.get(header, "") for field, header in column_for.items()}
        if not data.get("name"):
            data["name"] = " ".join(p for p in (_clean(data.get("first_name")), _clean(data.get("last_name"))) if p)
        try:
            add_contact(data)
            added += 1
        except ValueError as e:
            skipped.append(f"Row {line_no}: {e}")

    logger.info("[EMAIL] CSV import: %d added, %d skipped", added, len(skipped))
    return {"added": added, "skipped": skipped}


def sent_today(contacts: List[Dict[str, Any]]) -> int:
    today = datetime.now().date().isoformat()
    return sum(
        1
        for c in contacts
        for h in c.get("history", [])
        if h.get("type") in ("initial", "follow_up") and h.get("at", "").startswith(today)
    )


def get_stats(contacts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, int]:
    contacts = load_contacts() if contacts is None else contacts
    stats = {status: 0 for status in STATUSES}
    for contact in contacts:
        stats[contact.get("status", "new")] = stats.get(contact.get("status", "new"), 0) + 1
    stats["total"] = len(contacts)
    stats["sent_today"] = sent_today(contacts)
    return stats


def _already_emailed(contact: Dict[str, Any]) -> bool:
    return any(h.get("type") == "initial" for h in contact.get("history", []))


def _follow_up_due(contact: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    if contact.get("status") not in ("sent", "followed_up"):
        return False
    sends = [h for h in contact.get("history", []) if h.get("type") in ("initial", "follow_up")]
    follow_ups = sum(1 for h in sends if h["type"] == "follow_up")
    if not sends or follow_ups >= settings["max_followups"]:
        return False
    last_sent = datetime.fromisoformat(sends[-1]["at"])
    return datetime.now() - last_sent >= timedelta(days=settings["followup_days"])


# ---------------------------------------------------------------------------
# Email Content
# ---------------------------------------------------------------------------
def _job_context(job_url: str) -> Tuple[str, Optional[Path]]:
    """Returns (job description, tailored resume PDF) for a job already in the tracker."""
    if not job_url:
        return "", None
    try:
        import sheet_manager

        for record in sheet_manager.get_all_jobs():
            url = record.get("Job URL") or record.get("job_url") or ""
            if url.strip() != job_url.strip():
                continue
            description = record.get("Job Description (Context)") or record.get("description") or ""
            raw_pdf = record.get("Tailored Resume Path") or record.get("resume_path") or ""
            pdf_path = Path(raw_pdf) if raw_pdf.endswith(".pdf") and Path(raw_pdf).exists() else None
            return description[:3000], pdf_path
    except Exception as e:
        logger.warning("[EMAIL] Could not read the job tracker for context: %s", e)
    return "", None


def _first_name(contact: Dict[str, Any]) -> str:
    parts = contact.get("name", "").split()
    return parts[0] if parts else ""


def _pick_projects(cv: Dict[str, Any], context: str, limit: int = 2) -> List[Dict[str, Any]]:
    """Ranks CV projects by word overlap with the role / company / job description."""
    context_words = set(re.findall(r"[a-z0-9+#]+", context.lower()))

    def score(project: Dict[str, Any]) -> Tuple[int, bool]:
        text = " ".join(project.get("tech", []) + [project.get("name", ""), project.get("category", ""), project.get("summary", "")])
        words = set(re.findall(r"[a-z0-9+#]+", text.lower()))
        return (sum(1 for w in words if len(w) > 2 and w in context_words), bool(project.get("featured")))

    return sorted(cv.get("projects", []), key=score, reverse=True)[:limit]


def _template_email(contact: Dict[str, Any], cv: Dict[str, Any], job_description: str) -> Tuple[str, str]:
    profile = cv["profile"]
    portfolio = profile.get("links", {}).get("portfolio", "")
    company = contact.get("company") or "your team"
    role = contact.get("role")
    projects = _pick_projects(cv, " ".join([role or "", company, contact.get("notes", ""), job_description]))

    subject = f"{role} at {company} | {profile['name']}" if role else f"Exploring roles at {company} | {profile['name']}"
    article = "an" if profile["title"][:1].lower() in "aeiou" else "a"
    lines = [
        f"Hi {_first_name(contact) or 'there'},",
        "",
        f"I'm {profile['name']}, {article} {profile['title']}. I'm reaching out because I'd love to contribute to "
        f"{company}{f' as a {role}' if role else ''}.",
    ]
    if projects:
        lines += ["", "A couple of things I've built that may be relevant:"]
        lines += [f"- {p['name']}: {p.get('summary', '')}".rstrip(": ") for p in projects]
    lines += [
        "",
        f"My CV is attached{f', and you can see my projects at {portfolio}' if portfolio else ''}. "
        "Would you be open to a 15-minute chat, or could you point me to the right person for this role?",
    ]
    return subject[:90], "\n".join(lines)


def _template_follow_up(contact: Dict[str, Any], cv: Dict[str, Any]) -> str:
    company = contact.get("company") or "your team"
    role = contact.get("role") or "open roles"
    projects = cv.get("projects", [])
    detail = f" I'd be glad to walk you through {projects[0]['name']} or anything else on my CV." if projects else ""
    return (
        f"Hi {_first_name(contact) or 'there'},\n\n"
        f"Following up on my note about {role} at {company}. I'm still very interested.{detail}\n\n"
        "Would a quick call in the next week or two work for you?"
    )


def _cv_for_prompt(cv: Dict[str, Any]) -> str:
    profile = {k: v for k, v in cv.get("profile", {}).items() if k not in ("phone", "show_phone")}
    return json.dumps(dict(cv, profile=profile), ensure_ascii=False)


def generate_email(contact: Dict[str, Any], cv: Dict[str, Any], kind: str = "initial") -> Tuple[str, str, str]:
    """Returns (subject, body, source) where source is 'llm' or 'template'. Follow-ups return an empty subject."""
    job_description, _ = _job_context(contact.get("job_url", ""))
    portfolio = cv["profile"].get("links", {}).get("portfolio", "")
    user_prompt = (
        f"CANDIDATE CV (JSON):\n{_cv_for_prompt(cv)}\n\n"
        f"CONTACT:\nName: {contact.get('name') or 'Unknown'}\nCompany: {contact.get('company') or 'Unknown'}\n"
        f"Role they hire for: {contact.get('role') or 'Not specified'}\n"
        f"Notes from the candidate: {contact.get('notes') or 'None'}\n\n"
        f"JOB CONTEXT:\n{job_description or 'None provided.'}\n\n"
        f"PORTFOLIO LINK: {portfolio or 'None'}"
    )

    if kind == "follow_up":
        user_prompt += f"\n\nORIGINAL EMAIL:\nSubject: {contact.get('subject', '')}\n{contact.get('body', '')}"
        _, body = _parse_llm_email(resume_tailor.generate_text(FOLLOW_UP_SYSTEM_PROMPT, user_prompt))
        if body:
            return "", body, "llm"
        return "", _template_follow_up(contact, cv), "template"

    subject, body = _parse_llm_email(resume_tailor.generate_text(EMAIL_SYSTEM_PROMPT, user_prompt))
    if subject and body:
        return subject[:90], body, "llm"
    subject, body = _template_email(contact, cv, job_description)
    return subject, body, "template"


def _parse_llm_email(text: str) -> Tuple[str, str]:
    subject_match = re.search(r"^\s*SUBJECT:\s*(.+)$", text, re.M)
    body_match = re.search(r"BODY:\s*\n?(.*)", text, re.S)
    subject = subject_match.group(1).strip().strip('"') if subject_match else ""
    body = body_match.group(1).strip() if body_match else ""
    return subject, body


def _signature(cv: Dict[str, Any]) -> str:
    profile = cv["profile"]
    links = profile.get("links", {})
    link_line = " | ".join(u for u in (links.get("portfolio"), links.get("linkedin"), links.get("github")) if u)
    lines = ["Best regards,", profile.get("name", ""), profile.get("title", ""), link_line, profile.get("phone", "")]
    return "\n".join(line for line in lines if line)


def compose_full_body(body: str, cv: Dict[str, Any]) -> str:
    """The exact text that goes out: draft body + opt-out line + signature."""
    return f"{body.strip()}\n\n{OPT_OUT_LINE}\n\n{_signature(cv)}\n"


def build_message(
    contact: Dict[str, Any],
    subject: str,
    body: str,
    cv: Dict[str, Any],
    settings: Dict[str, Any],
    attachment: Optional[Path] = None,
    in_reply_to: str = "",
) -> EmailMessage:
    profile = cv["profile"]
    sender = settings["smtp_user"] or profile["email"]
    msg = EmailMessage()
    msg["From"] = formataddr((settings["from_name"] or profile["name"], sender))
    msg["To"] = formataddr((contact.get("name", ""), contact["email"]))
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(compose_full_body(body, cv))
    if attachment:
        safe_name = re.sub(r"[^\w\-]", "_", profile["name"])
        msg.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf", filename=f"{safe_name}_CV.pdf")
    return msg


def _resolve_attachment(contact: Dict[str, Any]) -> Optional[Path]:
    """Prefers the tailored resume of the linked job, else the portfolio CV PDF (built on demand)."""
    _, tailored_pdf = _job_context(contact.get("job_url", ""))
    if tailored_pdf:
        return tailored_pdf
    if not portfolio_builder.PORTFOLIO_PDF_FILE.exists():
        try:
            portfolio_builder.build_portfolio()
        except Exception as e:
            logger.warning("[EMAIL] Could not build the CV PDF: %s", e)
    return portfolio_builder.PORTFOLIO_PDF_FILE if portfolio_builder.PORTFOLIO_PDF_FILE.exists() else None


# ---------------------------------------------------------------------------
# Drafting & Sending
# ---------------------------------------------------------------------------
def draft_contact(contact_id: str, cv: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generates (or regenerates) the first email for a contact that hasn't been emailed yet."""
    cv = cv or portfolio_builder.load_cv()
    contact = get_contact(contact_id)
    if contact["status"] in CLOSED_STATUSES:
        raise ValueError(f"{_label(contact)} is marked '{STATUSES[contact['status']]}', so no email was drafted.")
    if _already_emailed(contact):
        raise ValueError(f"{_label(contact)} has already been emailed.")

    subject, body, source = generate_email(contact, cv)

    def apply(c: Dict[str, Any]) -> None:
        c["subject"], c["body"], c["last_error"] = subject, body, ""
        if c["status"] in ("new", "failed"):
            c["status"] = "drafted"

    updated = _mutate_contact(contact_id, apply)
    logger.info("[EMAIL] Drafted email for %s (%s): %s", _label(contact), source, subject)
    return updated


def _slug(text: str) -> str:
    return re.sub(r"[^\w\-]", "_", text)[:40]


def send_contact_email(
    contact_id: str,
    kind: str = "initial",
    settings: Optional[Dict[str, Any]] = None,
    cv: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Sends the first email or a follow-up to one contact. In dry-run mode the message is written to
    output/emails/ instead. Returns {"status": sent|previewed|skipped|failed, "detail": str, "contact": dict}.
    """
    settings = settings or get_settings()
    cv = cv or portfolio_builder.load_cv()

    # One send at a time, so a dashboard click and the background cycle can't email the same person twice
    with _send_lock:
        contact = get_contact(contact_id)
        label = _label(contact)

        if contact["status"] in CLOSED_STATUSES:
            return {"status": "skipped", "detail": f"{label} is marked '{STATUSES[contact['status']]}'.", "contact": contact}
        if kind == "initial" and _already_emailed(contact):
            return {"status": "skipped", "detail": f"{label} has already been emailed.", "contact": contact}
        if kind == "follow_up" and not _already_emailed(contact):
            return {"status": "skipped", "detail": f"{label} has not received a first email yet.", "contact": contact}

        if kind == "initial":
            if not contact["subject"] or not contact["body"]:
                contact = draft_contact(contact_id, cv)
            subject, body, in_reply_to = contact["subject"], contact["body"], ""
            attachment = _resolve_attachment(contact)
            if attachment is None:
                return {"status": "failed", "detail": "No CV PDF to attach. Build the portfolio first.", "contact": contact}
        else:
            _, body, _ = generate_email(contact, cv, kind="follow_up")
            subject = "Re: " + re.sub(r"^(re:\s*)+", "", contact["subject"], flags=re.I)
            in_reply_to, attachment = contact.get("thread_message_id", ""), None

        msg = build_message(contact, subject, body, cv, settings, attachment, in_reply_to)

        if settings["dry_run"] or not smtp_configured(settings):
            EMAIL_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
            preview_path = EMAIL_PREVIEW_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{_slug(contact['email'])}_{kind}.eml"
            preview_path.write_bytes(bytes(msg))

            def apply_preview(c: Dict[str, Any]) -> None:
                c["history"].append({"type": "preview", "kind": kind, "at": _now(), "subject": subject, "detail": preview_path.name})
                if c["status"] in ("new", "drafted"):
                    c["status"] = "previewed"

            updated = _mutate_contact(contact_id, apply_preview)
            logger.info("[EMAIL] Dry run: %s email for %s saved to output/emails/%s", kind, label, preview_path.name)
            return {"status": "previewed", "detail": f"Dry run: saved to output/emails/{preview_path.name}", "contact": updated}

        try:
            _smtp_send(msg, settings)
        except Exception as e:
            error = str(e)[:300]

            def apply_failure(c: Dict[str, Any]) -> None:
                c["last_error"] = error
                c["history"].append({"type": "error", "kind": kind, "at": _now(), "detail": error})
                if kind == "initial":
                    c["status"] = "failed"

            updated = _mutate_contact(contact_id, apply_failure)
            logger.error("[EMAIL] Sending to %s failed: %s", label, error)
            return {"status": "failed", "detail": error, "contact": updated}

        def apply_sent(c: Dict[str, Any]) -> None:
            c["history"].append({"type": kind, "at": _now(), "subject": subject, "body": body, "message_id": msg["Message-ID"]})
            c["last_error"] = ""
            if kind == "initial":
                c["status"], c["thread_message_id"] = "sent", msg["Message-ID"]
            else:
                c["status"] = "followed_up"

        updated = _mutate_contact(contact_id, apply_sent)
        logger.info("[OK] [EMAIL] Sent %s email to %s <%s>: %s", kind.replace("_", "-"), label, contact["email"], subject)
        return {"status": "sent", "detail": f"Sent to {contact['email']}", "contact": updated}


def _smtp_send(msg: EmailMessage, settings: Dict[str, Any]) -> None:
    context = ssl.create_default_context()
    if settings["smtp_port"] == 465:
        with smtplib.SMTP_SSL(settings["smtp_host"], 465, timeout=30, context=context) as server:
            server.login(settings["smtp_user"], settings["smtp_password"])
            server.send_message(msg)
    else:
        with smtplib.SMTP(settings["smtp_host"], settings["smtp_port"], timeout=30) as server:
            server.starttls(context=context)
            server.login(settings["smtp_user"], settings["smtp_password"])
            server.send_message(msg)


def check_replies(settings: Optional[Dict[str, Any]] = None) -> int:
    """Marks contacts as 'replied' when a message from their address is in the inbox since the first email."""
    settings = settings or get_settings()
    if not smtp_configured(settings):
        return 0
    awaiting = [c for c in load_contacts() if c["status"] in ("sent", "followed_up")]
    if not awaiting:
        return 0

    found = 0
    try:
        with imaplib.IMAP4_SSL(settings["imap_host"]) as imap:
            imap.login(settings["smtp_user"], settings["smtp_password"])
            imap.select("INBOX", readonly=True)
            for contact in awaiting:
                first_sent = next(datetime.fromisoformat(h["at"]) for h in contact["history"] if h["type"] == "initial")
                since = f"{first_sent.day:02d}-{IMAP_MONTHS[first_sent.month - 1]}-{first_sent.year}"
                typ, data = imap.search(None, "FROM", f'"{contact["email"]}"', "SINCE", since)
                if typ != "OK" or not data or not data[0].split():
                    continue

                def apply_reply(c: Dict[str, Any]) -> None:
                    c["status"] = "replied"
                    c["history"].append({"type": "reply", "at": _now(), "detail": "Reply found in inbox"})

                _mutate_contact(contact["id"], apply_reply)
                found += 1
                logger.info("[EMAIL] %s replied. No more emails will be sent to them.", _label(contact))
    except Exception as e:
        logger.warning("[EMAIL] Reply check skipped (IMAP error): %s", e)
    return found


# ---------------------------------------------------------------------------
# Unattended Outreach Cycle
# ---------------------------------------------------------------------------
async def _pause(seconds: int, stop_event: Optional[asyncio.Event]) -> None:
    """Sleeps in 1-second slices so stop requests are handled immediately."""
    for _ in range(int(seconds)):
        if stop_event is not None and stop_event.is_set():
            return
        await asyncio.sleep(1)


async def run_outreach_cycle(
    auto_send: Optional[bool] = None,
    stop_event: Optional[asyncio.Event] = None,
    on_step: Optional[Callable[[str], None]] = None,
) -> Dict[str, int]:
    """Checks replies, drafts emails for new contacts, then (if auto-send) sends first emails and due follow-ups."""
    settings = get_settings()
    auto_send = settings["auto_send"] if auto_send is None else auto_send
    dry_run = settings["dry_run"] or not smtp_configured(settings)
    summary = {"replies": 0, "drafted": 0, "sent": 0, "followed_up": 0, "previewed": 0, "failed": 0, "deferred": 0}

    def stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    def step(text: str) -> None:
        if on_step:
            on_step(text)

    logger.info("[EMAIL] Outreach cycle started (auto-send: %s, mode: %s)", "on" if auto_send else "off", "DRY RUN" if dry_run else "LIVE")
    cv = await asyncio.to_thread(portfolio_builder.load_cv)

    if not dry_run:
        step("Checking inbox for replies...")
        summary["replies"] = await asyncio.to_thread(check_replies, settings)

    for contact in [c for c in load_contacts() if c["status"] == "new"]:
        if stopped():
            return summary
        step(f"Drafting email for {_label(contact)}...")
        try:
            await asyncio.to_thread(draft_contact, contact["id"], cv)
            summary["drafted"] += 1
        except Exception as e:
            logger.error("[EMAIL] Drafting failed for %s: %s", _label(contact), e)
            summary["failed"] += 1

    if not auto_send:
        waiting = sum(1 for c in load_contacts() if c["status"] in ("drafted", "previewed"))
        logger.info("[EMAIL] Auto-send is off. %d draft(s) are waiting for review in the dashboard.", waiting)
        return summary

    ready_statuses = ("drafted",) if dry_run else ("drafted", "previewed")
    contacts = load_contacts()
    queue = [(c["id"], "initial") for c in contacts if c["status"] in ready_statuses]
    if not dry_run:
        queue += [(c["id"], "follow_up") for c in contacts if _follow_up_due(c, settings)]

    remaining = settings["daily_limit"] - sent_today(contacts)
    sent_any = False
    for index, (contact_id, kind) in enumerate(queue):
        if stopped():
            break
        if not dry_run:
            if remaining <= 0:
                summary["deferred"] = len(queue) - index
                logger.info("[EMAIL] Daily limit of %d reached. %d email(s) will go out in a later cycle.",
                            settings["daily_limit"], summary["deferred"])
                break
            if sent_any:
                delay = random.randint(settings["min_delay"], max(settings["min_delay"], settings["max_delay"]))
                step(f"Pacing: waiting {delay}s before the next email...")
                logger.info("[EMAIL] Waiting %ds before the next email", delay)
                await _pause(delay, stop_event)
                if stopped():
                    break

        step(f"Sending {kind.replace('_', '-')} email ({index + 1}/{len(queue)})...")
        result = await asyncio.to_thread(send_contact_email, contact_id, kind, settings, cv)
        if result["status"] == "sent":
            summary["sent" if kind == "initial" else "followed_up"] += 1
            remaining -= 1
            sent_any = True
        elif result["status"] == "previewed":
            summary["previewed"] += 1
        elif result["status"] == "failed":
            summary["failed"] += 1

    logger.info("[EMAIL] Outreach cycle finished: %s", summary)
    return summary


async def run_daemon(
    interval_minutes: int = 60,
    auto_send: Optional[bool] = None,
    stop_event: Optional[asyncio.Event] = None,
    on_step: Optional[Callable[[str], None]] = None,
) -> None:
    """Runs outreach cycles forever (until stop_event is set)."""
    stop_event = stop_event or asyncio.Event()
    cycle = 0
    while not stop_event.is_set():
        cycle += 1
        try:
            await run_outreach_cycle(auto_send=auto_send, stop_event=stop_event, on_step=on_step)
        except Exception as e:
            logger.error("[EMAIL] Outreach cycle #%d failed: %s", cycle, e)
        if on_step:
            on_step(f"Outreach sleeping until next cycle (cycle #{cycle} done)")
        await _pause(interval_minutes * 60, stop_event)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Cold email outreach for your job search")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-once", action="store_true", help="Run a single outreach cycle")
    mode.add_argument("--daemon", action="store_true", help="Run outreach cycles on an interval")
    mode.add_argument("--import", dest="import_csv", metavar="CSV", help="Import contacts from a CSV file")
    mode.add_argument("--list", action="store_true", help="List contacts and their status")
    parser.add_argument("--send", action="store_true", help="Send during this run even if EMAIL_AUTO_SEND=false")
    parser.add_argument("--interval", type=int, default=60, help="Daemon interval in minutes (default: 60)")
    args = parser.parse_args()

    if args.import_csv:
        result = import_contacts_csv(Path(args.import_csv).read_text(encoding="utf-8-sig"))
        print(f"Added {result['added']} contact(s).")
        for reason in result["skipped"]:
            print(f"  Skipped {reason}")
    elif args.list:
        for c in load_contacts():
            print(f"{STATUSES.get(c['status'], c['status']):<20} {c['email']:<35} {c['name']} ({c['company']})")
    elif args.run_once:
        print(asyncio.run(run_outreach_cycle(auto_send=True if args.send else None)))
    else:
        try:
            asyncio.run(run_daemon(interval_minutes=args.interval, auto_send=True if args.send else None))
        except KeyboardInterrupt:
            print("Outreach daemon stopped.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()
