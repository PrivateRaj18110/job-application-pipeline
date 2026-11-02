"""
Module: ats_benchmark.py
Benchmarks the resume against real job postings for the roles in targets.json, the way an
applicant tracking system (ATS) would see it.

1. collect: pulls postings from companies' public job-board feeds (Greenhouse, Lever, Ashby,
   SmartRecruiters for India), keeps titles that match the target roles (same keyword and
   seniority rules as the scraper), and saves them to output/ats/postings.jsonl.
2. score: reads a resume PDF the way an ATS parser does, checks what breaks parsing (length,
   ligatures, hidden links, headings, contact details), measures how often each skill is asked
   for, and scores the resume's keyword match against every posting.

Run with:
  python ats_benchmark.py collect
  python ats_benchmark.py score portfolio/resume.pdf     # writes output/ats/report_<name>.md
"""

import re
import sys
import json
import html
import time
import logging
import argparse
from pathlib import Path
from typing import Dict, Iterator, List
from concurrent.futures import ThreadPoolExecutor

import httpx

from scraper import location_allowed, matches_keywords

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
ATS_DIR = BASE_DIR / "output" / "ats"
POSTINGS_FILE = ATS_DIR / "postings.jsonl"
TARGETS_FILE = BASE_DIR / "targets.json"

# Public job-board feeds. Unknown or retired boards simply return nothing and are skipped.
BOARDS = {
    "greenhouse": [
        "anthropic", "scaleai", "databricks", "mongodb", "gitlab", "elastic", "cloudflare", "twilio", "okta",
        "postman", "coinbase", "stripe", "airbnb", "dropbox", "figma", "samsara", "intercom", "gong", "robinhood",
        "discord", "reddit", "pinterest", "lyft", "doordash", "instacart", "affirm", "brex", "chime", "asana",
        "datadog", "hashicorp", "confluent", "cockroachlabs", "sumologic", "newrelic", "nutanix", "rubrik",
        "druva", "browserstack", "sprinklr", "phonepe", "groww", "meesho", "razorpay", "freshworks", "chargebee",
        "hackerrank", "innovaccer", "mindtickle", "observeai", "thoughtspot", "zscaler", "toast", "gusto",
        "grammarly", "duolingo", "squarespace", "airtable", "vercel", "planetscale", "fivetran", "dbtlabs",
        "clari", "highspot", "moengage", "zeta", "cleartax", "unacademy", "sharechat", "dunzo", "cars24",
    ],
    "lever": [
        "cred", "paytm", "upstox", "jupiter", "slice", "dream11", "swiggy", "atlan", "hasura", "plivo",
        "leadsquared", "palantir", "spotify", "mistral", "anyscale", "zepto", "khatabook", "lenskart",
        "rapido", "zomato", "urbancompany", "ola", "mpl", "glean", "netomi", "yellowai", "haptik",
    ],
    "ashby": [
        "openai", "notion", "linear", "ramp", "cohere", "perplexity", "deepgram", "elevenlabs", "replit",
        "supabase", "langchain", "pinecone", "weaviate", "modal", "runway", "sarvam", "krutrim", "lovable",
        "cursor", "anysphere", "harvey", "sierra", "decagon", "writer", "hebbia", "baseten", "fireworks",
    ],
    # SmartRecruiters can filter by country, which adds employers hiring in India
    "smartrecruiters": [
        "ServiceNow", "BoschGroup", "Freshworks", "Swiggy", "NielsenIQ", "Experian", "Equifax", "AVEVA",
        "Ciena", "Synechron", "Sabre", "Ubisoft", "LTIMindtree",
    ],
}
SMARTRECRUITERS_COUNTRY = "in"

# A matching keyword is not enough ("Recruiter, Applied AI"): the title must name an engineering role
ENGINEERING_TITLE = re.compile(r"engineer|developer|\bsde\b|programmer|mlops|ml ops|\bfde\b", re.I)
MAX_PER_COMPANY = 15  # keeps a few large AI labs from dominating the benchmark

TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")


def _text(raw: str) -> str:
    """Greenhouse sends escaped HTML; Lever and Ashby send HTML or plain text. Returns plain text."""
    return SPACE.sub(" ", TAG.sub(" ", html.unescape(html.unescape(raw or "")))).strip()


def _fetch_smartrecruiters(client: httpx.Client, company: str, wanted) -> List[Dict[str, str]]:
    """Lists the company's postings in one country, then fetches full text only for wanted titles."""
    base = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
    out, offset = [], 0
    while True:
        r = client.get(base, params={"country": SMARTRECRUITERS_COUNTRY, "limit": 100, "offset": offset})
        if r.status_code != 200:
            return out
        page = r.json()
        for p in page.get("content", []):
            if not wanted(p.get("name", "")):
                continue
            detail = client.get(f"{base}/{p['id']}")
            if detail.status_code != 200:
                continue
            sections = (detail.json().get("jobAd") or {}).get("sections") or {}
            loc = p.get("location") or {}
            out.append({"title": p.get("name", ""), "location": ", ".join(filter(None, [loc.get("city"), "India"])),
                        "url": f"https://jobs.smartrecruiters.com/{company}/{p['id']}",
                        "text": _text(" ".join((sections.get(k) or {}).get("text", "")
                                               for k in ("jobDescription", "qualifications", "additionalInformation")))})
        offset += 100
        if offset >= page.get("totalFound", 0):
            return out


def _fetch_board(client: httpx.Client, platform: str, token: str, wanted=None) -> List[Dict[str, str]]:
    try:
        if platform == "smartrecruiters":
            return _fetch_smartrecruiters(client, token, wanted)
        if platform == "greenhouse":
            r = client.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"})
            if r.status_code != 200:
                return []
            return [{"title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
                     "url": j.get("absolute_url", ""), "text": _text(j.get("content", ""))} for j in r.json().get("jobs", [])]
        if platform == "lever":
            r = client.get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"})
            if r.status_code != 200:
                return []
            out = []
            for j in r.json():
                parts = [j.get("descriptionPlain", "")] + [f"{s.get('text', '')}: {_text(s.get('content', ''))}" for s in j.get("lists", [])]
                parts.append(j.get("additionalPlain", ""))
                out.append({"title": j.get("text", ""), "location": (j.get("categories") or {}).get("location", ""),
                            "url": j.get("hostedUrl", ""), "text": SPACE.sub(" ", " ".join(parts)).strip()})
            return out
        r = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
        if r.status_code != 200:
            return []
        return [{"title": j.get("title", ""),
                 "location": ("Remote" if j.get("isRemote") else "") + " " + (j.get("location") or ""),
                 "url": j.get("jobUrl", ""), "text": _text(j.get("descriptionPlain") or j.get("descriptionHtml", ""))}
                for j in r.json().get("jobs", [])]
    except (httpx.HTTPError, ValueError):
        return []


def collect() -> Dict[str, int]:
    settings = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))["settings"]
    keywords, exclude = settings["default_role_keywords"], settings["exclude_title_keywords"]
    location_filter = settings["location_filter"]
    jobs = [(platform, token) for platform, tokens in BOARDS.items() for token in tokens]
    ATS_DIR.mkdir(parents=True, exist_ok=True)

    def wanted(title: str) -> bool:
        return bool(ENGINEERING_TITLE.search(title)) and matches_keywords(title, keywords, exclude)

    stats = {"boards_with_jobs": 0, "postings_seen": 0, "kept": 0, "india_or_remote": 0}
    seen_urls = set()
    with httpx.Client(timeout=20.0, headers={"User-Agent": "job-search-research/1.0"}) as client, \
            ThreadPoolExecutor(max_workers=6) as pool, open(POSTINGS_FILE, "w", encoding="utf-8") as out:
        for (platform, token), postings in zip(jobs, pool.map(lambda pt: _fetch_board(client, *pt, wanted=wanted), jobs)):
            if postings:
                stats["boards_with_jobs"] += 1
            stats["postings_seen"] += len(postings)
            # India and remote roles first, so the per-company cap keeps them
            postings.sort(key=lambda p: not location_allowed(p["location"], location_filter))
            kept_here = 0
            for p in postings:
                if kept_here >= MAX_PER_COMPANY:
                    break
                if p["url"] in seen_urls or len(p["text"]) < 400 or not wanted(p["title"]):
                    continue
                seen_urls.add(p["url"])
                kept_here += 1
                p.update(company=token, platform=platform, india_or_remote=location_allowed(p["location"], location_filter))
                out.write(json.dumps(p, ensure_ascii=False) + "\n")
                stats["kept"] += 1
                stats["india_or_remote"] += int(p["india_or_remote"])
    logger.info("[ATS] %s", stats)
    return stats


