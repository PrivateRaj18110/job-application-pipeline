"""
Module 4: apply_bot.py
Automated End-to-End Application Submission Engine using Playwright.
Navigates to job applications, fills candidate profile details with realistic human typing delays,
uploads tailored PDF resumes, handles consent checkboxes, executes auto-submission with verification,
detects CAPTCHAs and complex questionnaires, and saves visual audit screenshots.

All file operations and screenshot outputs are strictly anchored to the project workspace.
"""

import os
import re
import random
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple, Optional
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeoutError

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Workspace Root Anchoring
BASE_DIR = Path(__file__).resolve().parent
SCREENSHOTS_DIR = BASE_DIR / "logs" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Applicant profile (Source of truth: Master Resume)
DEFAULT_APPLICANT = {
    "full_name": os.getenv("APPLICANT_FULL_NAME", "Alex Rivera"),
    "first_name": os.getenv("APPLICANT_FIRST_NAME", "Alex"),
    "last_name": os.getenv("APPLICANT_LAST_NAME", "Rivera"),
    "email": os.getenv("APPLICANT_EMAIL", "alex.rivera.dev@example.com"),
    "phone": os.getenv("APPLICANT_PHONE", "+1-555-0199"),
    "linkedin": os.getenv("APPLICANT_LINKEDIN", "https://www.linkedin.com/in/alexrivera-dev"),
    "github": os.getenv("APPLICANT_GITHUB", "https://github.com/alexrivera-dev"),
    "portfolio": os.getenv("APPLICANT_PORTFOLIO", "https://alexrivera.dev"),
    "location": "San Francisco, CA",
}


def _make_job_slug(url_or_title: str) -> str:
    """Generate a sanitized filename slug for logging & screenshot tracking."""
    slug = re.sub(r"[^\w\-_]", "_", url_or_title)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:40] if slug else "job_application"


async def _human_type(page: Page, selector: str, text: str, field_name: str) -> bool:
    """Fills an input field with human-like keystroke pacing."""
    try:
        elem = await page.query_selector(selector)
        if elem and await elem.is_visible():
            await elem.click()
            await elem.fill("")  # Clear existing content
            delay_ms = random.randint(30, 60)
            await elem.press_sequentially(text, delay=delay_ms)
            logger.info("Filled %s via %s (human delay: %dms)", field_name, selector, delay_ms)
            return True
    except Exception as e:
        logger.debug("Failed typing into %s (%s): %s", field_name, selector, e)
    return False


async def _fill_field(page: Page, selectors: list[str], value: str, field_name: str) -> bool:
    """Tries multiple candidate selectors to locate and fill a specific profile attribute."""
    for selector in selectors:
        if await _human_type(page, selector, value, field_name):
            return True
    return False


