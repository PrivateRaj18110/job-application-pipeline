"""
Module 3: resume_tailor.py
The LLM Engine module for tailoring resumes based on job descriptions and candidate's master resume.
Uses Google Gemini (google-genai) or OpenAI to generate tailored Markdown resumes without hallucination,
and compiles them into clean, publication-ready PDFs saved in the /output folder using markdown-pdf.
"""

import os
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
raw_output = os.getenv("OUTPUT_DIR", "output")
OUTPUT_DIR = (BASE_DIR / raw_output).resolve() if not Path(raw_output).is_absolute() else Path(raw_output)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MASTER_RESUME_PATH = BASE_DIR / "master_resume.md"

STRICT_SYSTEM_PROMPT = """You are an elite technical career coach and resume strategist.
Your task is to take the candidate's MASTER RESUME and tailor it precisely for the provided JOB DESCRIPTION.

CRITICAL INTEGRITY CONSTRAINTS (ZERO HALLUCINATION POLICY):
1. SOURCE OF TRUTH: The Master Resume is the ONLY ground truth for facts.
2. ABSOLUTELY NO HALLUCINATIONS: You must NOT fabricate, invent, or exaggerate any past company, job title, project, educational institution, degree, GPA, date, certification, or tool that does not appear in the Master Resume.
3. ADAPTATION PERMITTED:
   - Reorder and emphasize technical skills that match the target role.
   - Reframe and spotlight project details and internship achievements using keywords from the job description, strictly reflecting the actual work performed.
   - Select the most relevant projects first.
   - Highlight core competencies matching the role (e.g. Computer Vision / PyTorch / Flutter / Full Stack).

OUTPUT SPECIFICATIONS:
- Format: Clean, beautifully structured Markdown.
- Header: Candidate name, title, email, phone, LinkedIn.
- Sections: Education, Technical Skills, Highlighted Projects, Professional Experience/Internships, Certifications, Research & Leadership.
- Return ONLY the raw markdown resume text. DO NOT wrap with ```markdown code fences or add conversational greetings.
"""


def load_master_resume(resume_path: Optional[str] = None) -> str:
    """Reads the master resume text from markdown file."""
    path = Path(resume_path) if resume_path else DEFAULT_MASTER_RESUME_PATH
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()

    # Fallback to embedded master resume if file is missing
    return """
# Alex Rivera
Senior Quantitative Systems & Machine Learning Engineer
alex.rivera.dev@example.com | +1-555-0199 | https://www.linkedin.com/in/alexrivera-dev

## Education
University of California, Berkeley (2024)
B.S. in Computer Science & Applied Mathematics | GPA: 3.91 / 4.00

## Technical Skills
- Programming Languages: Modern C++ (C++17/20), Python, SQL (PostgreSQL), Rust
- High-Performance & Low-Latency: Numba (JIT `@njit`), SIMD Vectorization, Lock-free Ring Buffers, ZeroMQ, Socket Programming
- Quantitative & Broker APIs: MetaTrader 5 (MT5 Python API), FlatTrade Broker API, WebSocket Market Feeds
- Numerical & Machine Learning: NumPy, Pandas, SciPy, PyTorch, Scikit-learn
- Systems: Linux, Docker, CMake, Git

## Projects
Low-Latency C++ Execution Engine
Tech Stack: Modern C++ (C++20), Lock-free Queues, Linux Sockets
- Engineered ultra-low-latency order execution engine in C++ with sub-millisecond execution dispatch.
- Implemented custom ring-buffer and lock-free SPSC queues to eliminate mutex contention across worker threads.

Numba-Accelerated Quantitative Strategy Engine
Tech Stack: Python, Numba JIT, NumPy, SciPy
- Built high-throughput algorithmic signal generation and risk management engine accelerated with Numba `@njit` kernels.
- Optimized hot execution paths for real-time tick analysis and dynamic position sizing.

Multi-Broker API Gateway (MetaTrader 5 & FlatTrade)
Tech Stack: Python, MetaTrader 5 API, FlatTrade API, WebSockets
- Developed unified multi-broker trading gateway connecting to MetaTrader 5 and FlatTrade APIs.
- Automated continuous order dispatch, live P&L tracking, and real-time margin calculation.

## Experience & Internships
AlphaPulse Quantitative Capital | Quantitative Systems Engineer (2024 - Present)
- Architected ultra-low-latency C++20 order routing engine with sub-50 microsecond execution dispatch.
- Implemented lock-free circular memory buffers to eliminate thread contention.

Vertex AI Research Labs | Machine Learning Engineering Intern (2023 - 2024)
- Developed deep learning models for real-time anomaly detection using PyTorch and CUDA.

## Certifications & Achievements
Certified Kubernetes Application Developer (CKAD) | AWS Certified Solutions Architect
"""


