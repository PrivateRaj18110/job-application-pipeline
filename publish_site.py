"""
Module: publish_site.py
Publishes the built portfolio/ folder to its own public GitHub Pages repository,
so recruiters see only the site and the CV while this pipeline repository stays private.

The site repo is cloned into site_repo/ (gitignored). Each publish mirrors portfolio/ into it,
commits only when something changed, and pushes; GitHub Pages serves the main branch.

Run with:
  python portfolio_builder.py --sync-master --publish   # rebuild, then publish
  python publish_site.py                                # publish the current portfolio/
"""

import shutil
import logging
import subprocess
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
PORTFOLIO_DIR = BASE_DIR / "portfolio"
SITE_DIR = BASE_DIR / "site_repo"
SITE_REPO_URL = "https://github.com/PrivateRaj18110/PrivateRaj18110.github.io.git"
SITE_URL = "https://privateraj18110.github.io/"

SITE_README = f"""# Raj Yadav: portfolio

Live site: {SITE_URL}

Static portfolio and CV, generated from a structured CV file and published here automatically.
"""


def _git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(SITE_DIR), *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def _mirror_portfolio() -> None:
    """Replaces everything in the site checkout (except .git) with the contents of portfolio/."""
    for item in SITE_DIR.iterdir():
        if item.name == ".git":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copytree(PORTFOLIO_DIR, SITE_DIR, dirs_exist_ok=True)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is, no Jekyll build
    (SITE_DIR / "README.md").write_text(SITE_README, encoding="utf-8")


def publish() -> str:
    """Mirrors portfolio/ into the public site repo and pushes it. Returns a short status message."""
    if not (PORTFOLIO_DIR / "index.html").exists():
        raise FileNotFoundError("portfolio/index.html not found. Run: python portfolio_builder.py")
    if not (SITE_DIR / ".git").exists():
        subprocess.run(["git", "clone", "-q", SITE_REPO_URL, str(SITE_DIR)], check=True)
        # Commit as the same identity this repository uses
        for key in ("user.name", "user.email"):
            value = subprocess.run(["git", "-C", str(BASE_DIR), "config", key], capture_output=True, text=True).stdout.strip()
            if value:
                _git("config", key, value)
    _git("checkout", "-q", "-B", "main")

    _mirror_portfolio()
    _git("add", "-A")
    if not _git("status", "--porcelain"):
        logger.info("[SITE] Nothing changed; site already up to date.")
        return "Site already up to date."
    _git("commit", "-q", "-m", f"Update portfolio ({datetime.now():%Y-%m-%d %H:%M})")
    _git("push", "-q", "-u", "origin", "main")
    logger.info("[SITE] Published to %s", SITE_URL)
    return f"Published to {SITE_URL}"


if __name__ == "__main__":
    print(publish())
