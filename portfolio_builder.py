"""
Module: portfolio_builder.py
Builds the public visual CV / portfolio website from cv.json (the structured CV source of truth).
Exports portfolio/cv.json for the site, compiles portfolio/resume.pdf (also attached to cold emails),
and stamps the page title / link-preview metadata so shared links look right.

Run with:
  python portfolio_builder.py                 # rebuild portfolio/ from cv.json
  python portfolio_builder.py --sync-master   # also regenerate master_resume.md from cv.json
  python portfolio_builder.py --publish       # also publish portfolio/ to the public site repo
"""

import re
import sys
import json
import html
import shutil
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import resume_tailor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CV_FILE = BASE_DIR / "cv.json"
PORTFOLIO_DIR = BASE_DIR / "portfolio"
PORTFOLIO_CV_FILE = PORTFOLIO_DIR / "cv.json"
PORTFOLIO_PDF_FILE = PORTFOLIO_DIR / "resume.pdf"
PORTFOLIO_INDEX_FILE = PORTFOLIO_DIR / "index.html"
MASTER_RESUME_FILE = BASE_DIR / "master_resume.md"

REQUIRED_SECTIONS = ["profile", "skills", "projects", "experience", "education"]


def load_cv(cv_path: Optional[Path] = None) -> Dict[str, Any]:
    """Reads the structured CV from cv.json."""
    path = Path(cv_path) if cv_path else CV_FILE
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_cv(cv: Dict[str, Any]) -> List[str]:
    """Returns a list of human-readable problems with the CV structure (empty when valid)."""
    if not isinstance(cv, dict):
        return ["CV must be a JSON object."]

    errors = [f"Missing section '{key}'." for key in REQUIRED_SECTIONS if key not in cv]
    profile = cv.get("profile") or {}
    for field in ("name", "title", "email"):
        if not profile.get(field):
            errors.append(f"profile.{field} is required.")

    for group in cv.get("skills", []):
        if not group.get("category"):
            errors.append("Every skill group needs a 'category'.")
        for skill in group.get("items", []):
            if not skill.get("name"):
                errors.append(f"A skill in '{group.get('category')}' is missing its 'name'.")
            # Levels are optional; the site hides the meter for unrated skills
            level = skill.get("level")
            if level is not None and (not isinstance(level, int) or not 1 <= level <= 5):
                errors.append(f"Skill '{skill.get('name')}' level must be a whole number from 1 to 5.")

    slugs = set()
    for project in cv.get("projects", []):
        if not project.get("name"):
            errors.append("Every project needs a 'name'.")
        # The slug is the case-study page address: project.html?p=<slug>
        slug = project.get("slug")
        if slug is not None:
            if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
                errors.append(f"Project slug '{slug}' must be lowercase letters, digits and hyphens.")
            elif slug in slugs:
                errors.append(f"Project slug '{slug}' is used more than once.")
            slugs.add(slug)

    return errors


def save_cv(cv: Dict[str, Any], cv_path: Optional[Path] = None) -> None:
    """Validates and writes the structured CV to cv.json."""
    errors = validate_cv(cv)
    if errors:
        raise ValueError(" ".join(errors))
    path = Path(cv_path) if cv_path else CV_FILE
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cv, f, indent=2, ensure_ascii=False)
        f.write("\n")
    logger.info("[CV] Saved structured CV to %s", path.name)


def cv_to_markdown(cv: Dict[str, Any]) -> str:
    """Renders the structured CV as a markdown resume (used for the PDF and master_resume.md)."""
    profile = cv.get("profile", {})
    links = profile.get("links", {})

    contact_bits = [profile.get("email", "")]
    if profile.get("show_phone") and profile.get("phone"):
        contact_bits.append(profile["phone"])
    if profile.get("location"):
        contact_bits.append(profile["location"])
    link_labels = {"github": "GitHub", "linkedin": "LinkedIn", "portfolio": "Portfolio"}
    link_bits = [f"[{link_labels.get(label, label.title())}]({url})" for label, url in links.items() if url]

    lines = [f"# {profile.get('name', '')}", f"**{profile.get('title', '')}**", ""]
    lines.append(" | ".join([b for b in contact_bits if b] + link_bits))
    if profile.get("summary"):
        lines += ["", profile["summary"]]

    how = cv.get("how_i_build") or {}
    if how.get("intro"):
        lines += ["", "## How I Build", how["intro"]]
        if how.get("tools"):
            lines.append(f"*Tools: {', '.join(how['tools'])}*")

    if cv.get("skills"):
        lines += ["", "## Technical Skills"]
        for group in cv["skills"]:
            names = ", ".join(s["name"] for s in group.get("items", []))
            lines.append(f"- **{group['category']}**: {names}")

    if cv.get("projects"):
        lines += ["", "## Key Projects"]
        for project in cv["projects"]:
            lines += ["", f"### {project['name']}"]
            if project.get("tech"):
                lines.append(f"*Tech Stack: {', '.join(project['tech'])}*")
            project_links = project.get("links", {})
            if project_links.get("live"):
                lines.append(f"Live: [{project_links['live']}]({project_links['live']})")
            if project.get("summary"):
                lines.append(f"- {project['summary']}")
            lines += [f"- {h}" for h in project.get("highlights", [])]

    if cv.get("experience"):
        lines += ["", "## Experience"]
        for job in cv["experience"]:
            period = " – ".join(p for p in (job.get("start"), job.get("end")) if p)
            lines.append(f"- **{job.get('company', '')} | {job.get('role', '')}** ({period})")
            lines += [f"  - {h}" for h in job.get("highlights", [])]

    if cv.get("education"):
        lines += ["", "## Education"]
        for edu in cv["education"]:
            score = f" | {edu['score']}" if edu.get("score") else ""
            lines.append(f"- **{edu.get('institution', '')}** ({edu.get('year', '')})")
            lines.append(f"  {edu.get('degree', '')}{score}")
            if edu.get("details"):
                lines.append(f"  {edu['details']}")

    extras = cv.get("certifications", []) + cv.get("achievements", [])
    if extras:
        lines += ["", "## Certifications & Achievements"]
        lines += [f"- {item}" for item in extras]

    personal = []
    if profile.get("date_of_birth"):
        personal.append(f"- Date of birth: {profile['date_of_birth']}")
    if cv.get("interests"):
        personal.append(f"- Interests: {', '.join(cv['interests'])}")
    if personal:
        lines += ["", "## Personal"] + personal

    return "\n".join(lines).strip() + "\n"