def load_postings() -> Iterator[Dict[str, object]]:
    with open(POSTINGS_FILE, encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)


# ---------------------------------------------------------------------------
# Scoring: skill demand across postings and the resume's keyword match
# ---------------------------------------------------------------------------
# Canonical skill -> pattern. Synonyms count as the same skill, e.g. "Google Cloud" is GCP.
SKILLS = {
    "Python": r"\bpython\b", "SQL": r"\bsql\b", "Java": r"\bjava\b(?!\s*script)", "Go": r"\bgolang\b|\bGo\b(?![- ]to\b)",
    "TypeScript": r"\btypescript\b", "JavaScript": r"\bjavascript\b", "C++": r"c\+\+", "Rust": r"\brust\b", "Scala": r"\bscala\b",
    "FastAPI": r"\bfastapi\b", "Django": r"\bdjango\b", "Flask": r"\bflask\b", "Node.js": r"\bnode\.?js\b",
    "REST APIs": r"\brest(ful)?\b", "APIs": r"\bapis?\b", "GraphQL": r"\bgraphql\b", "gRPC": r"\bgrpc\b",
    "Microservices": r"\bmicro-?services?\b", "Event-driven systems": r"\bevent[- ]driven\b",
    "Distributed systems": r"\bdistributed (systems?|computing)\b", "System design": r"\bsystem design\b|\bsystems? architecture\b",
    "LLMs": r"\bllms?\b|\blarge language models?\b", "Generative AI": r"\bgenerative ai\b|\bgen ?ai\b",
    "RAG": r"\brag\b|\bretrieval[- ]augmented\b", "AI agents": r"\bagentic\b|\bai agents?\b|\bagents\b",
    "Prompt engineering": r"\bprompt (engineering|design)\b|\bprompting\b|\bprompts\b",
    "LangChain": r"\blangchain\b|\blanggraph\b", "LlamaIndex": r"\bllama ?index\b",
    "Vector databases": r"\bvector (database|db|store|search)s?\b|\bpinecone\b|\bweaviate\b|\bfaiss\b|\bpgvector\b|\bchroma(db)?\b|\bmilvus\b|\bqdrant\b",
    "Embeddings": r"\bembeddings?\b", "Fine-tuning": r"\bfine[- ]?tun(e|ed|ing)\b", "LLM evaluation": r"\bevals?\b|\bevaluation (framework|harness|pipeline|suite)s?\b",
    "Hugging Face": r"\bhugging ?face\b", "PyTorch": r"\bpytorch\b", "TensorFlow": r"\btensorflow\b", "scikit-learn": r"\bscikit|\bsklearn\b",
    "Machine learning": r"\bmachine learning\b|\bml\b", "Deep learning": r"\bdeep learning\b", "NLP": r"\bnlp\b|\bnatural language processing\b",
    "Computer vision": r"\bcomputer vision\b", "Statistics": r"\bstatistic(s|al)\b", "MLOps": r"\bmlops\b|\bml ops\b|\bml infrastructure\b",
    "Model serving / inference": r"\bmodel serving\b|\binference\b", "MLflow": r"\bmlflow\b",
    "Docker": r"\bdocker\b|\bcontaineri[sz]", "Kubernetes": r"\bkubernetes\b|\bk8s\b", "AWS": r"\baws\b|\bamazon web services\b",
    "GCP": r"\bgcp\b|\bgoogle cloud\b", "Azure": r"\bazure\b", "Terraform": r"\bterraform\b|\binfrastructure as code\b",
    "CI/CD": r"\bci/cd\b|\bcontinuous (integration|delivery|deployment)\b", "GitHub Actions": r"\bgithub actions\b", "Git": r"\bgit\b",
    "Linux": r"\blinux\b", "PostgreSQL": r"\bpostgres(ql)?\b", "MySQL": r"\bmysql\b", "MongoDB": r"\bmongo(db)?\b", "Redis": r"\bredis\b",
    "NoSQL": r"\bnosql\b", "Kafka": r"\bkafka\b", "Spark": r"\b(py)?spark\b", "Airflow": r"\bairflow\b", "dbt": r"\bdbt\b",
    "Snowflake": r"\bsnowflake\b", "BigQuery": r"\bbigquery\b", "Databricks": r"\bdatabricks\b", "ETL / data pipelines": r"\betl\b|\belt\b|\bdata pipelines?\b",
    "Data modeling": r"\bdata model(l)?ing\b", "pandas": r"\bpandas\b", "NumPy": r"\bnumpy\b", "DuckDB": r"\bduckdb\b",
    "Observability": r"\bobservability\b|\bprometheus\b|\bgrafana\b|\bdatadog\b|\bopentelemetry\b",
    "Testing": r"\bunit tests?\b|\bpytest\b|\btest automation\b|\bautomated tests?\b", "React": r"\breact\b", "SaaS": r"\bsaas\b",
    "Communication": r"\bcommunicat(e|ion|ing)\b", "Cross-functional collaboration": r"\bcross[- ]functional\b|\bcollaborat(e|ion|ing)\b",
}
SOFT_SKILLS = {"Communication", "Cross-functional collaboration"}
CASE_SENSITIVE = {"Go"}
PATTERNS = {name: re.compile(p, 0 if name in CASE_SENSITIVE else re.I) for name, p in SKILLS.items()}

