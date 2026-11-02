"""
Module 1: scraper.py
Job Discovery module using Playwright (async).
Scrapes job listings and details from generic target sites such as Greenhouse,
Lever, Y Combinator, or direct job posting URLs.
"""

import re
import asyncio
import logging
from typing import Callable, List, Dict, Optional
from urllib.parse import urljoin
from playwright.async_api import async_playwright, Page, Browser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


JobFilter = Callable[[str, str], bool]  # (title, location) -> keep?


async def _greenhouse_location(elem, anchor_text: str) -> str:
    """Location of a Greenhouse listing: its location node (old and new board layouts), else extra anchor lines."""
    try:
        location = await elem.evaluate(
            """el => {
                const box = el.closest('.opening, tr, .job-post') || el;
                const node = box.querySelector('.location, .body--metadata, .job-post-location');
                return node ? node.innerText : '';
            }"""
        )
    except Exception:
        location = ""
    if not (location or "").strip():
        location = " | ".join(line.strip() for line in anchor_text.split("\n")[1:] if line.strip())
    return " ".join(location.split())


def _with_location(description: str, location: str) -> str:
    """Prefixes the description with the listing location so it shows up in the tracker."""
    return f"Location: {location}\n\n{description}" if location else description


async def _extract_greenhouse_jobs(
    page: Page, base_url: str, max_jobs: int, job_filter: Optional[JobFilter] = None
) -> List[Dict[str, str]]:
    """Extract jobs from a Greenhouse job board (boards.greenhouse.io)."""
    jobs: List[Dict[str, str]] = []
    company_elem = await page.query_selector("h1, .company-name, #header h1")
    company_name = (await company_elem.inner_text()).strip() if company_elem else "Unknown Company"

    opening_elements = await page.query_selector_all(
        ".opening a, tr.job a, div.opening a, a[href*='/jobs/'], a[data-mapped='true'], tr.job-post a"
    )
    job_links: List[tuple[str, str, str]] = []
    seen_urls = set()
    skipped = 0

    for elem in opening_elements:
        href = await elem.get_attribute("href")
        anchor_text = (await elem.inner_text()).strip()
        title = anchor_text.split("\n")[0].strip()
        if href and title and href not in seen_urls and "/jobs/" in href:
            seen_urls.add(href)
            location = await _greenhouse_location(elem, anchor_text)
            if job_filter and not job_filter(title, location):
                skipped += 1
                continue
            full_url = urljoin(base_url, href)
            job_links.append((title, full_url, location))
        if len(job_links) >= max_jobs:
            break

    logger.info("Found %d matching job links on Greenhouse board (%d skipped by role/location filters)",
                len(job_links), skipped)

    for title, url, location in job_links:
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
                "location": location,
                "description": _with_location(desc_text[:4000], location),  # Keep clean context length
                "job_url": url,
            })
        except Exception as e:
            logger.warning("Failed to scrape Greenhouse job details at %s: %s", url, e)

    return jobs


async def _extract_lever_jobs(
    page: Page, base_url: str, max_jobs: int, job_filter: Optional[JobFilter] = None
) -> List[Dict[str, str]]:
    """Extract jobs from a Lever job board (jobs.lever.co)."""
    jobs: List[Dict[str, str]] = []
    company_elem = await page.query_selector(".main-header-logo-container img, .header-logo")
    company_name = "Unknown Company"
    if company_elem:
        company_name = (await company_elem.get_attribute("alt")) or "Unknown Company"

    posting_elements = await page.query_selector_all("a.posting-title")
    job_links: List[tuple[str, str, str]] = []
    skipped = 0

    for elem in posting_elements:
        href = await elem.get_attribute("href")
        title_elem = await elem.query_selector("h5")
        title = (await title_elem.inner_text()).strip() if title_elem else (await elem.inner_text()).strip().split("\n")[0]
        location_elem = await elem.query_selector(".sort-by-location, .location")
        location = " ".join((await location_elem.inner_text()).split()) if location_elem else ""
        if not href:
            continue
        if job_filter and not job_filter(title, location):
            skipped += 1
            continue
        job_links.append((title, urljoin(base_url, href), location))
        if len(job_links) >= max_jobs:
            break

    logger.info("Found %d matching job links on Lever board (%d skipped by role/location filters)",
                len(job_links), skipped)

    for title, url, location in job_links:
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
                "location": location,
                "description": _with_location(desc_text[:4000], location),
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