def _stamp_page_metadata(cv: Dict[str, Any]) -> None:
    """Writes the candidate's name and title into the static <title> and link-preview meta tags."""
    if not PORTFOLIO_INDEX_FILE.exists():
        return
    profile = cv.get("profile", {})
    title = html.escape(f"{profile.get('name', '')} | {profile.get('title', '')}", quote=True)
    description = html.escape(profile.get("tagline") or profile.get("summary", ""), quote=True)

    page = PORTFOLIO_INDEX_FILE.read_text(encoding="utf-8")
    # Lambdas keep backslashes in CV text from being read as regex group references
    page = re.sub(r"<title>.*?</title>", lambda m: f"<title>{title}</title>", page, count=1, flags=re.S)
    for pattern, value in (
        (r'(<meta name="description" content=")[^"]*(")', description),
        (r'(<meta property="og:title" content=")[^"]*(")', title),
        (r'(<meta property="og:description" content=")[^"]*(")', description),
    ):
        page = re.sub(pattern, lambda m, v=value: f"{m.group(1)}{v}{m.group(2)}", page, count=1)
    PORTFOLIO_INDEX_FILE.write_text(page, encoding="utf-8")


def build_portfolio(cv: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Exports cv.json into the portfolio site, compiles resume.pdf, and stamps page metadata."""
    cv = cv or load_cv()
    errors = validate_cv(cv)
    if errors:
        raise ValueError(" ".join(errors))

    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    site_cv = dict(cv, generated_at=generated_at)
    if not cv.get("profile", {}).get("show_phone"):
        site_cv["profile"] = {k: v for k, v in cv["profile"].items() if k != "phone"}
    with open(PORTFOLIO_CV_FILE, "w", encoding="utf-8") as f:
        json.dump(site_cv, f, indent=2, ensure_ascii=False)

    safe_name = re.sub(r"[^\w\-]", "_", cv["profile"]["name"])
    pdf_path = resume_tailor.convert_markdown_to_pdf(
        cv_to_markdown(cv), output_filename=f"Resume_{safe_name}_Portfolio.pdf"
    )
    if pdf_path.endswith(".pdf"):
        shutil.copyfile(pdf_path, PORTFOLIO_PDF_FILE)
    else:
        logger.warning("[CV] PDF compilation failed; portfolio/resume.pdf was not updated.")

    _stamp_page_metadata(cv)
    for project in cv.get("projects", []):
        for shot in project.get("gallery", []):
            if not (PORTFOLIO_DIR / shot.get("src", "")).is_file():
                logger.warning("[CV] %s: gallery image %s is missing from portfolio/", project["name"], shot.get("src"))
    logger.info("[OK] Portfolio rebuilt from cv.json (%d projects, %d skill groups)",
                len(cv.get("projects", [])), len(cv.get("skills", [])))
    return {
        "generated_at": generated_at,
        "cv_path": str(PORTFOLIO_CV_FILE),
        "pdf_path": str(PORTFOLIO_PDF_FILE) if PORTFOLIO_PDF_FILE.exists() else "",
    }


def sync_master_resume(cv: Optional[Dict[str, Any]] = None) -> str:
    """Regenerates master_resume.md (the tailoring ground truth) from cv.json."""
    cv = cv or load_cv()
    content = cv_to_markdown(dict(cv, profile=dict(cv["profile"], show_phone=True)))
    MASTER_RESUME_FILE.write_text(content, encoding="utf-8")
    logger.info("[CV] master_resume.md regenerated from cv.json")
    return str(MASTER_RESUME_FILE)


def main():
    parser = argparse.ArgumentParser(description="Build the portfolio website from cv.json")
    parser.add_argument("--sync-master", action="store_true", help="Also regenerate master_resume.md from cv.json")
    parser.add_argument("--publish", action="store_true", help="Also publish portfolio/ to the public site repository")
    args = parser.parse_args()

    try:
        result = build_portfolio()
        print(f"Portfolio built at {PORTFOLIO_DIR} ({result['generated_at']})")
        if args.sync_master:
            print(f"Master resume regenerated: {sync_master_resume()}")
        if args.publish:
            import publish_site
            print(publish_site.publish())
    except (ValueError, FileNotFoundError, RuntimeError, json.JSONDecodeError) as e:
        print(f"Build failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