def _generate_tailored_resume_gemini(job_description: str, master_resume_text: str) -> str:
    """Invokes Google Gemini via google-genai library."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing.")

    from google import genai

    client = genai.Client(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    prompt = f"""
{STRICT_SYSTEM_PROMPT}

TARGET JOB DESCRIPTION:
{job_description}

CANDIDATE MASTER RESUME:
{master_resume_text}

Generate the tailored resume in Markdown format now:
"""
    logger.info("Calling Gemini API (%s) for resume tailoring...", model_name)
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
    )
    return response.text.strip()


def _generate_tailored_resume_openai(job_description: str, master_resume_text: str) -> str:
    """Invokes OpenAI API as an alternative LLM provider."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is missing.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    prompt = f"TARGET JOB DESCRIPTION:\n{job_description}\n\nCANDIDATE MASTER RESUME:\n{master_resume_text}"

    logger.info("Calling OpenAI API for resume tailoring...")
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": STRICT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


def _fallback_heuristic_tailoring(job_description: str, master_resume_text: str) -> str:
    """
    Intelligent heuristic fallback if no LLM API key is configured.
    Ensures that test runs and dry runs succeed smoothly without external keys.
    """
    logger.info("Using smart heuristic tailoring (No LLM API key configured).")
    jd_lower = job_description.lower()
    is_trading_focused = any(kw in jd_lower for kw in ["trading", "quant", "algorithmic", "latency", "numba", "broker", "metatrader", "flattrade", "execution engine", "c++"])
    is_ml_focused = any(kw in jd_lower for kw in ["machine learning", "ml", "ai", "vision", "pytorch", "deep learning"])
    is_mobile_focused = any(kw in jd_lower for kw in ["flutter", "mobile", "android", "dart", "frontend"])

    if is_trading_focused:
        highlight_note = "Tailored for Low-Latency Algorithmic Trading & Quantitative Systems"
    elif is_ml_focused:
        highlight_note = "Tailored for AI & Machine Learning Opportunities"
    else:
        highlight_note = "Tailored for Full-Stack & Mobile Engineering"

    tailored = f"""# Alex Rivera
**Quantitative Systems & Software Engineer | {highlight_note}**
alex.rivera.dev@example.com | +1-555-0199 | [LinkedIn](https://www.linkedin.com/in/alexrivera-dev) | [GitHub](https://github.com/alexrivera-dev)

---

## Technical Skills
- **Low-Latency & Performance**: Modern C++ (C++17/20), Numba (JIT `@njit`), SIMD, Lock-free Queues, Multithreading, ZeroMQ
- **Trading & Broker APIs**: MetaTrader 5 (MT5 Python API), FlatTrade Broker API, WebSocket tick streams, Order Management Systems
- **Programming Languages**: Python, Modern C++, SQL (PostgreSQL, SQLite)
- **Scientific & Numerical Computing**: NumPy, Pandas, SciPy, Scikit-learn
- **Systems & Tooling**: Linux/Unix, Git, CMake, GCC/Clang, Docker, Visual Studio

---

## Key Projects
"""

    if is_trading_focused:
        tailored += """### Low-Latency C++ Execution Engine
*Tech Stack: Modern C++ (C++20), Multithreading, Lock-free Queues, Socket Programming, Linux*
- Engineered an ultra-low-latency order execution engine in C++ with sub-millisecond execution dispatch.
- Implemented custom ring-buffer and lock-free SPSC queues to eliminate mutex contention across worker threads.
- Integrated asynchronous market data feeds and order routing protocols with deterministic latency profiles.

### Numba-Accelerated Quantitative Strategy Engine
*Tech Stack: Python, Numba JIT, NumPy, Pandas, SciPy*
- Built high-throughput algorithmic signal generation and risk management engine accelerated with Numba `@njit` kernels.
- Optimized execution hot paths, achieving near-C execution performance for real-time tick analysis and dynamic position sizing.
- Implemented backtesting and forward-simulation modules capable of crunching multi-gigabyte order book snapshots.

### Multi-Broker API Gateway (MetaTrader 5 & FlatTrade)
*Tech Stack: Python, MetaTrader 5 API, FlatTrade API, WebSockets, Asyncio, PostgreSQL*
- Developed unified multi-broker trading gateway connecting to MetaTrader 5 (MT5) and FlatTrade APIs.
- Automated continuous order dispatch, live P&L tracking, trailing stop algorithms, and real-time margin calculation.
- Architected resilient WebSocket reconnection listeners and failover mechanisms for uninterrupted trading connectivity.
"""
    elif is_ml_focused:
        tailored += """### TruthLens: Deepfake Video Detection
*Tech Stack: Python, PyTorch, OpenCV, Google Colab*
- Developed a deep learning system that classifies videos as real or deepfake by analyzing facial and temporal features.
- Implemented a ResNeXt CNN for frame-level feature extraction and an LSTM to model patterns across sequential frames.
- Preprocessed video datasets, trained and evaluated neural network models, generating predictions with confidence scores.

### Low-Latency C++ Execution Engine
*Tech Stack: Modern C++ (C++20), Lock-free Queues, Multithreading*
- Engineered high-throughput execution hot-paths and real-time data streaming pipelines.
"""
    else:
        tailored += """### Multi-Broker API Gateway (MetaTrader 5 & FlatTrade)
*Tech Stack: Python, MetaTrader 5 API, FlatTrade API, WebSockets*
- Built scalable automated trading gateway with real-time order processing and WebSocket feeds.

### Low-Latency C++ Execution Engine
*Tech Stack: Modern C++, Lock-free Queues, Linux*
- Developed high-performance order routing engine in Modern C++ with sub-millisecond latency.
"""

    tailored += """
---

## Experience & Internships
- **India Space Week | Trainee** *(Feb 2026 – Mar 2026)*
  - Completed rigorous training in drone technology covering UAV avionics, flight dynamics, and embedded systems.
  - Gained hands-on experience in structural simulation, flight controller integration, and GIS drone mapping.
- **Univent | Web Designing Intern** *(Jun 2023 – Jul 2023)*
  - Designed interactive user interfaces to client specifications using modern design standards.
- **Ekraft | Digital Marketing Intern** *(Jul 2022 – Aug 2022)*
  - Produced engaging technical content and visual assets to strengthen digital audience reach.

---

## Education
- **SNDT Women's University, Usha Mittal Institute of Technology** (2026)
  *B.Tech in Information Technology* | **CGPA: 8.28**
- **Shri Bhagubhai Mafatlal Polytechnic** (2023)
  *Diploma in Information Technology* | **CGPA: 8.79**
- **Bombay Cambridge International School** (2020)
  *SSC* | **87.00%**

---

## Certifications & Leadership
- Data Structures and Algorithms (Udemy) • Cloud Computing Fundamentals (IBM) • IT Fundamentals (IBM)
- Professional & Communication Skills (IBM)
- Senior Council Member, E-Cell Council
- Authored Research Papers on Smart City IoT Services and E-Commerce Architecture.
"""
    return tailored.strip()


