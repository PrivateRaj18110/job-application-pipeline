"""
Module 2: sheet_manager.py
Google Sheets Database & State Check module.
Interacts with Google Sheets using gspread and google-auth to track jobs,
prevent duplicate processing, and log progress through the application lifecycle.

Target Sheet ID: your_google_sheet_id_here
Headers:
Date Found | Job Title | Company | Job URL | Job Description (Context) | Tailored Resume Path | Application Status
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any, List
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

EXPECTED_HEADERS = [
    "Date Found",
    "Job Title",
    "Company",
    "Job URL",
    "Job Description (Context)",
    "Tailored Resume Path",
    "Application Status",
]

DEFAULT_SHEET_ID = "your_google_sheet_id_here"
LOCAL_BACKUP_FILE = BASE_DIR / "sheet_local_backup.json"


class SheetManager:
    """Manages connection and CRUD operations on the target Google Sheet."""

    def __init__(self, sheet_id: Optional[str] = None, credentials_path: Optional[str] = None):
        self.sheet_id = sheet_id or os.getenv("GOOGLE_SHEET_ID", DEFAULT_SHEET_ID)
        raw_creds = credentials_path or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials.json")
        self.credentials_path = str((BASE_DIR / raw_creds).resolve()) if not Path(raw_creds).is_absolute() else raw_creds
        self.client = None
        self.worksheet = None
        self._init_connection()

    def _init_connection(self):
        """Initializes connection to Google Sheets via gspread and service account."""
        try:
            import gspread
            from google.oauth2.service_account import Credentials

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]

            if not os.path.exists(self.credentials_path):
                logger.warning(
                    "Service account file '%s' not found. "
                    "Running in local fallback simulation mode (saving to %s).",
                    self.credentials_path, LOCAL_BACKUP_FILE
                )
                self._init_local_backup()
                return

            creds = Credentials.from_service_account_file(self.credentials_path, scopes=scopes)
            self.client = gspread.authorize(creds)
            spreadsheet = self.client.open_by_key(self.sheet_id)
            self.worksheet = spreadsheet.sheet1

            # Ensure header row exists
            existing_headers = self.worksheet.row_values(1)
            if not existing_headers:
                logger.info("Initializing sheet headers on first worksheet...")
                self.worksheet.append_row(EXPECTED_HEADERS)
            logger.info("Connected successfully to Google Sheet: %s", spreadsheet.title)

        except Exception as e:
            logger.warning(
                "Unable to connect to Google Sheets (%s). Falling back to local storage.", e
            )
            self._init_local_backup()

    def _init_local_backup(self):
        """Initializes local JSON database backup for offline or initial testing."""
        if not os.path.exists(LOCAL_BACKUP_FILE):
            with open(LOCAL_BACKUP_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)

    def _read_local_data(self) -> List[Dict[str, Any]]:
        if not os.path.exists(LOCAL_BACKUP_FILE):
            return []
        try:
            with open(LOCAL_BACKUP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _write_local_data(self, data: List[Dict[str, Any]]):
        with open(LOCAL_BACKUP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def check_if_job_exists(self, job_url: str) -> bool:
        """
        Reads the 'Job URL' column to prevent duplicate processing.
        Returns True if job_url already exists in the sheet, False otherwise.
        """
        job_url_clean = (job_url or "").strip().rstrip("/")
        if not job_url_clean:
            return False

        if self.worksheet:
            try:
                # Find column index for 'Job URL'
                headers = self.worksheet.row_values(1)
                col_idx = 4
                if "Job URL" in headers:
                    col_idx = headers.index("Job URL") + 1

                urls = self.worksheet.col_values(col_idx)
                # Check normalized URLs (excluding header)
                for existing_url in urls[1:]:
                    if existing_url.strip().rstrip("/") == job_url_clean:
                        logger.info("Job already exists in sheet: %s", job_url)
                        return True
                return False
            except Exception as e:
                logger.error("Error reading Google Sheet during duplicate check: %s", e)

        # Fallback to local backup
        local_data = self._read_local_data()
        for row in local_data:
            if row.get("Job URL", "").strip().rstrip("/") == job_url_clean:
                return True
        return False

    def log_new_job(self, job_dict: Dict[str, str]) -> bool:
        """
        Appends a new row with the status 'Pending Tailoring'.
        Expected job_dict keys: 'title', 'company', 'job_url', 'description'
        """
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = job_dict.get("title", "Untitled")
        company = job_dict.get("company", "Unknown")
        url = job_dict.get("job_url", "")
        # Truncate description text in cell to prevent sheet cell size overflow
        description = job_dict.get("description", "")[:1000]
        resume_path = ""
        status = "Pending Tailoring"

        row = [
            date_str,
            title,
            company,
            url,
            description,
            resume_path,
            status,
        ]

        if self.worksheet:
            try:
                self.worksheet.append_row(row)
                logger.info("Logged new job to Google Sheet: %s at %s", title, company)
                return True
            except Exception as e:
                logger.error("Error appending row to Google Sheet: %s", e)

        # Fallback to local backup
        local_data = self._read_local_data()
        entry = {
            "Date Found": date_str,
            "Job Title": title,
            "Company": company,
            "Job URL": url,
            "Job Description (Context)": description,
            "Tailored Resume Path": resume_path,
            "Application Status": status,
        }
        local_data.append(entry)
        self._write_local_data(local_data)
        logger.info("Logged new job to local backup: %s at %s", title, company)
        return True

    def update_status(self, job_url: str, new_status: str, resume_path: Optional[str] = None) -> bool:
        """
        Updates the row matching job_url with new_status and optionally new resume_path.
        """
        job_url_clean = (job_url or "").strip().rstrip("/")

        if self.worksheet:
            try:
                headers = self.worksheet.row_values(1)
                url_col = headers.index("Job URL") + 1 if "Job URL" in headers else 4
                status_col = headers.index("Application Status") + 1 if "Application Status" in headers else 7
                resume_col = headers.index("Tailored Resume Path") + 1 if "Tailored Resume Path" in headers else 6

                urls = self.worksheet.col_values(url_col)
                for row_idx, url in enumerate(urls[1:], start=2):
                    if url.strip().rstrip("/") == job_url_clean:
                        self.worksheet.update_cell(row_idx, status_col, new_status)
                        if resume_path:
                            self.worksheet.update_cell(row_idx, resume_col, resume_path)
                        logger.info("Updated Google Sheet row %d: Status -> %s", row_idx, new_status)
                        return True
            except Exception as e:
                logger.error("Error updating cell in Google Sheet: %s", e)

        # Fallback to local backup
        local_data = self._read_local_data()
        updated = False
        for entry in local_data:
            if entry.get("Job URL", "").strip().rstrip("/") == job_url_clean:
                entry["Application Status"] = new_status
                if resume_path:
                    entry["Tailored Resume Path"] = resume_path
                updated = True
                break

        if updated:
            self._write_local_data(local_data)
            logger.info("Updated local backup: Status -> %s for %s", new_status, job_url)
            return True

        logger.warning("Job URL not found for status update: %s", job_url)
        return False


# Singleton instance and standalone function bindings as specified in requirements
_default_manager: Optional[SheetManager] = None


def get_manager() -> SheetManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = SheetManager()
    return _default_manager


def check_if_job_exists(job_url: str) -> bool:
    """Wrapper function conforming directly to project specification."""
    return get_manager().check_if_job_exists(job_url)


def log_new_job(job_dict: Dict[str, str]) -> bool:
    """Wrapper function conforming directly to project specification."""
    return get_manager().log_new_job(job_dict)


def update_status(job_url: str, new_status: str, resume_path: Optional[str] = None) -> bool:
    """Wrapper function conforming directly to project specification."""
    return get_manager().update_status(job_url, new_status, resume_path)


if __name__ == "__main__":
    print("Testing sheet_manager module...")
    mgr = get_manager()
    test_url = "https://example.com/test-job-99"
    print(f"Exists before: {check_if_job_exists(test_url)}")
    log_new_job({
        "title": "Senior AI Engineer",
        "company": "DeepMind Partner",
        "job_url": test_url,
        "description": "Seeking expert in PyTorch, transformers, and vision models."
    })
    print(f"Exists after: {check_if_job_exists(test_url)}")
    update_status(test_url, "Tailored", "output/tailored_resume_test.pdf")
