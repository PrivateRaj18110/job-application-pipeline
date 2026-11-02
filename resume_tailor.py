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

# Segoe UI ships with Windows and has no "fi"/"fl"/"ff" ligature glyphs. The PDF engine's default fonts
# do, and ATS parsers then read "verification" as "veriﬁcation", so keyword searches miss it.
PDF_FONT_DIR = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts"
PDF_FONT_FACES = {"normal normal": "segoeui.ttf", "bold normal": "segoeuib.ttf",
                  "normal italic": "segoeuii.ttf", "bold italic": "segoeuiz.ttf"}

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
- Header: candidate name, title, email and links exactly as in the Master Resume, with each link's address as its visible text.
- Sections, with these exact headings so applicant tracking systems recognise them: Summary, Skills, Projects, Experience, Education, Certifications, Achievements.
- Length: at most two pages.
- Return ONLY the raw markdown resume text. DO NOT wrap with ```markdown code fences or add conversational greetings.
"""


def load_master_resume(resume_path: Optional[str] = None) -> str:
    """Reads the master resume text from markdown file."""
    path = Path(resume_path) if resume_path else DEFAULT_MASTER_RESUME_PATH
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()

    # No master resume yet: render one from the structured CV (cv.json)
    import portfolio_builder

    return portfolio_builder.cv_to_markdown(portfolio_builder.load_cv())


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


def generate_text(system_prompt: str, user_prompt: str, temperature: float = 0.4) -> str:
    """
    Provider-agnostic LLM call shared with other modules (e.g. cold_emailer.py).
    Returns an empty string when no provider is configured or the call fails, so callers can fall back.
    """
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    try:
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if provider == "gemini" and gemini_key and not gemini_key.startswith("your_"):
            from google import genai

            client = genai.Client(api_key=gemini_key)
            response = client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=f"{system_prompt}\n\n{user_prompt}",
            )
            return (response.text or "").strip()

        if provider == "openai" and openai_key and not openai_key.startswith("your_"):
            from openai import OpenAI

            client = OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
            return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("[LLM] %s generation failed: %s", provider, e)
    return ""


def _fallback_heuristic_tailoring(job_description: str, master_resume_text: str) -> str:
    """
    Fallback when no LLM API key is configured: returns the concise ATS resume from cv.json
    (or the master resume when cv.json has no "resume" section), untailored but truthful,
    so test runs and dry runs still produce a real PDF without external keys.
    """
    import portfolio_builder

    cv = portfolio_builder.load_cv()
    if cv.get("resume"):
        logger.info("No LLM API key configured; using the ATS resume from cv.json without tailoring.")
        return portfolio_builder.cv_to_resume_markdown(cv)
    logger.info("No LLM API key configured; using the master resume without tailoring.")
    return master_resume_text.strip()


def _with_private_phone(markdown_content: str) -> str:
    """Adds the phone number kept out of git (APPLICANT_PHONE in .env) after the email in the header.

    The master resume is tracked in git, so it never contains the number; resumes sent to employers do.
    """
    phone = os.getenv("APPLICANT_PHONE", "").strip()
    lines = markdown_content.splitlines()
    header = "\n".join(lines[:8])
    if not phone or re.sub(r"\D", "", phone)[-10:] in re.sub(r"\D", "", header):
        return markdown_content
    for i, line in enumerate(lines[:8]):
        email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", line)
        if email:
            lines[i] = f"{line[:email.end()]} | {phone}{line[email.end():]}"
            return "\n".join(lines)
    return markdown_content


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

    return _with_private_phone(markdown_content)


def _render_pdf_with_ats_font(markdown_content: str, css: str, output_path: Path) -> bool:
    """Renders Markdown to an A4 PDF in Segoe UI. Returns False when the font is not installed."""
    if not all((PDF_FONT_DIR / f).exists() for f in PDF_FONT_FACES.values()):
        return False
    import pymupdf
    from markdown_it import MarkdownIt

    font_css = " ".join(
        f"@font-face {{font-family: ResumeSans; src: url({file}); font-weight: {style.split()[0]}; font-style: {style.split()[1]};}}"
        for style, file in PDF_FONT_FACES.items()
    )
    story = pymupdf.Story(MarkdownIt("commonmark").render(markdown_content), user_css=font_css + css,
                          archive=pymupdf.Archive(str(PDF_FONT_DIR)))
    page = pymupdf.paper_rect("a4")
    writer = pymupdf.DocumentWriter(str(output_path))
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(page + (40, 34, -40, -34))
        story.draw(device)
        writer.end_page()
    writer.close()

    # Embed only the glyphs used: the full font files make a ~2.5 MB PDF, over many application forms' 2 MB limit
    doc = pymupdf.open(str(output_path))
    doc.subset_fonts()
    data = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    output_path.write_bytes(data)
    return True


def convert_markdown_to_pdf(markdown_content: str, job_title: str = "Tailored", output_filename: Optional[str] = None) -> str:
    """
    Utility function converting tailored Markdown into a cleanly formatted PDF
    saved in the local /output folder (Segoe UI via PyMuPDF; markdown-pdf and ReportLab as fallbacks).
    """
    sanitized_title = re.sub(r"[^\w\-_]", "_", job_title)[:30]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not output_filename:
        name_match = re.search(r"^#\s+(.+)$", markdown_content, re.M)
        candidate = re.sub(r"[^\w\-]", "_", name_match.group(1).strip()) if name_match else "Candidate"
        output_filename = f"Resume_{candidate}_{sanitized_title}_{timestamp}.pdf"

    output_path = OUTPUT_DIR / output_filename

    # Professional CSS Styling for Clean Resume Layout
    custom_css = """
    body {
        font-family: ResumeSans, 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 10pt;
        line-height: 1.35;
        color: #222222;
    }
    h1 {
        font-size: 18pt;
        margin-bottom: 2px;
        color: #111111;
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
        if _render_pdf_with_ats_font(markdown_content, custom_css, output_path):
            logger.info("Generated PDF successfully (Segoe UI): %s", output_path)
            return str(output_path.resolve())
        logger.warning("Segoe UI not found in %s; falling back to markdown-pdf (its fonts use ligatures).", PDF_FONT_DIR)
    except Exception as e:
        logger.warning("Segoe UI rendering failed (%s), falling back to markdown-pdf...", e)

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