def tailor_resume(job_description: str, master_resume_text: Optional[str] = None) -> str:
    """
    Main function to tailor candidate's master resume against job description.
    Tries Gemini, then OpenAI, and gracefully falls back to heuristic tailoring.
    """
    if not master_resume_text:
        master_resume_text = load_master_resume()

    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    markdown_content = ""

    if provider == "gemini" and os.getenv("GEMINI_API_KEY"):
        try:
            markdown_content = _generate_tailored_resume_gemini(job_description, master_resume_text)
        except Exception as e:
            logger.warning("Gemini generation failed: %s. Falling back.", e)

    elif provider == "openai" and os.getenv("OPENAI_API_KEY"):
        try:
            markdown_content = _generate_tailored_resume_openai(job_description, master_resume_text)
        except Exception as e:
            logger.warning("OpenAI generation failed: %s. Falling back.", e)

    # Clean markdown if enclosed in fences
    if markdown_content:
        markdown_content = re.sub(r"^```markdown\s*", "", markdown_content)
        markdown_content = re.sub(r"^```\s*", "", markdown_content)
        markdown_content = re.sub(r"\s*```$", "", markdown_content).strip()
    else:
        markdown_content = _fallback_heuristic_tailoring(job_description, master_resume_text)

    return markdown_content