def _contains_phrase(text: str, phrase: str) -> bool:
    """Whole-word, case-insensitive phrase match: "AI" matches "AI Engineer" but not "email"."""
    pattern = rf"(?<![a-z0-9]){re.escape(phrase.lower().strip())}(?![a-z0-9])"
    return re.search(pattern, text.lower()) is not None


def matches_keywords(
    title: str,
    keywords: Optional[List[str]],
    exclude_keywords: Optional[List[str]] = None,
) -> bool:
    """
    Role matching on the job title: at least one keyword phrase must appear as whole words,
    and no exclude phrase (e.g. seniority such as "Senior" or "Staff") may appear.
    """
    if exclude_keywords and any(_contains_phrase(title, kw) for kw in exclude_keywords):
        return False
    if not keywords:
        return True
    return any(_contains_phrase(title, kw) for kw in keywords)


# Words that may accompany a remote term without tying the role to a specific country or city
REMOTE_QUALIFIERS = {
    "friendly", "first", "fully", "only", "global", "globally", "worldwide", "anywhere",
    "apac", "asia", "pacific", "work", "from", "home", "or", "and", "in", "the", "world",
}


def location_allowed(location: str, location_filter: Optional[Dict]) -> bool:
    """
    True when a listing's location is acceptable:
    - it names an allowed place (e.g. India or an Indian city), or
    - it is remote with no other place attached ("Remote", "Remote - APAC"), so
      "San Francisco, CA | Remote-Friendly" and "Remote, US" are rejected.
    Listings without a location are kept, since there is nothing to judge.
    """
    if not location_filter or not location_filter.get("enabled", True) or not location.strip():
        return True
    if any(_contains_phrase(location, place) for place in location_filter.get("allowed", [])):
        return True

    remote_terms = location_filter.get("remote_terms", [])
    if any(_contains_phrase(location, term) for term in remote_terms):
        neutral = REMOTE_QUALIFIERS | {w for term in remote_terms for w in re.findall(r"[a-z]+", term.lower())}
        return all(word in neutral for word in re.findall(r"[a-z]+", location.lower()))
    return False


async def scrape_jobs(
    target_url: str,
    max_jobs: int = 5,
    role_keywords: Optional[List[str]] = None,
    headless: bool = True,
    exclude_keywords: Optional[List[str]] = None,
    location_filter: Optional[Dict] = None,
) -> List[Dict[str, str]]:
    """
    Scrapes jobs from the target URL and applies role keyword and location filtering.
    On job boards, listings are filtered before their pages are opened, so max_jobs counts matching roles only.
    Returns:
        List of dicts: [{"title": str, "company": str, "location": str, "description": str, "job_url": str}, ...]
    """
    logger.info("Initiating scrape on %s (max_jobs=%d, keywords=%s, excluded=%s, location filter=%s)",
                target_url, max_jobs, role_keywords, exclude_keywords,
                "on" if location_filter and location_filter.get("enabled", True) else "off")
    raw_results: List[Dict[str, str]] = []

    def job_filter(title: str, location: str) -> bool:
        return matches_keywords(title, role_keywords, exclude_keywords) and location_allowed(location, location_filter)

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
                raw_results = await _extract_greenhouse_jobs(page, target_url, max_jobs, job_filter)
            elif "lever.co" in target_url:
                raw_results = await _extract_lever_jobs(page, target_url, max_jobs, job_filter)
            else:
                # Check if it has multiple job openings or is a single job page
                job_links = await page.query_selector_all("a[href*='/job/'], a[href*='/jobs/'], a[href*='/apply']")
                if len(job_links) > 1:
                    logger.info("Found %d generic job links, scraping list...", len(job_links))
                    extracted_urls = []
                    for link in job_links:
                        href = await link.get_attribute("href")
                        title = (await link.inner_text()).strip() or "Software Engineer"
                        if href and job_filter(title, ""):
                            full_url = urljoin(target_url, href)
                            extracted_urls.append((title, full_url))
                        if len(extracted_urls) >= max_jobs:
                            break

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
        if job_filter(j.get("title", ""), j.get("location", "")):
            filtered_results.append(j)
        else:
            logger.info("Filtered out job '%s' (did not match target roles or locations)", j.get("title", ""))

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

    matched = [j for j in all_mock if matches_keywords(j["title"], role_keywords)]
    return matched if matched else all_mock


if __name__ == "__main__":
    print("Testing scraper module...")
    sample_jobs = get_mock_jobs(["Python", "Vision"])
    for job in sample_jobs:
        print(f"[*] Title: {job['title']} | Company: {job['company']}")
        print(f"    URL: {job['job_url']}\n")

