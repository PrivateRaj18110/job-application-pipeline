"""
Module 1: scraper.py
Job Discovery module using Playwright (async).
Scrapes job listings and details from generic target sites such as Greenhouse,
Lever, Y Combinator, or direct job posting URLs.
"""

import asyncio
import logging
from typing import List, Dict, Optional
from urllib.parse import urljoin
from playwright.async_api import async_playwright, Page, Browser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def _extract_greenhouse_jobs(page: Page, base_url: str, max_jobs: int) -> List[Dict[str, str]]:
    """Extract jobs from a Greenhouse job board (boards.greenhouse.io)."""
    jobs: List[Dict[str, str]] = []
    company_elem = await page.query_selector("h1, .company-name, #header h1")
    company_name = (await company_elem.inner_text()).strip() if company_elem else "Unknown Company"

    opening_elements = await page.query_selector_all(
        ".opening a, tr.job a, div.opening a, a[href*='/jobs/'], a[data-mapped='true'], tr.job-post a"
    )
    job_links: List[tuple[str, str]] = []
    seen_urls = set()

    for elem in opening_elements:
        href = await elem.get_attribute("href")
        title = (await elem.inner_text()).strip()
        if href and title and href not in seen_urls and "/jobs/" in href:
            seen_urls.add(href)
            full_url = urljoin(base_url, href)
            job_links.append((title, full_url))
        if len(job_links) >= max_jobs:
            break

    logger.info("Found %d job links on Greenhouse board", len(job_links))

    for title, url in job_links:
        try:
            logger.info("Scraping job details: %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1000)

            # Get description
            content_elem = await page.query_selector("#content, #app, .job-post, main, body")
            desc_text = (await content_elem.inner_text()).strip() if content_elem else ""

            jobs.append({
                "title": title,
                "company": company_name,
                "description": desc_text[:4000],  # Keep clean context length
                "job_url": url,
            })
        except Exception as e:
            logger.warning("Failed to scrape Greenhouse job details at %s: %s", url, e)

    return jobs


async def _extract_lever_jobs(page: Page, base_url: str, max_jobs: int) -> List[Dict[str, str]]:
    """Extract jobs from a Lever job board (jobs.lever.co)."""
    jobs: List[Dict[str, str]] = []
    company_elem = await page.query_selector(".main-header-logo-container img, .header-logo")
    company_name = "Unknown Company"
    if company_elem:
        company_name = (await company_elem.get_attribute("alt")) or "Unknown Company"

    posting_elements = await page.query_selector_all("a.posting-title")
    job_links: List[tuple[str, str]] = []

    for elem in posting_elements:
        href = await elem.get_attribute("href")
        title_elem = await elem.query_selector("h5")
        title = (await title_elem.inner_text()).strip() if title_elem else (await elem.inner_text()).strip()
        if href:
            full_url = urljoin(base_url, href)
            job_links.append((title, full_url))
        if len(job_links) >= max_jobs:
            break

    logger.info("Found %d job links on Lever board", len(job_links))

    for title, url in job_links:
        try:
            logger.info("Scraping job details: %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1000)

            content_elem = await page.query_selector(".content, .section-wrapper, body")
            desc_text = (await content_elem.inner_text()).strip() if content_elem else ""

            apply_btn = await page.query_selector("a.postings-btn[href*='apply'], a[data-qa='btn-apply']")
            apply_url = url
            if apply_btn:
                apply_href = await apply_btn.get_attribute("href")
                if apply_href:
                    apply_url = urljoin(url, apply_href)

            jobs.append({
                "title": title,
                "company": company_name,
                "description": desc_text[:4000],
                "job_url": apply_url,
            })
        except Exception as e:
            logger.warning("Failed to scrape Lever job details at %s: %s", url, e)

    return jobs


async def _extract_single_job_page(page: Page, url: str) -> List[Dict[str, str]]:
    """Fallback parser for direct single job postings."""
    # Extract Title
    title = ""
    for selector in ["h1", "[data-automation-id='jobTitle']", ".job-title", "title"]:
        elem = await page.query_selector(selector)
        if elem:
            title = (await elem.inner_text()).strip()
            if title:
                break
    if not title:
        title = await page.title()

    # Extract Company
    company = ""
    for selector in [".company", ".company-name", "[data-company]", "meta[property='og:site_name']"]:
        elem = await page.query_selector(selector)
        if elem:
            if selector.startswith("meta"):
                company = (await elem.get_attribute("content") or "").strip()
            else:
                company = (await elem.inner_text()).strip()
            if company:
                break
    if not company:
        company = "Target Employer"

    # Extract Description
    desc_elem = await page.query_selector("article, main, #job-description, .description, body")
    description = (await desc_elem.inner_text()).strip() if desc_elem else ""

    return [{
        "title": title[:100],
        "company": company[:100],
        "description": description[:4000],
        "job_url": url,
    }]


from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def matches_keywords(title: str, description: str, keywords: Optional[List[str]]) -> bool:
    """Checks whether the job title or description matches any of the target keywords."""
    if not keywords:
        return True
    haystack = f"{title} {description}".lower()
    return any(kw.lower() in haystack for kw in keywords)


async def scrape_jobs(
    target_url: str,
    max_jobs: int = 5,
    role_keywords: Optional[List[str]] = None,
    headless: bool = True,
) -> List[Dict[str, str]]:
    """
    Scrapes jobs from the target URL and applies role keyword filtering.
    Returns:
        List of dicts: [{"title": str, "company": str, "description": str, "job_url": str}, ...]
    """
    logger.info("Initiating scrape on %s (max_jobs=%d, keywords=%s)", target_url, max_jobs, role_keywords)
    raw_results: List[Dict[str, str]] = []

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        page: Page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2000)

            # Heuristics based on URL domain / structure
            if "greenhouse.io" in target_url:
                raw_results = await _extract_greenhouse_jobs(page, target_url, max_jobs)
            elif "lever.co" in target_url:
                raw_results = await _extract_lever_jobs(page, target_url, max_jobs)
            else:
                # Check if it has multiple job openings or is a single job page
                job_links = await page.query_selector_all("a[href*='/job/'], a[href*='/jobs/'], a[href*='/apply']")
                if len(job_links) > 1:
                    logger.info("Found %d generic job links, scraping list...", len(job_links))
                    extracted_urls = []
                    for link in job_links[:max_jobs]:
                        href = await link.get_attribute("href")
                        title = (await link.inner_text()).strip() or "Software Engineer"
                        if href:
                            full_url = urljoin(target_url, href)
                            extracted_urls.append((title, full_url))

                    for title, url in extracted_urls:
                        try:
                            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                            page_desc = await _extract_single_job_page(page, url)
                            if page_desc:
                                page_desc[0]["title"] = title if title else page_desc[0]["title"]
                                raw_results.append(page_desc[0])
                        except Exception as ex:
                            logger.warning("Error fetching sub-job page %s: %s", url, ex)
                else:
                    raw_results = await _extract_single_job_page(page, target_url)

        except Exception as e:
            logger.error("Error while navigating or scraping %s: %s", target_url, e)
        finally:
            await browser.close()

    # Filter jobs by role keywords if specified
    filtered_results = []
    for j in raw_results:
        if matches_keywords(j.get("title", ""), j.get("description", ""), role_keywords):
            filtered_results.append(j)
        else:
            logger.info("Filtered out job '%s' (did not match target keywords)", j.get("title", ""))

    logger.info("Scraping completed. Extracted %d matched jobs out of %d scraped.", len(filtered_results), len(raw_results))
    return filtered_results


def get_mock_jobs(role_keywords: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Returns sample mock jobs matching candidate profile, optionally filtered by keywords."""
    all_mock = [
        {
            "title": "Machine Learning Engineer (Computer Vision / Deep Learning)",
            "company": "VisionTech AI Labs",
            "description": (
                "We are seeking an ML Engineer specializing in Computer Vision and Deep Learning. "
                "Key responsibilities include developing deep neural networks, CNNs, LSTMs, and video analysis "
                "pipelines for real-time anomaly and synthetic media detection. "
                "Requirements: Strong proficiency in Python, PyTorch, OpenCV, Data Structures, and cloud platforms. "
                "Experience with deepfake detection, model optimization, and REST API integration is a major plus."
            ),
            "job_url": "https://example.com/careers/visiontech/ml-engineer-01",
        },
        {
            "title": "Full Stack / Mobile Application Developer (Flutter & Python)",
            "company": "Apex Mobility Solutions",
            "description": (
                "Apex is building next-generation consumer apps. We are looking for a developer with hands-on "
                "experience in Flutter, Dart, Firebase, and PostgreSQL. "
                "You will design responsive mobile user interfaces, integrate authentication and payment gateways, "
                "and build backend APIs with Python/PostgreSQL. Familiarity with Figma and agile development required."
            ),
            "job_url": "https://example.com/careers/apex/mobile-dev-02",
        },
        {
            "title": "Backend Software Engineer (Python & PostgreSQL)",
            "company": "NovaCloud Systems",
            "description": (
                "NovaCloud is hiring a Backend Engineer to build robust APIs and data streaming pipelines. "
                "Requirements include Python, SQL, REST architecture, Docker, and familiarity with AI pipelines."
            ),
            "job_url": "https://example.com/careers/novacloud/backend-se-03",
        }
    ]

    if not role_keywords:
        return all_mock

    matched = [j for j in all_mock if matches_keywords(j["title"], j["description"], role_keywords)]
    return matched if matched else all_mock


if __name__ == "__main__":
    print("Testing scraper module...")
    sample_jobs = get_mock_jobs(["Python", "Vision"])
    for job in sample_jobs:
        print(f"[*] Title: {job['title']} | Company: {job['company']}")
        print(f"    URL: {job['job_url']}\n")