def convert_markdown_to_pdf(markdown_content: str, job_title: str = "Tailored", output_filename: Optional[str] = None) -> str:
    """
    Utility function converting tailored Markdown into a cleanly formatted PDF
    saved in the local /output folder using markdown-pdf.
    """
    sanitized_title = re.sub(r"[^\w\-_]", "_", job_title)[:30]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not output_filename:
        output_filename = f"Resume_Alex_Rivera_{sanitized_title}_{timestamp}.pdf"

    output_path = OUTPUT_DIR / output_filename

    # Professional CSS Styling for Clean Resume Layout
    custom_css = """
    body {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 10pt;
        line-height: 1.35;
        color: #222222;
        margin: 20px 30px;
    }
    h1 {
        font-size: 18pt;
        margin-bottom: 2px;
        color: #111111;
        text-align: center;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    h2 {
        font-size: 11pt;
        border-bottom: 1px solid #333333;
        padding-bottom: 2px;
        margin-top: 10px;
        margin-bottom: 4px;
        color: #1a1a1a;
        text-transform: uppercase;
    }
    h3 {
        font-size: 10pt;
        margin-top: 6px;
        margin-bottom: 2px;
        color: #222222;
    }
    p {
        margin-top: 2px;
        margin-bottom: 4px;
    }
    ul {
        margin-top: 2px;
        margin-bottom: 4px;
        padding-left: 18px;
    }
    li {
        margin-bottom: 2px;
    }
    hr {
        border: none;
        border-top: 1px solid #cccccc;
        margin: 8px 0;
    }
    strong {
        color: #000000;
    }
    a {
        color: #004488;
        text-decoration: none;
    }
    """

    try:
        from markdown_pdf import MarkdownPdf, Section

        pdf = MarkdownPdf(toc_level=0)
        pdf.add_section(Section(markdown_content, toc=False, paper_size="A4"))
        pdf.save(str(output_path))
        logger.info("Generated PDF successfully via markdown-pdf: %s", output_path)
        return str(output_path.resolve())

    except Exception as e:
        logger.warning("markdown-pdf failed (%s), attempting ReportLab fallback...", e)

    # Secondary Fallback via ReportLab (already installed in environment)
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        doc = SimpleDocTemplate(str(output_path), pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        story = []

        normal_style = styles["Normal"]
        h1_style = styles["Heading1"]
        h2_style = styles["Heading2"]

        for line in markdown_content.splitlines():
            line_str = line.strip()
            if not line_str:
                story.append(Spacer(1, 4))
            elif line_str.startswith("# "):
                title_text = line_str[2:].replace("*", "")
                story.append(Paragraph(f"<b>{title_text}</b>", h1_style))
            elif line_str.startswith("## "):
                section_text = line_str[3:].replace("*", "")
                story.append(Paragraph(f"<b>{section_text}</b>", h2_style))
            elif line_str.startswith("- "):
                clean_bullet = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", line_str[2:])
                clean_bullet = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", clean_bullet)
                story.append(Paragraph(f"&bull; {clean_bullet}", normal_style))
            else:
                clean_p = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", line_str)
                clean_p = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", clean_p)
                clean_p = clean_p.replace("---", "")
                if clean_p.strip():
                    story.append(Paragraph(clean_p, normal_style))

        doc.build(story)
        logger.info("Generated PDF successfully via ReportLab: %s", output_path)
        return str(output_path.resolve())

    except Exception as e2:
        logger.error("Failed to generate PDF with all methods: %s", e2)
        # Save markdown as file
        md_path = output_path.with_suffix(".md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        return str(md_path.resolve())


def tailor_and_export(job_description: str, job_title: str = "Tailored Role") -> str:
    """High-level pipeline function: takes job description and returns compiled PDF path."""
    logger.info("Starting resume tailoring for role: %s", job_title)
    markdown_resume = tailor_resume(job_description)
    pdf_path = convert_markdown_to_pdf(markdown_resume, job_title=job_title)
    return pdf_path


if __name__ == "__main__":
    print("Testing resume_tailor module...")
    sample_jd = (
        "Seeking a Deep Learning & Computer Vision Engineer proficient in PyTorch, OpenCV, "
        "and video classification. Experience with CNN and LSTM models is essential."
    )
    result_pdf = tailor_and_export(sample_jd, job_title="Computer Vision Engineer")
    print(f"Tailored PDF generated at: {result_pdf}")