STANDARD_HEADINGS = {"summary", "skills", "technical skills", "experience", "work experience", "projects",
                     "education", "certifications", "achievements"}
LIGATURES = "ﬀﬁﬂﬃﬄﬅﬆ"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(\+?\d[\d\s-]{8,}\d)")
URL = re.compile(r"(https?://|www\.)?[\w-]+\.(com|in|io|dev|me|org|net)(/[\w./-]*)?", re.I)


def skills_in(text: str) -> set:
    return {name for name, pattern in PATTERNS.items() if pattern.search(text)}


def read_like_ats(pdf_path: Path) -> Dict[str, object]:
    """Extracts the text with two common parsers and records what would trip up an ATS."""
    import logging as _logging
    import pdfplumber
    import pypdf
    _logging.getLogger("pypdf").setLevel(_logging.ERROR)
    _logging.getLogger("pdfminer").setLevel(_logging.ERROR)

    plumber = pdfplumber.open(pdf_path)
    text = "\n".join(page.extract_text() or "" for page in plumber.pages)
    raw = "\n".join(page.extract_text() for page in pypdf.PdfReader(pdf_path).pages)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    headings = [l for l in lines if l.lower().rstrip(":") in STANDARD_HEADINGS]
    top = "\n".join(lines[:6])
    return {
        "text": text,
        "pages": len(plumber.pages),
        "words": len(text.split()),
        "images": sum(len(p.images) for p in plumber.pages),
        "tables": sum(len(p.find_tables()) for p in plumber.pages),
        "ligature_glyphs": sum(raw.count(ch) for ch in LIGATURES),
        "email_found": bool(EMAIL.search(top)),
        "phone_found": bool(PHONE.search(top)),
        "urls_in_text": sorted({m.group(0) for m in URL.finditer(top) if "@" not in m.group(0)}),
        "standard_headings": headings,
    }


