"""
Script to capture high-resolution screenshots of the dashboard for GitHub documentation.
Saves screenshots into assets/screenshots/.
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets" / "screenshots"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


async def capture_dashboard_views():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 960},
            device_scale_factor=1.5,
        )
        page = await context.new_page()

        print("[1/5] Navigating to dashboard overview...")
        await page.goto("http://127.0.0.1:8000", wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # 1. Main Dashboard Overview
        overview_path = ASSETS_DIR / "dashboard_overview.png"
        await page.screenshot(path=str(overview_path), full_page=False)
        print(f"Captured: {overview_path}")

        # 2. Application Tracker Table Tab
        print("[2/5] Capturing Application Tracker tab...")
        await page.click("button:has-text('Application Tracker')")
        await page.wait_for_timeout(1500)
        tracker_path = ASSETS_DIR / "application_tracker.png"
        await page.screenshot(path=str(tracker_path), full_page=False)
        print(f"Captured: {tracker_path}")

        # 3. Audit Screenshots Gallery Tab
        print("[3/5] Capturing Audit Screenshots Gallery tab...")
        await page.click("button:has-text('Audit Screenshots Gallery')")
        await page.wait_for_timeout(1500)
        gallery_path = ASSETS_DIR / "audit_gallery.png"
        await page.screenshot(path=str(gallery_path), full_page=False)
        print(f"Captured: {gallery_path}")

        # 4. Target Career Registry Tab
        print("[4/5] Capturing Target Career Registry tab...")
        await page.click("button:has-text('Target Career Registry')")
        await page.wait_for_timeout(1000)
        targets_path = ASSETS_DIR / "target_registry.png"
        await page.screenshot(path=str(targets_path), full_page=False)
        print(f"Captured: {targets_path}")

        # 5. Master Resume Editor Tab
        print("[5/5] Capturing Master Resume Editor tab...")
        await page.click("button:has-text('Master Resume')")
        await page.wait_for_timeout(1000)
        resume_path = ASSETS_DIR / "master_resume_editor.png"
        await page.screenshot(path=str(resume_path), full_page=False)
        print(f"Captured: {resume_path}")

        await browser.close()
        print("All dashboard screenshots captured successfully.")


if __name__ == "__main__":
    asyncio.run(capture_dashboard_views())
