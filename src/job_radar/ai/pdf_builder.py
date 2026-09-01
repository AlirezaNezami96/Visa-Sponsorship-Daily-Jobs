"""Deterministic ATS-safe PDF assembly (fpdf2 — no AI in layout).

AI produces structured JSON only (validators in engine/ai/validators.py
guarantee grounding before anything reaches here); this module turns that
JSON into resume / cover-letter PDFs with fixed typography:

- Inter for body (10.5-11pt), Poppins for the name + section headers.
- Single column, 0.75in margins, standard headings — no tables, graphics or
  multi-column layouts, so ATS parsers see plain text in reading order.
- "professional" fixed order: Summary -> Skills -> Experience -> Projects -> Education -> Certifications -> Publications -> Awards -> Languages -> Volunteer -> Links -> Interests.
- "own" order from profile["section_order"] or output_json["sections"] (verbatim sequence & labels).
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

# Bundled OFL fonts (Poppins + Inter statics).
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

PROFESSIONAL_ORDER = [
    "summary",
    "skills",
    "experience",
    "projects",
    "education",
    "certifications",
    "publications",
    "awards",
    "languages",
    "volunteer_work",
    "links",
    "interests",
]

DEFAULT_OWN_ORDER = [
    "summary",
    "experience",
    "education",
    "skills",
    "projects",
    "certifications",
    "publications",
    "awards",
    "languages",
    "volunteer_work",
    "links",
]

SECTION_TITLES = {
    "summary": "PROFESSIONAL SUMMARY",
    "skills": "CORE SKILLS",
    "experience": "PROFESSIONAL EXPERIENCE",
    "education": "EDUCATION",
    "projects": "PROJECTS",
    "certifications": "CERTIFICATIONS",
    "publications": "PUBLICATIONS",
    "awards": "HONORS & AWARDS",
    "languages": "LANGUAGES",
    "volunteer_work": "VOLUNTEER EXPERIENCE",
    "links": "LINKS",
    "interests": "INTERESTS",
}


class _Doc(_BaseDoc):  # type: ignore[valid-type, misc]
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
        self.set_font("Poppins", "B", 18)
        self.set_text_color(14, 27, 60)
        self.multi_cell(CONTENT_W_MM, 7.5, text)
        self.ln(1)

    def contact_line(self, text: str) -> None:
        self.set_font("Inter", "", 9)
        self.set_text_color(90, 100, 115)
        self.multi_cell(CONTENT_W_MM, 4.5, text)
        self.ln(2.0)

    def section_header(self, title: str) -> None:
        self.ln(1.5)
        self.set_font("Poppins", "", 11.5)
        self.set_text_color(14, 27, 60)
        self.cell(CONTENT_W_MM, 5.5, title.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(226, 59, 59)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.l_margin + 24, self.get_y())
        self.ln(2.0)

    def body(self, text: str, size: float = 10.0) -> None:
        self.set_font("Inter", "", size)
        self.set_text_color(30, 38, 50)
        self.multi_cell(CONTENT_W_MM, 4.8, text)

    def bullet(self, text: str, size: float = 9.5) -> None:
        self.set_font("Inter", "", size)
        self.set_text_color(30, 38, 50)
        x = self.get_x()
        self.cell(4.5, 4.8, "\u2022")
        self.multi_cell(CONTENT_W_MM - 4.5, 4.8, text)
        self.set_x(x)
        self.ln(0.5)


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
        contact.get("github") or profile.get("github"),
    ):
        value = _clean(value)
        if value and value not in parts:
            parts.append(value)
    return "  |  ".join(parts)


def _render_summary(doc: _Doc, items: Any) -> None:
    text = ""
    if isinstance(items, str):
        text = items
    elif isinstance(items, list):
        text = " ".join(str(i) for i in items if i)
    text = _clean(text)
    if text:
        doc.body(text, size=10.0)
        doc.ln(1.0)


def _render_skills(doc: _Doc, items: Any) -> None:
    if isinstance(items, list):
        skill_strs: list[str] = []
        for it in items:
            if isinstance(it, str) and _clean(it):
                skill_strs.append(_clean(it))
            elif isinstance(it, dict):
                cat = it.get("category") or it.get("name")
                sk = it.get("skills") or it.get("items")
                if cat and sk:
                    sk_list = ", ".join(sk) if isinstance(sk, list) else str(sk)
                    skill_strs.append(f"{cat}: {sk_list}")
                elif cat:
                    skill_strs.append(str(cat))
        if skill_strs:
            doc.body(" • ".join(skill_strs), size=10.0)
            doc.ln(1.0)
    elif isinstance(items, str) and _clean(items):
        doc.body(_clean(items), size=10.0)
        doc.ln(1.0)


def _render_experience(doc: _Doc, items: Any) -> None:
    if not isinstance(items, list):
        return
    for entry in items:
        if isinstance(entry, dict):
            title = _clean(entry.get("title"))
            company = _clean(entry.get("company"))
            start, end = _clean(entry.get("start")), _clean(entry.get("end"))
            dates = f"{start} – {end}" if start and end else start or end or "Present"
            headline = f"{title} | {company}" if title and company else title or company
            if dates:
                headline = f"{headline}   ({dates})" if headline else dates
            if headline:
                doc.set_font("Inter", "B", 10.0)
                doc.set_text_color(14, 27, 60)
                doc.multi_cell(CONTENT_W_MM, 5.0, headline)
                doc.ln(0.4)
            bullets = entry.get("bullets") or entry.get("highlights") or []
            if isinstance(bullets, list):
                for b in bullets:
                    b_text = _clean(b)
                    if b_text:
                        doc.bullet(b_text)
            doc.ln(1.0)
        elif isinstance(entry, str) and _clean(entry):
            doc.bullet(_clean(entry))


def _render_projects(doc: _Doc, items: Any) -> None:
    if not isinstance(items, list):
        return
    for proj in items:
        if not isinstance(proj, dict):
            continue
        name = _clean(proj.get("name"))
        tech = proj.get("technologies") or []
        desc = _clean(proj.get("description"))
        bullets = proj.get("bullets") or []

        headline = name
        if tech and isinstance(tech, list):
            t_str = ", ".join(str(t) for t in tech if t)
            if t_str:
                headline = f"{headline} | {t_str}"
        if headline:
            doc.set_font("Inter", "B", 9.5)
            doc.set_text_color(14, 27, 60)
            doc.multi_cell(CONTENT_W_MM, 4.8, headline)
            doc.ln(0.3)
        if desc:
            doc.bullet(desc)
        if isinstance(bullets, list):
            for b in bullets:
                b_text = _clean(b)
                if b_text and b_text != desc:
                    doc.bullet(b_text)
        doc.ln(0.8)


def _render_education(doc: _Doc, items: Any) -> None:
    if not isinstance(items, list):
        return
    for edu in items:
        if not isinstance(edu, dict):
            continue
        inst = _clean(edu.get("institution"))
        deg = _clean(edu.get("degree"))
        year = _clean(edu.get("year") or edu.get("end"))
        line = f"{deg}, {inst}" if deg and inst else deg or inst
        if year:
            line = f"{line} ({year})" if line else year
        if line:
            doc.body(line, size=9.5)
            doc.ln(0.5)


def _render_certifications(doc: _Doc, items: Any) -> None:
    if not isinstance(items, list):
        return
    for cert in items:
        if not isinstance(cert, dict):
            continue
        name = _clean(cert.get("name"))
        issuer = _clean(cert.get("issuer"))
        year = _clean(cert.get("year"))
        line = f"{name} – {issuer}" if name and issuer else name or issuer
        if year:
            line = f"{line} ({year})" if line else year
        if line:
            doc.bullet(line)


def _render_publications(doc: _Doc, items: Any) -> None:
    if not isinstance(items, list):
        return
    for pub in items:
        if not isinstance(pub, dict):
            continue
        title = _clean(pub.get("title"))
        venue = _clean(pub.get("venue"))
        year = _clean(pub.get("year"))
        line = f'"{title}", {venue}' if title and venue else f'"{title}"' if title else venue
        if year:
            line = f"{line} ({year})" if line else year
        if line:
            doc.bullet(line)


def _render_awards(doc: _Doc, items: Any) -> None:
    if not isinstance(items, list):
        return
    for aw in items:
        if not isinstance(aw, dict):
            continue
        title = _clean(aw.get("title"))
        issuer = _clean(aw.get("issuer"))
        year = _clean(aw.get("year"))
        line = f"{title} – {issuer}" if title and issuer else title or issuer
        if year:
            line = f"{line} ({year})" if line else year
        if line:
            doc.bullet(line)


def _render_languages(doc: _Doc, items: Any) -> None:
    if not isinstance(items, list):
        return
    lang_bits: list[str] = []
    for lang in items:
        if isinstance(lang, dict):
            l_name = _clean(lang.get("language"))
            l_prof = _clean(lang.get("proficiency"))
            if l_name and l_prof:
                lang_bits.append(f"{l_name} ({l_prof})")
            elif l_name:
                lang_bits.append(l_name)
        elif isinstance(lang, str) and _clean(lang):
            lang_bits.append(_clean(lang))
    if lang_bits:
        doc.body(" • ".join(lang_bits), size=9.5)
        doc.ln(1.0)


def _render_volunteer_work(doc: _Doc, items: Any) -> None:
    if not isinstance(items, list):
        return
    for vol in items:
        if not isinstance(vol, dict):
            continue
        org = _clean(vol.get("organization"))
        role = _clean(vol.get("role"))
        desc = _clean(vol.get("description"))
        line = f"{role} | {org}" if role and org else role or org
        if line:
            doc.set_font("Inter", "B", 9.5)
            doc.set_text_color(14, 27, 60)
            doc.multi_cell(CONTENT_W_MM, 4.8, line)
            doc.ln(0.3)
        if desc:
            doc.bullet(desc)
        doc.ln(0.8)


def _render_links(doc: _Doc, items: Any) -> None:
    if isinstance(items, list):
        link_strs: list[str] = []
        for it in items:
            if isinstance(it, dict):
                t = it.get("type") or "link"
                u = it.get("url")
                if u:
                    link_strs.append(f"{t}: {u}")
            elif isinstance(it, str) and _clean(it):
                link_strs.append(_clean(it))
        if link_strs:
            doc.body("  |  ".join(link_strs), size=9.0)
            doc.ln(1.0)


def _render_interests(doc: _Doc, items: Any) -> None:
    if isinstance(items, list):
        valid = [_clean(i) for i in items if _clean(i)]
        if valid:
            doc.body(", ".join(valid), size=9.5)
            doc.ln(1.0)


PDF_RENDERERS = {
    "summary": _render_summary,
    "skills": _render_skills,
    "experience": _render_experience,
    "education": _render_education,
    "projects": _render_projects,
    "certifications": _render_certifications,
    "publications": _render_publications,
    "awards": _render_awards,
    "languages": _render_languages,
    "volunteer_work": _render_volunteer_work,
    "links": _render_links,
    "interests": _render_interests,
}


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
            if current == "summary":
                sections[current] = " ".join(bucket)
            else:
                sections.setdefault(current, []).extend(bucket)
        bucket = []

    for line in markdown.splitlines():
        heading = re.match(r"^#{1,3}\s*(.+?)\s*$", line)
        if heading:
            flush()
            norm_title = heading.group(1).strip().lower()
            current = key_by_title.get(norm_title)
            if not current:
                for k in SECTION_TITLES:
                    if k in norm_title:
                        current = k
                        break
            continue
        text = _clean(line.lstrip("-•* ").strip())
        if text and current:
            bucket.append(text)
    flush()
    return sections


def _extract_ordered_sections(tailored: dict[str, Any], profile: dict[str, Any], format_type: str) -> list[tuple[str, str, Any]]:
    ordered_sections: list[tuple[str, str, Any]] = []

    sections_payload = tailored.get("sections")
    if isinstance(sections_payload, list):
        for item in sections_payload:
            if isinstance(item, dict) and "type" in item:
                s_type = str(item["type"]).lower()
                s_label = str(item.get("label") or SECTION_TITLES.get(s_type, s_type.upper()))
                s_items = item.get("items")
                if s_items is not None and s_type in PDF_RENDERERS:
                    ordered_sections.append((s_type, s_label, s_items))
    elif isinstance(sections_payload, dict):
        for s_type, s_items in sections_payload.items():
            if s_items is not None and s_type in PDF_RENDERERS:
                s_label = SECTION_TITLES.get(s_type, s_type.upper())
                ordered_sections.append((s_type, s_label, s_items))

    if not ordered_sections and tailored.get("tailored_resume_markdown"):
        md_sections = _sections_from_markdown(str(tailored.get("tailored_resume_markdown") or ""))
        for s_type, s_items in md_sections.items():
            if s_items and s_type in PDF_RENDERERS:
                s_label = SECTION_TITLES.get(s_type, s_type.upper())
                ordered_sections.append((s_type, s_label, s_items))

    final_sections: list[tuple[str, str, Any]] = []
    if format_type == "own":
        section_order = profile.get("section_order") or []
        if isinstance(section_order, list) and len(section_order) > 0:
            section_map = {s[0]: s for s in ordered_sections}
            for entry in section_order:
                if isinstance(entry, dict) and "type" in entry:
                    e_type = str(entry["type"]).lower()
                    if e_type in section_map:
                        custom_label = str(entry.get("label") or section_map[e_type][1])
                        final_sections.append((e_type, custom_label, section_map[e_type][2]))
                        del section_map[e_type]
                elif isinstance(entry, str):
                    e_type = entry.lower()
                    if e_type in section_map:
                        final_sections.append((e_type, section_map[e_type][1], section_map[e_type][2]))
                        del section_map[e_type]
            for rem in section_map.values():
                final_sections.append(rem)
        else:
            final_sections = ordered_sections
    else:
        section_map = {s[0]: s for s in ordered_sections}
        for s_type in PROFESSIONAL_ORDER:
            if s_type in section_map:
                final_sections.append((s_type, SECTION_TITLES.get(s_type, s_type.upper()), section_map[s_type][2]))
                del section_map[s_type]
        for rem in section_map.values():
            final_sections.append(rem)

    return final_sections


def _render_full_resume(doc: _Doc, profile: dict[str, Any], sections_list: list[tuple[str, str, Any]]) -> None:
    doc.add_page()
    doc.name_line(_clean(profile.get("full_name")) or "Candidate")
    contact = _contact_bits(profile)
    if contact:
        doc.contact_line(contact)

    for s_type, s_label, s_items in sections_list:
        renderer = PDF_RENDERERS.get(s_type)
        if renderer:
            doc.section_header(s_label)
            renderer(doc, s_items)


def _count_bullets_in_sections(sections_list: list[tuple[str, str, Any]]) -> int:
    count = 0
    for s_type, _, s_items in sections_list:
        if s_type == "experience" and isinstance(s_items, list):
            for entry in s_items:
                if isinstance(entry, dict):
                    count += len(entry.get("bullets") or entry.get("highlights") or [])
                elif isinstance(entry, str):
                    count += 1
    return count


def _apply_bullet_budget_to_list(sections_list: list[tuple[str, str, Any]], budget: int | None) -> list[tuple[str, str, Any]]:
    if budget is None:
        return sections_list
    remaining = budget
    out: list[tuple[str, str, Any]] = []
    for s_type, s_label, s_items in sections_list:
        if s_type == "experience" and isinstance(s_items, list):
            trimmed: list[Any] = []
            for entry in s_items:
                if isinstance(entry, dict):
                    bullets = list(entry.get("bullets") or entry.get("highlights") or [])
                    kept = bullets[: max(remaining, 0)]
                    remaining -= len(kept)
                    trimmed.append({**entry, "bullets": kept})
                elif isinstance(entry, str):
                    if remaining > 0:
                        trimmed.append(entry)
                        remaining -= 1
            out.append((s_type, s_label, trimmed))
        else:
            out.append((s_type, s_label, s_items))
    return out


def build_resume_pdf(
    profile: dict[str, Any],
    tailored: dict[str, Any],
    format_type: str = "professional",
) -> bytes:
    """Assemble the tailored resume PDF (<= 2 pages, deterministic bytes)."""
    sections_list = _extract_ordered_sections(tailored, profile, format_type)

    def render(budget: int | None) -> _Doc:
        bounded = _apply_bullet_budget_to_list(sections_list, budget)
        doc = _Doc()
        _render_full_resume(doc, profile, bounded)
        return doc

    doc = render(None)
    if doc.page > RESUME_MAX_PAGES:
        total = _count_bullets_in_sections(sections_list)
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
        if doc.page > RESUME_MAX_PAGES:
            doc = render(0)

    return bytes(doc.output())


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
