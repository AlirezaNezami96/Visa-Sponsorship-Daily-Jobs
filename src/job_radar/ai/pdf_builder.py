"""Deterministic ATS-safe PDF assembly (fpdf2 — no AI in layout).

AI produces structured JSON only (validators in engine/ai/validators.py
guarantee grounding before anything reaches here); this module turns that
JSON into resume / cover-letter PDFs with fixed typography:

- Inter for body (10.5-11pt), Poppins for the name + section headers.
- Single column, 0.75in margins, standard headings — no tables, graphics or
  multi-column layouts, so ATS parsers see plain text in reading order.
- "professional" fixed order: Summary -> Skills -> Experience -> Education -> Links.
- "own" order from profile["section_order"] (default = resume parse order).
- Page caps enforced by dropping whole trailing bullets (never mid-word):
  resume <= 2 pages, cover letter <= 1 page.
- Fixed CreationDate metadata -> identical inputs produce identical bytes.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

try:
    from fpdf import FPDF

    _BaseDoc = FPDF
except ImportError:
    FPDF = None  # type: ignore[assignment, misc]
    _BaseDoc = object  # type: ignore[misc, assignment]

# Bundled OFL fonts (Poppins + Inter statics). Resolved locally — this module
# deliberately imports nothing else from job_radar so the engine container can
# load it without the pipeline's dependency chain. System fonts are NEVER used.
_REPO_ROOT = Path(__file__).resolve().parents[3]
FONTS_DIR = _REPO_ROOT / "assets" / "fonts"
_FONT_FILES = {
    "poppins_bold": "Poppins-Bold.ttf",
    "poppins_semibold": "Poppins-SemiBold.ttf",
    "inter_regular": "Inter-Regular.ttf",
    "inter_medium": "Inter-Medium.ttf",
    "inter_bold": "Inter-Bold.ttf",
}


def _font_path(key: str) -> Path:
    path = FONTS_DIR / _FONT_FILES[key]
    if not path.is_file():
        raise FileNotFoundError(f"Bundled font missing: {path}. System fonts are intentionally never used.")
    return path


MARGIN_IN = 0.75
PAGE_W_MM = 210
PAGE_H_MM = 297
CONTENT_W_MM = PAGE_W_MM - 2 * MARGIN_IN * 25.4

RESUME_MAX_PAGES = 2
COVER_LETTER_MAX_PAGES = 1

FIXED_CREATION_DATE = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.UTC)

PROFESSIONAL_ORDER = ["summary", "skills", "experience", "education", "links"]
DEFAULT_OWN_ORDER = ["summary", "experience", "education", "skills", "links"]

SECTION_TITLES = {
    "summary": "SUMMARY",
    "skills": "SKILLS",
    "experience": "EXPERIENCE",
    "education": "EDUCATION",
    "links": "LINKS",
}


class _Doc(_BaseDoc):
    def __init__(self):
        if FPDF is None:
            raise RuntimeError("fpdf2 is not installed. Install with `pip install fpdf2` to build PDFs.")
        super().__init__(format="A4")
        self.set_auto_page_break(True, margin=MARGIN_IN * 25.4)
        self.set_margins(MARGIN_IN * 25.4, MARGIN_IN * 25.4, MARGIN_IN * 25.4)
        self.creation_date = FIXED_CREATION_DATE
        self.add_font("Inter", "", str(_font_path("inter_regular")))
        self.add_font("Inter", "B", str(_font_path("inter_bold")))
        self.add_font("Poppins", "", str(_font_path("poppins_semibold")))
        self.add_font("Poppins", "B", str(_font_path("poppins_bold")))

    # ── typography helpers ──

    def name_line(self, text: str) -> None:
        self.set_font("Poppins", "B", 20)
        self.set_text_color(14, 27, 60)
        self.multi_cell(CONTENT_W_MM, 8, text)
        self.ln(1)

    def contact_line(self, text: str) -> None:
        self.set_font("Inter", "", 9)
        self.set_text_color(90, 100, 115)
        self.multi_cell(CONTENT_W_MM, 4.5, text)
        self.ln(2.5)

    def section_header(self, title: str) -> None:
        self.ln(1.5)
        self.set_font("Poppins", "", 12)
        self.set_text_color(14, 27, 60)
        self.cell(CONTENT_W_MM, 6, title.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(226, 59, 59)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.l_margin + 24, self.get_y())
        self.ln(2.5)

    def body(self, text: str, size: float = 10.5) -> None:
        self.set_font("Inter", "", size)
        self.set_text_color(30, 38, 50)
        self.multi_cell(CONTENT_W_MM, 5.2, text)

    def bullet(self, text: str, size: float = 10.5) -> None:
        self.set_font("Inter", "", size)
        self.set_text_color(30, 38, 50)
        x = self.get_x()
        self.cell(4.5, 5.2, "\u2022")
        self.multi_cell(CONTENT_W_MM - 4.5, 5.2, text)
        self.set_x(x)
        self.ln(0.6)


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _contact_bits(profile: dict[str, Any]) -> str:
    parts: list[str] = []
    contact = profile.get("contact") or {}
    for value in (
        profile.get("email") or contact.get("email"),
        profile.get("phone") or contact.get("phone"),
        profile.get("location") or contact.get("location"),
        contact.get("website") or profile.get("website"),
        contact.get("linkedin") or profile.get("linkedin"),
    ):
        value = _clean(value)
        if value:
            parts.append(value)
    return "  |  ".join(parts)


def _sections_from_markdown(markdown: str) -> dict[str, Any]:
    """Best-effort structured-section fallback from tailored markdown."""
    sections: dict[str, Any] = {}
    current: str | None = None
    bucket: list[str] = []
    key_by_title = {v.lower(): k for k, v in SECTION_TITLES.items()} | {
        "professional experience": "experience",
        "work experience": "experience",
        "technical skills": "skills",
        "personal links": "links",
    }

    def flush():
        nonlocal current, bucket
        if current:
            sections.setdefault(current, []).extend(bucket)
        bucket = []

    for line in markdown.splitlines():
        heading = re.match(r"^#{1,3}\s*(.+?)\s*$", line)
        if heading:
            flush()
            current = key_by_title.get(heading.group(1).strip().lower())
            continue
        text = _clean(line.lstrip("-•* ").strip())
        if text and current:
            bucket.append(text)
    flush()
    return sections


def _structured_sections(tailored: dict[str, Any]) -> dict[str, Any]:
    """Prefer AI-structured sections; fall back to parsing the markdown.

    Accepts both the wrapped shape ``{"sections": {...}}`` and the flat shape
    ``{"summary": ..., "skills": [...], ...}`` that models sometimes return.
    """
    if isinstance(tailored, dict):
        inner = tailored.get("sections")
        if isinstance(inner, dict) and any(inner.get(k) for k in SECTION_TITLES):
            return inner
        if any(tailored.get(k) for k in SECTION_TITLES):
            return {k: tailored[k] for k in SECTION_TITLES if tailored.get(k)}
    return _sections_from_markdown(str(tailored.get("tailored_resume_markdown") or ""))


def _render_resume(doc: _Doc, profile: dict[str, Any], sections: dict[str, Any], order: list[str]) -> None:
    doc.add_page()
    doc.name_line(_clean(profile.get("full_name")) or "Candidate")
    contact = _contact_bits(profile)
    if contact:
        doc.contact_line(contact)

    for key in order:
        if key == "summary":
            summary_raw = sections.get("summary") or profile.get("summary") or profile.get("about_me")
            if isinstance(summary_raw, list):
                summary_raw = " ".join(summary_raw)
            summary = _clean(summary_raw)
            if not summary:
                continue
            doc.section_header("SUMMARY")
            doc.body(summary)
        elif key == "skills":
            skills = sections.get("skills") or profile.get("skills") or []
            if isinstance(skills, str):
                skills = [s.strip() for s in skills.split(",") if s.strip()]
            if not skills:
                continue
            doc.section_header("SKILLS")
            doc.body(" • ".join(_clean(s) for s in skills if _clean(s)))
        elif key == "experience":
            entries = sections.get("experience") or []
            if not entries:
                continue
            doc.section_header("EXPERIENCE")
            plain_lines = [e for e in entries if isinstance(e, str)]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                title = _clean(entry.get("title"))
                company = _clean(entry.get("company"))
                start, end = _clean(entry.get("start")), _clean(entry.get("end"))
                dates = " – ".join(p for p in (start, end or "Present") if p)
                headline = " — ".join(p for p in (title, company) if p)
                if dates:
                    headline = f"{headline}  ({dates})" if headline else dates
                if headline:
                    doc.set_font("Inter", "B", 10.5)
                    doc.set_text_color(14, 27, 60)
                    doc.multi_cell(CONTENT_W_MM, 5.2, headline)
                    doc.ln(0.4)
                for bullet in entry.get("bullets") or []:
                    text = _clean(bullet)
                    if text:
                        doc.bullet(text)
                doc.ln(1.2)
            # Markdown-fallback bullets arrive as flat strings.
            for line in plain_lines:
                text = _clean(line)
                if text:
                    doc.bullet(text)
            if plain_lines:
                doc.ln(1.2)
        elif key == "education":
            entries = sections.get("education") or []
            if not entries:
                continue
            doc.section_header("EDUCATION")
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                institution = _clean(entry.get("institution"))
                degree = _clean(entry.get("degree"))
                year = _clean(entry.get("year") or entry.get("end"))
                line = " — ".join(p for p in (degree, institution) if p)
                if year:
                    line = f"{line}  ({year})" if line else year
                if line:
                    doc.body(line, size=10.5)
                    doc.ln(0.8)
        elif key == "links":
            links = sections.get("links") or []
            if isinstance(links, str):
                links = [links]
            links = [_clean(l) for l in links if _clean(l)]
            if not links:
                continue
            doc.section_header("LINKS")
            for link in links:
                doc.body(link)


def build_resume_pdf(
    profile: dict[str, Any],
    tailored: dict[str, Any],
    format_type: str = "professional",
) -> bytes:
    """Assemble the tailored resume PDF (<= 2 pages, deterministic bytes)."""
    sections = _structured_sections(tailored)
    order = PROFESSIONAL_ORDER
    if format_type == "own":
        requested = profile.get("section_order")
        if isinstance(requested, list) and requested:
            order = [k for k in requested if k in SECTION_TITLES]
        if not order:
            order = DEFAULT_OWN_ORDER

    def render(bullet_budget: int | None) -> _Doc:
        bounded = _apply_bullet_budget(sections, bullet_budget)
        doc = _Doc()
        _render_resume(doc, profile, bounded, order)
        return doc

    doc = render(None)
    if doc.page > RESUME_MAX_PAGES:
        # Shrink the bullet budget until the document fits (whole bullets only).
        total = _count_bullets(sections)
        lo, hi = 0, total
        best: _Doc | None = None
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = render(mid)
            if candidate.page <= RESUME_MAX_PAGES:
                best = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        doc = best or render(0)
        # If even zero bullets overflows (huge summary), accept the 2-page head:
        if doc.page > RESUME_MAX_PAGES:
            doc = render(0)

    return bytes(doc.output())


def _count_bullets(sections: dict[str, Any]) -> int:
    count = 0
    for entry in sections.get("experience") or []:
        if isinstance(entry, dict):
            count += len(entry.get("bullets") or [])
        elif isinstance(entry, str):
            count += 1
    return count


def _apply_bullet_budget(sections: dict[str, Any], budget: int | None) -> dict[str, Any]:
    """Return sections capped at `budget` experience bullets (None = no cap)."""
    if budget is None:
        return sections
    out = dict(sections)
    remaining = budget
    trimmed: list[Any] = []
    for entry in sections.get("experience") or []:
        if not isinstance(entry, dict):
            if remaining > 0:
                trimmed.append(entry)
                remaining -= 1
            continue
        bullets = list(entry.get("bullets") or [])
        kept = bullets[: max(remaining, 0)]
        remaining -= len(kept)
        trimmed.append({**entry, "bullets": kept})
    out["experience"] = trimmed
    return out


def build_cover_letter_pdf(
    profile: dict[str, Any],
    cover_letter: dict[str, Any],
    job: dict[str, Any],
) -> bytes:
    """Assemble the cover-letter PDF (<= 1 page, deterministic bytes)."""
    doc = _Doc()
    doc.add_page()
    doc.name_line(_clean(profile.get("full_name")) or "Candidate")
    contact = _contact_bits(profile)
    if contact:
        doc.contact_line(contact)

    today = FIXED_CREATION_DATE.strftime("%B %d, %Y")
    doc.body(today)
    doc.ln(2)

    company = _clean(job.get("company"))
    location = _clean(job.get("location"))
    addr = " — ".join(p for p in (company, location) if p)
    if addr:
        doc.body(addr)
        doc.ln(3)

    markdown = str(cover_letter.get("cover_letter_markdown") or "")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", markdown) if p.strip()]
    for paragraph in paragraphs[:6]:
        doc.body(paragraph, size=10.5)
        doc.ln(2.5)

    doc.ln(2)
    name = _clean(profile.get("full_name"))
    if name:
        doc.body("Sincerely,")
        doc.set_font("Inter", "B", 10.5)
        doc.cell(CONTENT_W_MM, 5.2, name, new_x="LMARGIN", new_y="NEXT")

    if doc.page > COVER_LETTER_MAX_PAGES:
        # Rebuild with fewer paragraphs until it fits one page.
        for drop in range(1, len(paragraphs)):
            retry = _Doc()
            retry.add_page()
            retry.name_line(_clean(profile.get("full_name")) or "Candidate")
            if contact:
                retry.contact_line(contact)
            retry.body(today)
            retry.ln(2)
            if addr:
                retry.body(addr)
                retry.ln(3)
            for paragraph in paragraphs[: len(paragraphs) - drop]:
                retry.body(paragraph, size=10.5)
                retry.ln(2.5)
            retry.ln(2)
            if name:
                retry.body("Sincerely,")
                retry.set_font("Inter", "B", 10.5)
                retry.cell(CONTENT_W_MM, 5.2, name, new_x="LMARGIN", new_y="NEXT")
            if retry.page <= COVER_LETTER_MAX_PAGES:
                return bytes(retry.output())

    return bytes(doc.output())


def build_outreach_email_pdf(
    profile: dict[str, Any],
    outreach: dict[str, Any],
    job: dict[str, Any],
) -> bytes:
    """Assemble an outreach email PDF (<= 1 page)."""
    doc = _Doc()
    doc.add_page()
    doc.name_line(_clean(profile.get("full_name")) or "Candidate")
    contact = _contact_bits(profile)
    if contact:
        doc.contact_line(contact)

    today = FIXED_CREATION_DATE.strftime("%B %d, %Y")
    doc.body(today)
    doc.ln(3)

    subject = outreach.get("cold_email", {}).get("subject") or outreach.get("subject", "Outreach")
    doc.set_font("Inter", "B", 11)
    doc.cell(CONTENT_W_MM, 6.0, f"Subject: {subject}", new_x="LMARGIN", new_y="NEXT")
    doc.ln(2)

    body_text = outreach.get("cold_email", {}).get("body") or outreach.get("body", "")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body_text) if p.strip()]
    for p in paragraphs:
        doc.body(p, size=10.5)
        doc.ln(2.5)

    return bytes(doc.output())
