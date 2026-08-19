"""Generate the bundled sample CV PDFs.

Produces two files under ``backend/sample_data``:

* ``sample_cv_text.pdf``   — a normal, text-based multi-page CV (parses to real
  text, quality flag -> "ok").
* ``sample_cv_scanned.pdf`` — an *image-only* CV: the same content rasterised to
  an image and embedded with no text layer, simulating a scanned document
  (quality flag -> "low").

This is a dev-time helper, not part of the runtime. It depends on reportlab and
Pillow (listed in requirements.txt under the dev section).

Run:
    python scripts/generate_samples.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"

TEXT_CV_PAGES: list[list[str]] = [
    [
        "JANE DOE",
        "Backend Engineer",
        "jane.doe@example.com  |  +1 555 0100  |  github.com/janedoe",
        "",
        "SUMMARY",
        "Backend engineer with 6 years of professional Python experience building",
        "FastAPI services, data pipelines, and document-processing systems. Strong",
        "focus on typing, testing, and clean API design.",
        "",
        "EXPERIENCE",
        "Senior Backend Engineer — Acme Corp (2021–present)",
        "  - Designed and shipped REST APIs with FastAPI and Pydantic v2.",
        "  - Built a PDF ingestion pipeline (pdfplumber + rendering) for search.",
        "  - Drove test coverage from 40% to 90% with pytest and CI gates.",
        "",
        "Backend Engineer — Globex (2018–2021)",
        "  - Developed microservices in Python; mentored two junior engineers.",
        "  - Integrated third-party APIs and background job processing.",
    ],
    [
        "SKILLS",
        "Python, FastAPI, Pydantic, pytest, PostgreSQL, Docker, CI/CD, REST,",
        "document parsing (pdfplumber, pdf2image), basic TypeScript/Next.js.",
        "",
        "EDUCATION",
        "B.Sc. Computer Science — State University (2014–2018)",
        "",
        "PROJECTS",
        "  - Open-source résumé parser (300+ stars).",
        "  - LLM evaluation harness for document scoring experiments.",
        "",
        "REFERENCES",
        "Available on request.",
    ],
]


# A third, distinct candidate — junior profile, single page.
TEXT_CV_2_PAGES: list[list[str]] = [
    [
        "SAM RIVERA",
        "Junior Python Developer",
        "sam.rivera@example.com  |  +1 555 0182  |  github.com/samrivera",
        "",
        "SUMMARY",
        "Early-career developer with 2 years of Python experience. Comfortable",
        "with FastAPI basics and eager to grow in API design and testing.",
        "",
        "EXPERIENCE",
        "Python Developer — Umbrella Startups (2023–present)",
        "  - Built internal REST endpoints with Flask and some FastAPI.",
        "  - Wrote unit tests with pytest; set up basic GitHub Actions CI.",
        "",
        "Intern — DataWorks (2022–2023)",
        "  - Assisted with CSV/PDF data-cleaning scripts.",
        "",
        "SKILLS",
        "Python, Flask, FastAPI (basic), pytest, Git, SQL.",
        "",
        "EDUCATION",
        "B.Sc. Software Engineering — City College (2019–2023)",
    ],
]


# Two designer candidates (for the "graphic-designer" job) — distinct files so
# their file hashes don't collide with the backend candidates under dedup.
TEXT_CV_3_PAGES: list[list[str]] = [
    [
        "DANA LEE",
        "Product Designer",
        "dana.lee@example.com  |  dribbble.com/danalee",
        "",
        "SUMMARY",
        "Product designer with 7 years across brand and product. Strong visual",
        "hierarchy, systems thinking, and hands-on Figma prototyping.",
        "",
        "EXPERIENCE",
        "Senior Product Designer — Northwind (2020-present)",
        "  - Owned the design system and brand refresh across web and mobile.",
        "  - Partnered with engineering to ship accessible, polished UI.",
        "",
        "Designer — Pixel Forge (2016-2020)",
        "  - Marketing campaigns, illustration, and motion.",
        "",
        "SKILLS",
        "Figma, Adobe CC, prototyping, design systems, typography.",
        "",
        "EDUCATION",
        "BFA Graphic Design — Rhode Island (2012-2016)",
    ],
]

TEXT_CV_4_PAGES: list[list[str]] = [
    [
        "MIGUEL TORRES",
        "Junior Graphic Designer",
        "miguel.torres@example.com  |  behance.net/miguelt",
        "",
        "SUMMARY",
        "Early-career designer with 2 years in visual/brand design. Comfortable",
        "in Figma; growing in layout and design systems.",
        "",
        "EXPERIENCE",
        "Graphic Designer — Sunrise Studio (2023-present)",
        "  - Social assets, decks, and light UI work.",
        "",
        "SKILLS",
        "Figma, Illustrator, Photoshop, layout.",
        "",
        "EDUCATION",
        "BA Visual Communication — City College (2019-2023)",
    ],
]


def build_text_cv(path: Path, pages: list[list[str]] | None = None) -> None:
    """Render a real text-based PDF with reportlab (has a selectable text layer)."""
    pages = pages if pages is not None else TEXT_CV_PAGES
    c = canvas.Canvas(str(path), pagesize=LETTER)
    width, height = LETTER
    for page_lines in pages:
        y = height - inch
        for i, line in enumerate(page_lines):
            # First line of first block is the name -> larger font.
            if line.isupper() and len(line.split()) <= 3 and i == 0:
                c.setFont("Helvetica-Bold", 18)
            elif line.isupper():
                c.setFont("Helvetica-Bold", 12)
            else:
                c.setFont("Helvetica", 10)
            c.drawString(inch, y, line)
            y -= 16
        c.showPage()
    c.save()


def build_scanned_cv(path: Path) -> None:
    """Render an *image-only* PDF (no text layer) to simulate a scan.

    We draw the CV text onto a raster image, then embed that image full-page in
    a PDF. pdfplumber will extract ~no text -> quality flag "low".
    """
    # US Letter at 150 DPI.
    dpi = 150
    px_w, px_h = int(8.5 * dpi), int(11 * dpi)
    img = Image.new("RGB", (px_w, px_h), "white")
    draw = ImageDraw.Draw(img)

    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 30)
        body_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 18)
    except OSError:
        title_font = ImageFont.load_default()
        body_font = ImageFont.load_default()

    lines = [
        ("JOHN SMITH", title_font),
        ("Backend Engineer  |  john.smith@example.com", body_font),
        ("", body_font),
        ("SUMMARY", body_font),
        ("Backend engineer with 5 years of Python experience.", body_font),
        ("Built FastAPI services and document pipelines.", body_font),
        ("", body_font),
        ("EXPERIENCE", body_font),
        ("Backend Engineer — Initech (2020-present)", body_font),
        ("  - Python microservices, REST APIs, pytest, CI.", body_font),
        ("  - PDF processing and background jobs.", body_font),
        ("", body_font),
        ("(This page is an image-only scan: no selectable text.)", body_font),
    ]
    y = int(0.8 * dpi)
    for text, font in lines:
        draw.text((int(0.8 * dpi), y), text, fill="black", font=font)
        y += 40

    # Save the raster page(s) as an image-only PDF.
    img.save(str(path), "PDF", resolution=float(dpi))


ASSIGNMENT_BRIEF_LINES = [
    "CATALIST — TAKE-HOME ASSIGNMENT",
    "",
    "Thank you for progressing to the assignment stage. This is a short,",
    "time-boxed exercise designed to take about 2-3 hours.",
    "",
    "TASK",
    "Build a small REST endpoint that accepts a JSON payload, validates it,",
    "and returns a computed result. Include a couple of automated tests.",
    "",
    "WHAT WE'RE LOOKING FOR",
    "  - Clear, readable code and sensible structure.",
    "  - Input validation and graceful error handling.",
    "  - A short README explaining how to run it.",
    "",
    "SUBMISSION",
    "Reply to the assignment email with a link to a repository (or a zip).",
    "Please submit before the deadline stated in the email.",
    "",
    "(This is a placeholder brief generated for local development.)",
]


def build_assignment_brief(path: Path) -> None:
    """Render a simple one-page assignment brief PDF (Phase 5 attachment)."""
    c = canvas.Canvas(str(path), pagesize=LETTER)
    _width, height = LETTER
    y = height - inch
    for i, line in enumerate(ASSIGNMENT_BRIEF_LINES):
        if i == 0:
            c.setFont("Helvetica-Bold", 16)
        elif line.isupper() and line:
            c.setFont("Helvetica-Bold", 11)
        else:
            c.setFont("Helvetica", 10)
        c.drawString(inch, y, line)
        y -= 18
    c.showPage()
    c.save()


def main() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    text_path = SAMPLE_DIR / "sample_cv_text.pdf"
    text2_path = SAMPLE_DIR / "sample_cv_text_2.pdf"
    text3_path = SAMPLE_DIR / "sample_cv_text_3.pdf"
    text4_path = SAMPLE_DIR / "sample_cv_text_4.pdf"
    scanned_path = SAMPLE_DIR / "sample_cv_scanned.pdf"
    brief_path = SAMPLE_DIR / "assignment_brief.pdf"
    build_text_cv(text_path)
    build_text_cv(text2_path, pages=TEXT_CV_2_PAGES)
    build_text_cv(text3_path, pages=TEXT_CV_3_PAGES)
    build_text_cv(text4_path, pages=TEXT_CV_4_PAGES)
    build_scanned_cv(scanned_path)
    build_assignment_brief(brief_path)
    for p in (text_path, text2_path, text3_path, text4_path, scanned_path, brief_path):
        print(f"Wrote {p}")


if __name__ == "__main__":
    main()