def score(pdf_path: Path) -> Dict[str, object]:
    postings = list(load_postings())
    resume = read_like_ats(pdf_path)
    have = skills_in(resume["text"])

    demand, india = {}, [p for p in postings if p["india_or_remote"]]
    per_posting = []
    for p in postings:
        wanted = skills_in(f"{p['title']} {p['text']}") - SOFT_SKILLS
        p["skills"] = wanted
        if wanted:
            per_posting.append(len(wanted & have) / len(wanted))
    for name in SKILLS:
        if name in SOFT_SKILLS:
            continue
        share = sum(1 for p in postings if name in p["skills"]) / len(postings)
        share_india = sum(1 for p in india if name in p["skills"]) / (len(india) or 1)
        demand[name] = {"all": round(share, 3), "india_remote": round(share_india, 3), "on_resume": name in have}

    per_posting.sort()
    summary = {
        "resume": str(pdf_path), "postings": len(postings), "companies": len({p["company"] for p in postings}),
        "india_or_remote": len(india),
        "median_match": round(per_posting[len(per_posting) // 2], 3),
        "mean_match": round(sum(per_posting) / len(per_posting), 3),
        "postings_matched_60pct": round(sum(1 for s in per_posting if s >= 0.6) / len(per_posting), 3),
        **{k: v for k, v in resume.items() if k != "text"},
    }
    return {"summary": summary, "demand": demand}


def write_report(result: Dict[str, object], name: str) -> Path:
    s, demand = result["summary"], result["demand"]
    ranked = sorted(demand.items(), key=lambda kv: -kv[1]["all"])
    lines = [
        f"# ATS benchmark: {s['resume']}", "",
        f"{s['postings']} real postings for the target roles from {s['companies']} companies "
        f"({s['india_or_remote']} in India or remote).", "",
        "## Keyword match", "",
        f"- Median match: **{s['median_match']:.0%}** of the skills a posting asks for appear on the resume",
        f"- Mean match: {s['mean_match']:.0%}",
        f"- Postings matched at 60% or more: {s['postings_matched_60pct']:.0%}", "",
        "## Parsing", "",
        f"- Pages: {s['pages']} · words: {s['words']} · images: {s['images']} · tables: {s['tables']}",
        f"- Ligature glyphs (break words like 'verification'): {s['ligature_glyphs']}",
        f"- Email in header: {s['email_found']} · phone in header: {s['phone_found']} · visible URLs: {', '.join(s['urls_in_text']) or 'none'}",
        f"- Standard section headings found: {', '.join(s['standard_headings']) or 'none'}", "",
        "## Skill demand", "", "| Skill | All postings | India / remote | On resume |", "|---|---|---|---|",
    ]
    lines += [f"| {k} | {v['all']:.0%} | {v['india_remote']:.0%} | {'yes' if v['on_resume'] else '**no**'} |"
              for k, v in ranked if v["all"] >= 0.03]
    path = ATS_DIR / f"report_{name}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ATS_DIR / f"report_{name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description="Benchmark the resume against real job postings")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("collect", help="Collect postings for the target roles")
    sc = sub.add_parser("score", help="Score a resume PDF against the collected postings")
    sc.add_argument("pdf", type=Path)
    sc.add_argument("--name", default=None, help="Report name (defaults to the PDF file name)")
    args = parser.parse_args()
    if args.command == "collect":
        started = time.perf_counter()
        print(json.dumps(collect(), indent=2), f"\n{time.perf_counter() - started:.0f}s")
    else:
        result = score(args.pdf)
        print(f"Report: {write_report(result, args.name or args.pdf.stem)}")
        print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    sys.exit(main())