async def _take_audit_screenshot(page: Page, job_slug: str, status_tag: str) -> str:
    """Captures and saves a full-page audit screenshot in logs/screenshots/."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_file = SCREENSHOTS_DIR / f"{job_slug}_{status_tag}_{timestamp}.png"
    try:
        await page.screenshot(path=str(screenshot_file), full_page=True)
        logger.info("Saved visual audit screenshot: %s", screenshot_file)
        return str(screenshot_file.resolve())
    except Exception as e:
        logger.warning("Could not capture full-page screenshot (%s), attempting viewport snapshot...", e)
        try:
            await page.screenshot(path=str(screenshot_file), full_page=False)
            return str(screenshot_file.resolve())
        except Exception as e2:
            logger.error("Screenshot capture failed: %s", e2)
            return ""


async def _check_anti_bot_or_captcha(page: Page) -> Tuple[bool, str]:
    """Detects CAPTCHAs, Cloudflare turnstile, and blocking mechanisms."""
    captcha_selectors = [
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        "iframe[src*='challenges.cloudflare.com']",
        ".g-recaptcha",
        ".h-captcha",
        "#cf-turnstile",
        "div[id*='turnstile']",
    ]

    for sel in captcha_selectors:
        elem = await page.query_selector(sel)
        if elem and await elem.is_visible():
            return True, f"CAPTCHA detected matching selector: {sel}"

    # Text-based detection
    page_text = (await page.inner_text("body")).lower() if await page.query_selector("body") else ""
    if "verify you are human" in page_text or "recaptcha" in page_text:
        return True, "Cloudflare or human challenge text detected"

    return False, ""


async def _check_unmapped_questionnaire(page: Page) -> Tuple[bool, str]:
    """Detects complex multi-stage quizzes, coding tests, or extensive required questions."""
    # Look for extensive mandatory textareas or radio groups that require custom answers
    req_textareas = await page.query_selector_all("textarea[required]")
    if len(req_textareas) > 3:
        return True, f"Complex questionnaire detected ({len(req_textareas)} required essay fields)"

    # Check for multi-step wizards requiring interactive pagination
    wizards = await page.query_selector_all(".wizard-step, .multi-step, [data-qa='survey-step']")
    if len(wizards) > 1:
        return True, "Multi-stage application questionnaire detected"

    return False, ""


async def apply_to_job(
    target_url: str,
    pdf_path: str,
    applicant_data: Optional[Dict[str, str]] = None,
    auto_submit: Optional[bool] = None,
    headless: Optional[bool] = None,
) -> Tuple[bool, str, str]:
    """
    Automated End-to-End Application Bot.
    Args:
        target_url: URL to the application form
        pdf_path: Path to the generated role-tailored PDF resume
        applicant_data: Custom applicant information override
        auto_submit: True for live final submission, False for dry-run
        headless: True for background headless operation
    Returns:
        (success: bool, final_status_tag: str, screenshot_path: str)
    """
    if auto_submit is None:
        auto_submit = os.getenv("AUTO_SUBMIT", "true").lower() in ("true", "1", "yes")

    if headless is None:
        headless = os.getenv("HEADLESS_BROWSER", "true").lower() in ("true", "1", "yes")

    data = {**DEFAULT_APPLICANT, **(applicant_data or {})}
    resolved_pdf = Path(pdf_path).resolve()
    job_slug = _make_job_slug(target_url)

    if not resolved_pdf.exists():
        msg = f"Resume PDF not found at path: {pdf_path}"
        logger.error(msg)
        return False, "Failed - Needs Manual Check", ""

    logger.info("Executing apply_bot on: %s (Auto-submit: %s, Headless: %s)", target_url, auto_submit, headless)

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/New_York",
        )

        page: Page = await context.new_page()

        try:
            # 1. Navigate to target URL
            logger.info("Navigating to application URL: %s", target_url)
            await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)

            # 2. Check for anti-bot / CAPTCHA challenge
            is_captcha, captcha_reason = await _check_anti_bot_or_captcha(page)
            if is_captcha:
                logger.warning("Anti-bot protection triggered: %s", captcha_reason)
                shot = await _take_audit_screenshot(page, job_slug, "blocked_captcha")
                await browser.close()
                return False, "Blocked - CAPTCHA / Questionnaire", shot

            # 3. Check for modal or 'Apply' trigger button if not directly on the form
            apply_triggers = [
                "a[href*='#apply']",
                "a[href*='/apply']",
                "button:has-text('Apply Now')",
                "button:has-text('Apply for this job')",
                "a:has-text('Apply Now')",
                "a:has-text('Apply for this job')",
            ]
            for trigger in apply_triggers:
                try:
                    btn = await page.query_selector(trigger)
                    if btn and await btn.is_visible():
                        logger.info("Triggering application form modal/section: %s", trigger)
                        await btn.click()
                        await page.wait_for_timeout(2000)
                        break
                except Exception:
                    pass

            # 4. Check for complex multi-stage questionnaire
            is_complex, complex_reason = await _check_unmapped_questionnaire(page)
            if is_complex:
                logger.warning("Complex questionnaire detected: %s", complex_reason)
                shot = await _take_audit_screenshot(page, job_slug, "questionnaire_blocked")
                await browser.close()
                return False, "Blocked - CAPTCHA / Questionnaire", shot

            # 5. Fill standard applicant profile fields
            # Full Name or Split First/Last Name
            filled_full_name = await _fill_field(
                page,
                [
                    "input[name*='name' i]:not([name*='first']):not([name*='last'])",
                    "input[id*='name' i]:not([id*='first']):not([id*='last'])",
                    "input[autocomplete='name']",
                    "#name",
                    "[data-qa='name-input']",
                ],
                data["full_name"],
                "Full Name",
            )

            if not filled_full_name:
                await _fill_field(
                    page,
                    ["input[name*='first' i]", "input[id*='first' i]", "#first_name", "[data-qa='first-name']"],
                    data["first_name"],
                    "First Name",
                )
                await _fill_field(
                    page,
                    ["input[name*='last' i]", "input[id*='last' i]", "#last_name", "[data-qa='last-name']"],
                    data["last_name"],
                    "Last Name",
                )

            # Email
            await _fill_field(
                page,
                [
                    "input[type='email']",
                    "input[name*='email' i]",
                    "input[id*='email' i]",
                    "#email",
                    "[data-qa='email-input']",
                ],
                data["email"],
                "Email",
            )

            # Phone
            await _fill_field(
                page,
                [
                    "input[type='tel']",
                    "input[name*='phone' i]",
                    "input[id*='phone' i]",
                    "#phone",
                    "[data-qa='phone-input']",
                ],
                data["phone"],
                "Phone",
            )

            # LinkedIn Profile
            await _fill_field(
                page,
                [
                    "input[name*='linkedin' i]",
                    "input[id*='linkedin' i]",
                    "input[name*='urls[LinkedIn]' i]",
                    "input[placeholder*='linkedin' i]",
                ],
                data["linkedin"],
                "LinkedIn",
            )

            # GitHub Profile
            await _fill_field(
                page,
                [
                    "input[name*='github' i]",
                    "input[id*='github' i]",
                    "input[name*='urls[GitHub]' i]",
                    "input[placeholder*='github' i]",
                ],
                data["github"],
                "GitHub",
            )

            # Portfolio / Website
            await _fill_field(
                page,
                [
                    "input[name*='portfolio' i]",
                    "input[name*='website' i]",
                    "input[name*='urls[Portfolio]' i]",
                    "input[placeholder*='portfolio' i]",
                    "input[placeholder*='website' i]",
                ],
                data["portfolio"],
                "Portfolio",
            )

            # 6. Upload Tailored PDF Resume
            file_input = await page.query_selector(
                "input[type='file'][name*='resume' i], "
                "input[type='file'][id*='resume' i], "
                "input[type='file'][data-qa*='resume' i], "
                "input[type='file']"
            )

            if file_input:
                logger.info("Uploading tailored PDF: %s", resolved_pdf.name)
                await file_input.set_input_files(str(resolved_pdf))
                await page.wait_for_timeout(2000)
            else:
                logger.warning("No file input located on page: %s", target_url)

            # 7. Check Mandatory Consent / Privacy Checkboxes
            checkbox_selectors = [
                "input[type='checkbox'][name*='consent' i]",
                "input[type='checkbox'][name*='privacy' i]",
                "input[type='checkbox'][name*='terms' i]",
                "input[type='checkbox'][name*='agree' i]",
                "input[type='checkbox'][data-qa*='consent']",
                "input[type='checkbox'][required]",
            ]

            for cb_sel in checkbox_selectors:
                checkboxes = await page.query_selector_all(cb_sel)
                for cb in checkboxes:
                    try:
                        if not await cb.is_checked():
                            await cb.check(force=True)
                            logger.info("Checked mandatory consent checkbox: %s", cb_sel)
                    except Exception:
                        pass

            await page.wait_for_timeout(1500)

            # 8. Submission Verification / Dry-Run Branch
            if not auto_submit:
                logger.info("AUTO_SUBMIT is False (Safe Dry-Run). Staged form fields and captured screenshot.")
                screenshot_path = await _take_audit_screenshot(page, job_slug, "dryrun_verified")
                await browser.close()
                return True, "Staged (Dry-run verified)", screenshot_path

            # Auto-Submit = True (Unattended Live Application)
            submit_selectors = [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Submit Application')",
                "button:has-text('Submit application')",
                "button:has-text('Submit')",
                "#submit_app",
                "[data-qa='btn-submit']",
            ]

            submit_btn = None
            for s_sel in submit_selectors:
                elem = await page.query_selector(s_sel)
                if elem and await elem.is_visible():
                    submit_btn = elem
                    logger.info("Found submit button using selector: %s", s_sel)
                    break

            if not submit_btn:
                logger.warning("Submit button could not be found.")
                screenshot_path = await _take_audit_screenshot(page, job_slug, "no_submit_btn")
                await browser.close()
                return False, "Failed - Needs Manual Check", screenshot_path

            logger.info("Clicking final submit button...")
            await submit_btn.click()

            # Wait for confirmation or navigation
            try:
                await page.wait_for_timeout(5000)
                page_content = (await page.inner_text("body")).lower()

                success_indicators = [
                    "thank you",
                    "application submitted",
                    "received your application",
                    "we have received",
                    "success",
                    "your application has been sent",
                ]

                has_confirmed = any(ind in page_content for ind in success_indicators)
                current_url = page.url.lower()
                redirect_confirmed = any(kw in current_url for kw in ["confirm", "thanks", "applied", "success"])

                if has_confirmed or redirect_confirmed:
                    logger.info("Application submission verified successfully!")
                    screenshot_path = await _take_audit_screenshot(page, job_slug, "applied_success")
                    await browser.close()
                    return True, "Applied", screenshot_path
                else:
                    logger.warning("Submission clicked, but explicit confirmation banner was not detected.")
                    screenshot_path = await _take_audit_screenshot(page, job_slug, "submit_unconfirmed")
                    await browser.close()
                    return True, "Applied (Pending Confirmation)", screenshot_path

            except Exception as wait_err:
                logger.warning("Error waiting for submission response: %s", wait_err)
                screenshot_path = await _take_audit_screenshot(page, job_slug, "submit_timeout")
                await browser.close()
                return False, "Failed - Needs Manual Check", screenshot_path

        except PlaywrightTimeoutError as te:
            logger.error("Navigation / Action timeout on %s: %s", target_url, te)
            screenshot_path = await _take_audit_screenshot(page, job_slug, "timeout_error")
            await browser.close()
            return False, "Failed - Needs Manual Check", screenshot_path

        except Exception as e:
            logger.exception("Unexpected error in apply_bot: %s", e)
            screenshot_path = await _take_audit_screenshot(page, job_slug, "fatal_error")
            await browser.close()
            return False, "Failed - Needs Manual Check", screenshot_path


if __name__ == "__main__":
    import asyncio

    async def _test():
        print("Testing upgraded apply_bot module...")
        test_pdf = BASE_DIR / "output" / "test_verification.pdf"
        test_pdf.parent.mkdir(parents=True, exist_ok=True)
        if not test_pdf.exists():
            test_pdf.write_text("Verification PDF content")
        success, status, shot = await apply_to_job(
            "https://example.com",
            str(test_pdf),
            auto_submit=False,
        )
        print(f"Result: success={success}, status='{status}', screenshot='{shot}'")

    asyncio.run(_test())
