# Automated Job Discovery, Resume Tailoring & Application Pipeline

A 100% fully automated, unattended background pipeline for job discovery, anti-hallucination resume tailoring, Google Sheets state tracking, and Playwright-driven application submission with anti-bot mitigations.

Candidate Source of Truth: **Alex Rivera** (Quantitative Systems & Machine Learning Engineer).

---

## 🏗️ Architecture & Modules

The codebase is strictly confined to `c:/Users/Light/Documents/antigravity/lively-carson`:

| File | Purpose | Key Technologies |
|---|---|---|
| [`targets.json`](file:///c:/Users/Light/Documents/antigravity/lively-carson/targets.json) | Central target registry containing job boards (Greenhouse, Lever, etc.), role keyword filters, and scrape intervals. | JSON configuration |
| [`scheduler.py`](file:///c:/Users/Light/Documents/antigravity/lively-carson/scheduler.py) | Unattended background scheduler and execution loop. Handles rate-limiting delays (30–90s) between submissions. | Python `asyncio` |
| [`main.py`](file:///c:/Users/Light/Documents/antigravity/lively-carson/main.py) | Master CLI entrypoint supporting `--daemon`, `--run-once`, `--mock`, and direct `--url` execution. | Python CLI |
| [`scraper.py`](file:///c:/Users/Light/Documents/antigravity/lively-carson/scraper.py) | Discovers openings across Greenhouse, Lever, or generic job pages; matches against role keywords. | Playwright (Async) |
| [`sheet_manager.py`](file:///c:/Users/Light/Documents/antigravity/lively-carson/sheet_manager.py) | Manages state & prevents duplicates. Reads & logs rows in Google Sheets. | `gspread`, `google-auth` |
| [`resume_tailor.py`](file:///c:/Users/Light/Documents/antigravity/lively-carson/resume_tailor.py) | Tailors the master resume using a strict zero-hallucination system prompt. Exports PDF to `output/`. | `google-genai` (Gemini), `markdown-pdf` |
| [`apply_bot.py`](file:///c:/Users/Light/Documents/antigravity/lively-carson/apply_bot.py) | Automated application submission engine. Fills inputs with human typing delays, uploads PDFs, checks consent, handles CAPTCHA/questionnaires, and logs visual audit screenshots to `logs/screenshots/`. | Playwright (Async) |
| [`master_resume.md`](file:///c:/Users/Light/Documents/antigravity/lively-carson/master_resume.md) | Ground-truth candidate profile: Modern C++, Numba, PyTorch, MetaTrader 5 & FlatTrade APIs. | Markdown |

---

## 🛡️ Anti-Bot Mitigations & Error Handling

- **Human Keystroke Emulation**: Text fields are filled with randomized keystroke pacing (`delay=30–60ms`).
- **Consent Checkboxes**: Automatically locates and toggles mandatory privacy/consent/terms checkboxes.
- **CAPTCHA & Questionnaire Detection**: Scans for Cloudflare Turnstile, reCAPTCHA, hCaptcha, or multi-stage quiz questionnaires. If detected, takes an audit screenshot in `logs/screenshots/`, marks the sheet row as `"Blocked - CAPTCHA / Questionnaire"`, and continues to the next job.
- **Visual Audit Logging**: Full-page screenshots are saved for every attempt in `logs/screenshots/<job_slug>_<status>_<timestamp>.png`.
- **Randomized Pacing Delay**: Pauses 30–90 seconds between applications to avoid bot detection and rate limits.

---

## ⚙️ Setup & Configuration

### 1. Configure Environment (`.env`)
```ini
# Google Gemini API Key
GEMINI_API_KEY=your_gemini_api_key_here
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-2.5-flash

# Google Sheet Target
GOOGLE_SHEET_ID=your_google_sheet_id_here
GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json

# Unattended Controls
AUTO_SUBMIT=false
HEADLESS_BROWSER=true
```

### 2. Configure Target Boards (`targets.json`)
Add or customize target career boards and keyword filters in [`targets.json`](file:///c:/Users/Light/Documents/antigravity/lively-carson/targets.json):
```json
{
  "settings": {
    "default_scrape_interval_minutes": 60,
    "min_delay_between_applications_seconds": 30,
    "max_delay_between_applications_seconds": 90
  },
  "targets": [
    {
      "name": "Anthropic Careers",
      "type": "greenhouse",
      "url": "https://boards.greenhouse.io/anthropic",
      "enabled": true,
      "role_keywords": ["Python", "Machine Learning", "Backend", "AI"]
    }
  ]
}
```

---

## 🚀 Running the System

### 1. Immediate Single-Pass Automated Run
Scans all enabled targets in `targets.json`, deduplicates, tailors resumes, submits applications, and updates Google Sheets:
```bash
python main.py --run-once
```

### 2. Continuous Unattended Background Daemon
Runs on a scheduled interval (e.g. every 60 minutes) indefinitely:
```bash
python main.py --daemon
```
Custom interval (e.g. every 30 minutes):
```bash
python main.py --daemon --interval 30
```

### 3. Offline Verification / Mock Pass
Test the entire discovery -> tailoring -> submission -> screenshot flow without hitting external sites:
```bash
python main.py --run-once --mock
```

### 4. Direct Single Target Run
Target a specific job board directly:
```bash
python main.py --url "https://boards.greenhouse.io/<company>"
```

---

## 📊 Google Sheet Schema

| Column | Header | Description |
|---|---|---|
| A | `Date Found` | Timestamp when the job was discovered |
| B | `Job Title` | Target role title |
| C | `Company` | Employer name |
| D | `Job URL` | Unique application link (used for deduplication) |
| E | `Job Description (Context)` | Scraped job description text snippet |
| F | `Tailored Resume Path` | Local path to the generated PDF in `output/` |
| G | `Application Status` | State: `Pending Tailoring`, `Tailored`, `Applied (<timestamp>)`, `Blocked - CAPTCHA / Questionnaire (<timestamp>)`, or `Failed - Needs Manual Check (<timestamp>)` |
