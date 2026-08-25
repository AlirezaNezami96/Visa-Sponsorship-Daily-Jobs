"""HTML Email template renderers for Job Radar digests."""
from __future__ import annotations

import datetime
import html as html_lib
from typing import Any, Dict, List, Optional


def _render_ats_block(resume_match: Optional[dict]) -> str:
    """Render the ATS match block for a job card.

    Returns an empty string if resume_match is None or missing required fields.
    The editing prompt is wrapped in a <details> block so it's hidden by default
    and selectable when expanded (compatible with Gmail's renderer).
    """
    if not resume_match or not isinstance(resume_match, dict):
        return ""

    ats_score = resume_match.get("ats_score")
    if ats_score is None:
        return ""

    keywords_to_add = resume_match.get("keywords_to_add", []) or []
    editing_prompt = resume_match.get("resume_editing_prompt", "") or ""
    score_rationale = resume_match.get("score_rationale", "") or ""

    # Color-code the score: green ≥ 70, amber 50–69, red < 50
    if ats_score >= 70:
        score_bg = "#F0FDF4"
        score_color = "#166534"
        score_border = "#4ADE80"
    elif ats_score >= 50:
        score_bg = "#FFFBEB"
        score_color = "#92400E"
        score_border = "#FCD34D"
    else:
        score_bg = "#FEF2F2"
        score_color = "#991B1B"
        score_border = "#FCA5A5"

    parts = [
        f'<div style="margin-top:10px;padding:10px 12px;background:{score_bg};border-left:3px solid {score_border};border-radius:0 6px 6px 0;">',
        f'<div style="font-size:12px;font-weight:700;color:{score_color};margin-bottom:4px;">📊 ATS Match: {ats_score}%</div>',
    ]

    if score_rationale:
        escaped_rationale = html_lib.escape(score_rationale)
        parts.append(
            f'<div style="font-size:12px;color:#475569;margin-bottom:6px;">{escaped_rationale}</div>'
        )

    if keywords_to_add:
        kw_display = html_lib.escape(", ".join(keywords_to_add[:8]))
        parts.append(
            f'<div style="font-size:11px;color:#64748B;margin-bottom:6px;">'
            f'<strong>Keywords to add:</strong> {kw_display}</div>'
        )

    if editing_prompt:
        escaped_prompt = html_lib.escape(editing_prompt)
        parts.append(
            '<details style="margin-top:4px;">'
            '<summary style="font-size:11px;color:#6366F1;cursor:pointer;font-weight:600;">✏️ View resume editing prompt</summary>'
            f'<pre style="font-size:11px;color:#334155;white-space:pre-wrap;word-break:break-word;margin:6px 0 0 0;padding:8px;background:#F8FAFC;border-radius:4px;font-family:ui-monospace,monospace;">{escaped_prompt}</pre>'
            '</details>'
        )

    parts.append('</div>')
    return "\n".join(parts)


def _render_job_card(
    j: dict,
    accent_color: str = "#6366F1",
    show_visa_tag: bool = True,
    resume_match: Optional[dict] = None,
) -> str:
    """Render a clean, responsive job card for HTML email."""
    title = html_lib.escape(j.get("title", "Untitled Role"))
    company = html_lib.escape(j.get("company", "Company"))
    url = html_lib.escape(j.get("url", "#"))
    location = html_lib.escape(j.get("location", "Remote"))
    why = html_lib.escape(j.get("why_matched", ""))
    score = j.get("relevance_score", 0)
    source = html_lib.escape(j.get("source", "Direct ATS"))
    salary = html_lib.escape(j.get("salary")) if j.get("salary") else None
    has_visa = j.get("visa_sponsorship") is True

    # Fall back to resume_match embedded in the job dict itself
    if resume_match is None:
        resume_match = j.get("resume_match")

    remote_scope = j.get("remote_scope", "worldwide")
    allowed_regs = j.get("allowed_regions", [])
    if remote_scope == "worldwide" or "worldwide" in location.lower():
        remote_badge = "🌍 Remote (Worldwide)"
    elif allowed_regs and allowed_regs != ["Worldwide"]:
        remote_badge = f"📍 Remote ({', '.join(allowed_regs[:2])})"
    else:
        remote_badge = f"📍 {location}"

    badges = [
        f'<span style="background:#EEF2FF;color:#4338CA;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600;">{remote_badge}</span>',
        f'<span style="background:#F0FDF4;color:#166534;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600;">🎯 {score}% Match</span>',
    ]
    if salary:
        badges.append(f'<span style="background:#FEF3C7;color:#92400E;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:500;">💰 {salary}</span>')
    # Visa Sponsorship Badge
    visa_status = j.get("visa_status", "sponsors" if has_visa else "unknown")
    if show_visa_tag:
        if visa_status == "sponsors":
            badges.append('<span style="background:#DCFCE7;color:#15803D;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:700;">🏛️ Visa Sponsor: Confirmed</span>')
        elif visa_status == "likely":
            badges.append('<span style="background:#E0E7FF;color:#3730A3;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600;">✨ Visa Sponsor: Likely</span>')
        elif visa_status == "opt_friendly":
            badges.append('<span style="background:#FEF3C7;color:#92400E;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600;">🎓 Visa: OPT / STEM-OPT Friendly</span>')
        elif visa_status == "no":
            badges.append('<span style="background:#FEE2E2;color:#991B1B;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:500;">🚫 Visa: No Sponsorship</span>')
        elif has_visa or (visa_status == "unknown" and j.get("visa_sponsorship")):
            badges.append('<span style="background:#FDF2F8;color:#9D174D;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600;">🛂 Visa Sponsor</span>')

    if source:
        badges.append(f'<span style="background:#F1F5F9;color:#475569;padding:3px 8px;border-radius:4px;font-size:11px;">🏷️ {source}</span>')

    why_block = ""
    if why:
        why_block = (
            f'<div style="margin-top:8px;padding:8px 12px;background:#F8FAFC;border-left:3px solid {accent_color};border-radius:0 4px 4px 0;font-size:13px;color:#334155;line-height:1.4;">'
            f'💡 <i>{why}</i>'
            f'</div>'
        )

    ats_block = _render_ats_block(resume_match)

    linkedin_url = j.get("company_linkedin_url")
    linkedin_badge = (
        f' · <a href="{html_lib.escape(linkedin_url)}" target="_blank" style="color:#0A66C2;text-decoration:none;font-weight:600;font-size:12px;text-transform:none;letter-spacing:normal;">💼 LinkedIn</a>'
        if linkedin_url
        else ""
    )

    return f"""
    <div style="margin-bottom:16px;padding:16px;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;">
        <div>
          <div style="font-size:13px;color:#64748B;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;">{company}{linkedin_badge}</div>
          <div style="font-size:16px;font-weight:700;color:#0F172A;margin-top:2px;">
            <a href="{url}" style="color:#1E293B;text-decoration:none;">{title}</a>
          </div>
        </div>
      </div>
      <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;">
        {' '.join(badges)}
      </div>
      {why_block}
      {ats_block}
      <div style="margin-top:12px;text-align:right;">
        <a href="{url}" target="_blank" style="display:inline-block;background:{accent_color};color:#FFFFFF;padding:6px 14px;font-size:13px;font-weight:600;text-decoration:none;border-radius:6px;">Apply Directly →</a>
      </div>
    </div>
    """


def build_radar_html(
    internships: List[dict],
    engineers: List[dict],
    health_info: Dict[str, Any],
    show_visa_tag: bool = True,
) -> str:
    """Build modern, mobile-friendly HTML digest for AI Radar."""
    date_str = datetime.datetime.now().strftime("%B %d, %Y")
    total_jobs = len(internships) + len(engineers)
    companies_count = health_info.get("companies_scanned", 0)
    boards_count = health_info.get("boards_scanned", 0)
    errors_count = health_info.get("errors", 0)

    html_parts = [
        '<!DOCTYPE html>',
        '<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>',
        '<body style="margin:0;padding:20px 0;background-color:#F8FAFC;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;">',
        '<div style="max-width:640px;margin:0 auto;background:#FFFFFF;border-radius:12px;overflow:hidden;border:1px solid #E2E8F0;">',

        # Header Banner
        '<div style="background:linear-gradient(135deg, #0F172A 0%, #1E1B4B 40%, #4338CA 100%);padding:28px 24px;color:#FFFFFF;text-align:center;">',
        '<h1 style="margin:0;font-size:22px;font-weight:800;letter-spacing:-0.5px;">🧠 AI & ML Remote Job Radar</h1>',
        f'<p style="margin:8px 0 0 0;font-size:14px;color:#C7D2FE;">'
        f'{len(internships)} Internships · {len(engineers)} Early-Career Engineers · {date_str}</p>',
        '</div>',

        # Main Body Content
        '<div style="padding:24px 20px;">',
    ]

    # 1. Internships Track
    html_parts.append(
        '<div style="margin-bottom:28px;">'
        '<div style="display:flex;align-items:center;margin-bottom:14px;border-bottom:2px solid #E0E7FF;padding-bottom:6px;">'
        '<h2 style="margin:0;font-size:18px;color:#1E1B4B;font-weight:700;">🎓 AI & Machine Learning Internships</h2>'
        f'<span style="margin-left:auto;background:#EEF2FF;color:#4338CA;font-weight:700;font-size:12px;padding:2px 8px;border-radius:12px;">{len(internships)}</span>'
        '</div>'
    )
    if internships:
        for job in internships:
            html_parts.append(_render_job_card(job, accent_color="#4F46E5", show_visa_tag=show_visa_tag))
    else:
        html_parts.append('<p style="font-size:13px;color:#94A3B8;font-style:italic;margin:10px 0 20px 4px;">No new AI internship openings matched today.</p>')
    html_parts.append('</div>')

    # 2. Engineer Track
    html_parts.append(
        '<div style="margin-bottom:20px;">'
        '<div style="display:flex;align-items:center;margin-bottom:14px;border-bottom:2px solid #D1FAE5;padding-bottom:6px;">'
        '<h2 style="margin:0;font-size:18px;color:#064E3B;font-weight:700;">🚀 Early-Career AI & ML Engineers</h2>'
        f'<span style="margin-left:auto;background:#ECFDF5;color:#059669;font-weight:700;font-size:12px;padding:2px 8px;border-radius:12px;">{len(engineers)}</span>'
        '</div>'
    )
    if engineers:
        for job in engineers:
            html_parts.append(_render_job_card(job, accent_color="#059669", show_visa_tag=show_visa_tag))
    else:
        html_parts.append('<p style="font-size:13px;color:#94A3B8;font-style:italic;margin:10px 0 20px 4px;">No new early-career engineer openings matched today.</p>')
    html_parts.append('</div>')

    # Footer and Health Stats
    html_parts.extend([
        '</div>',
        '<div style="background:#F1F5F9;padding:16px 20px;border-top:1px solid #E2E8F0;font-size:12px;color:#64748B;line-height:1.5;">',
        f'<div style="font-weight:600;color:#475569;margin-bottom:4px;">'
        f'⚡ Radar Health: Scanned {companies_count} companies + {boards_count} public APIs · {errors_count} error(s)</div>',
        '<div>Filtering: AI/ML specific · 0–2 yrs & Internships only · Worldwide & Region-Restricted Remote.</div>',
        '<div style="margin-top:6px;font-size:11px;color:#94A3B8;">'
        'Automated AI Job Radar · Powered by GitHub Actions</div>',
        '</div>',
        '</div>',
        '</body></html>',
    ])

    return "\n".join(html_parts)


def build_legacy_html(report: list, total_jobs: int) -> str:
    """Build simple HTML report for legacy visa jobs."""
    html_parts = [
        '<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', Roboto, sans-serif; max-width: 680px; margin: 0 auto; color: #1a1a1a;">',
        '<div style="background: linear-gradient(135deg, #4338CA 0%, #6366F1 100%); padding: 24px 28px; border-radius: 12px 12px 0 0;">',
        f'<h1 style="margin: 0; color: white; font-size: 22px;">Job Digest</h1>',
        f'<p style="margin: 6px 0 0; color: rgba(255,255,255,0.85); font-size: 14px;">{len(report)} companies · {total_jobs} new jobs</p>',
        '</div>',
        '<div style="padding: 20px 28px 28px; background: #fff; border: 1px solid #e8e8e8; border-top: none; border-radius: 0 0 12px 12px;">',
    ]
    for company, jobs in report:
        # Check if first job has company_linkedin_url
        co_linkedin = None
        for j in jobs:
            if j.get("company_linkedin_url"):
                co_linkedin = j.get("company_linkedin_url")
                break
        linkedin_link = (
            f' <a href="{html_lib.escape(co_linkedin)}" target="_blank" style="font-size:12px;color:#0A66C2;font-weight:normal;text-decoration:none;margin-left:8px;">💼 LinkedIn</a>'
            if co_linkedin
            else ""
        )
        html_parts.append(f'<h2 style="margin: 20px 0 8px; font-size: 17px; color: #333;">{company}{linkedin_link}</h2>')
        html_parts.append('<ul style="margin: 0; padding-left: 20px;">')
        for j in jobs:
            loc = j.get("location", "")
            # Include ATS score if available
            ats_score = ""
            rm = j.get("resume_match")
            if rm and isinstance(rm, dict) and rm.get("ats_score") is not None:
                ats_score = f' <span style="color:#6366F1;font-size:12px;">({rm["ats_score"]}% ATS)</span>'
            html_parts.append(f'<li style="margin: 6px 0;"><a href="{j["url"]}">{j["title"]}</a> {loc}{ats_score}</li>')
        html_parts.append('</ul>')
    html_parts.append('</div></div>')
    return "\n".join(html_parts)


def build_justjoin_html(
    ai_jobs: List[dict],
    mobile_jobs: List[dict],
) -> str:
    """Build modern, mobile-friendly HTML digest for JustJoin.it jobs."""
    date_str = datetime.datetime.now().strftime("%B %d, %Y")
    total_jobs = len(ai_jobs) + len(mobile_jobs)

    html_parts = [
        '<!DOCTYPE html>',
        '<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>',
        '<body style="margin:0;padding:20px 0;background-color:#F8FAFC;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;">',
        '<div style="max-width:640px;margin:0 auto;background:#FFFFFF;border-radius:12px;overflow:hidden;border:1px solid #E2E8F0;">',

        # Header Banner
        '<div style="background:linear-gradient(135deg, #FF1464 0%, #7B1FA2 50%, #1E1B4B 100%);padding:28px 24px;color:#FFFFFF;text-align:center;">',
        '<h1 style="margin:0;font-size:22px;font-weight:800;letter-spacing:-0.5px;">🚀 JustJoin.it Daily Digest</h1>',
        f'<p style="margin:8px 0 0 0;font-size:14px;color:#FCE7F3;">'
        f'{len(ai_jobs)} AI/ML · {len(mobile_jobs)} Mobile · {date_str}</p>',
        '</div>',

        # Main Body Content
        '<div style="padding:24px 20px;">',
    ]

    # Helper function to render a JustJoin job card
    def _render_jj_card(job: dict, accent_color: str) -> str:
        title = html_lib.escape(job.get("title", "Untitled Role"))
        company = html_lib.escape(job.get("company", "Company"))
        url = html_lib.escape(job.get("url", "#"))
        location = html_lib.escape(job.get("location", "All Locations"))
        salary = html_lib.escape(job.get("salary")) if job.get("salary") else None
        is_remote = job.get("remote", False)

        badges = []
        if is_remote:
            badges.append('<span style="background:#F0FDF4;color:#166534;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600;">🌍 Remote</span>')
        badges.append(f'<span style="background:#F1F5F9;color:#475569;padding:3px 8px;border-radius:4px;font-size:12px;">📍 {location}</span>')
        if salary:
            badges.append(f'<span style="background:#FEF3C7;color:#92400E;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600;">💰 {salary}</span>')

        ats_block = _render_ats_block(job.get("resume_match"))

        linkedin_url = job.get("company_linkedin_url")
        linkedin_badge = (
            f' · <a href="{html_lib.escape(linkedin_url)}" target="_blank" style="color:#0A66C2;text-decoration:none;font-weight:600;font-size:11px;text-transform:none;letter-spacing:normal;">💼 LinkedIn</a>'
            if linkedin_url
            else ""
        )

        return f"""
        <div style="margin-bottom:14px;padding:14px;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;box-shadow:0 1px 2px rgba(0,0,0,0.03);">
          <div style="font-size:12px;color:#64748B;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;">{company}{linkedin_badge}</div>
          <div style="font-size:15px;font-weight:700;color:#0F172A;margin-top:2px;">
            <a href="{url}" style="color:#0F172A;text-decoration:none;">{title}</a>
          </div>
          <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;">
            {' '.join(badges)}
          </div>
          {ats_block}
          <div style="margin-top:10px;text-align:right;">
            <a href="{url}" target="_blank" style="display:inline-block;background:{accent_color};color:#FFFFFF;padding:5px 12px;font-size:12px;font-weight:600;text-decoration:none;border-radius:4px;">Apply on JustJoin →</a>
          </div>
        </div>
        """

    # 1. AI & ML Track
    html_parts.append(
        '<div style="margin-bottom:28px;">'
        '<div style="display:flex;align-items:center;margin-bottom:14px;border-bottom:2px solid #FCE7F3;padding-bottom:6px;">'
        '<h2 style="margin:0;font-size:17px;color:#7B1FA2;font-weight:700;">🧠 AI & Machine Learning Openings</h2>'
        f'<span style="margin-left:auto;background:#F3E8FF;color:#7B1FA2;font-weight:700;font-size:12px;padding:2px 8px;border-radius:12px;">{len(ai_jobs)}</span>'
        '</div>'
    )
    if ai_jobs:
        for job in ai_jobs:
            html_parts.append(_render_jj_card(job, accent_color="#7B1FA2"))
    else:
        html_parts.append('<p style="font-size:13px;color:#94A3B8;font-style:italic;margin:10px 0 20px 4px;">No new AI/ML job offers published in the last 24h.</p>')
    html_parts.append('</div>')

    # 2. Mobile Track
    html_parts.append(
        '<div style="margin-bottom:20px;">'
        '<div style="display:flex;align-items:center;margin-bottom:14px;border-bottom:2px solid #FFE4E6;padding-bottom:6px;">'
        '<h2 style="margin:0;font-size:17px;color:#E11D48;font-weight:700;">📱 Mobile Development Openings</h2>'
        f'<span style="margin-left:auto;background:#FFE4E6;color:#BE123C;font-weight:700;font-size:12px;padding:2px 8px;border-radius:12px;">{len(mobile_jobs)}</span>'
        '</div>'
    )
    if mobile_jobs:
        for job in mobile_jobs:
            html_parts.append(_render_jj_card(job, accent_color="#E11D48"))
    else:
        html_parts.append('<p style="font-size:13px;color:#94A3B8;font-style:italic;margin:10px 0 20px 4px;">No new Mobile job offers published in the last 24h.</p>')
    html_parts.append('</div>')

    # Footer
    html_parts.extend([
        '</div>',
        '<div style="background:#F1F5F9;padding:16px 20px;border-top:1px solid #E2E8F0;font-size:12px;color:#64748B;line-height:1.5;">',
        f'<div style="font-weight:600;color:#475569;margin-bottom:4px;">'
        f'⚡ JustJoin Scanner · Total {total_jobs} new job(s) from last 24h</div>',
        '<div>Directly sourced from JustJoin.it AI & Mobile feeds.</div>',
        '<div style="margin-top:6px;font-size:11px;color:#94A3B8;">'
        'Automated Job Radar · Powered by GitHub Actions</div>',
        '</div>',
        '</div>',
        '</body></html>',
    ])

    return "\n".join(html_parts)


_build_radar_html = build_radar_html


def build_worker_run_alert_html(
    run_id: str,
    status: str,
    inputs: Optional[Dict[str, Any]] = None,
    stats: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    run_url: Optional[str] = None,
    dataset_url: Optional[str] = None,
) -> str:
    """Build an HTML email alert for a worker / Apify Actor execution."""
    inputs = inputs or {}
    stats = stats or {}
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    normalized_status = status.lower()
    if normalized_status in ("completed", "success", "succeeded"):
        badge_bg = "#DCFCE7"
        badge_color = "#15803D"
        badge_border = "#86EFAC"
        status_label = "✅ COMPLETED"
        header_gradient = "linear-gradient(135deg, #064E3B 0%, #065F46 50%, #047857 100%)"
    elif normalized_status in ("timed_out", "timeout"):
        badge_bg = "#FEF3C7"
        badge_color = "#92400E"
        badge_border = "#FCD34D"
        status_label = "⏱️ TIMED OUT"
        header_gradient = "linear-gradient(135deg, #78350F 0%, #92400E 50%, #B45309 100%)"
    elif normalized_status in ("started", "running"):
        badge_bg = "#DBEAFE"
        badge_color = "#1E40AF"
        badge_border = "#93C5FD"
        status_label = "🚀 STARTED"
        header_gradient = "linear-gradient(135deg, #1E1B4B 0%, #1E40AF 50%, #2563EB 100%)"
    else:
        badge_bg = "#FEE2E2"
        badge_color = "#991B1B"
        badge_border = "#FCA5A5"
        status_label = "❌ FAILED"
        header_gradient = "linear-gradient(135deg, #7F1D1D 0%, #991B1B 50%, #B91C1C 100%)"

    total_fetched = stats.get("totalFetched", stats.get("scannedCount", "-"))
    total_emitted = stats.get("totalEmitted", stats.get("emittedCount", "-"))
    visa_enriched = stats.get("visaEnrichedJobs", stats.get("visaPassedJobs", "-"))
    duration = stats.get("durationSeconds", "-")
    if duration != "-" and isinstance(duration, (int, float)):
        duration_display = f"{duration:.1f}s"
    else:
        duration_display = str(duration)

    def _fmt_list(val: Any) -> str:
        if not val:
            return "<i>(Default / None)</i>"
        if isinstance(val, list):
            return html_lib.escape(", ".join(str(x) for x in val))
        return html_lib.escape(str(val))

    job_titles_str = _fmt_list(inputs.get("jobTitles") or inputs.get("job_titles"))
    keywords_str = _fmt_list(inputs.get("keywords") or inputs.get("searchKeywords"))
    countries_str = _fmt_list(inputs.get("countries") or inputs.get("destinationCountries"))
    overseas_enabled = inputs.get("enableOverseasSources", False)
    ai_enabled = inputs.get("enableAiClassification", False)
    max_results = inputs.get("maxResults", inputs.get("max_results", "200"))

    error_section = ""
    if error_message:
        escaped_err = html_lib.escape(str(error_message))
        error_section = f"""
        <div style="margin-top:20px;padding:14px;background:#FEF2F2;border:1px solid #F87171;border-radius:8px;">
          <div style="font-size:13px;font-weight:700;color:#991B1B;margin-bottom:6px;">⚠️ Failure Reason / Trace:</div>
          <pre style="font-family:ui-monospace,monospace;font-size:12px;color:#7F1D1D;margin:0;white-space:pre-wrap;word-break:break-word;">{escaped_err}</pre>
        </div>
        """

    buttons = []
    if run_url:
        buttons.append(
            f'<a href="{html_lib.escape(run_url)}" target="_blank" style="display:inline-block;background:#2563EB;color:#FFFFFF;padding:10px 18px;font-size:13px;font-weight:700;text-decoration:none;border-radius:6px;margin-right:10px;">View Run on Apify ↗</a>'
        )
    if dataset_url:
        buttons.append(
            f'<a href="{html_lib.escape(dataset_url)}" target="_blank" style="display:inline-block;background:#475569;color:#FFFFFF;padding:10px 18px;font-size:13px;font-weight:700;text-decoration:none;border-radius:6px;">View Dataset ↗</a>'
        )
    button_section = ""
    if buttons:
        button_section = f"""
        <div style="margin-top:24px;text-align:center;">
          {''.join(buttons)}
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:24px 0;background-color:#F8FAFC;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1E293B;">
  <div style="max-width:620px;margin:0 auto;background:#FFFFFF;border-radius:12px;overflow:hidden;border:1px solid #E2E8F0;box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);">
    
    <!-- Header -->
    <div style="background:{header_gradient};padding:24px 28px;color:#FFFFFF;">
      <div style="display:inline-block;padding:4px 10px;background:{badge_bg};color:{badge_color};border:1px solid {badge_border};border-radius:20px;font-size:11px;font-weight:800;letter-spacing:0.5px;text-transform:uppercase;margin-bottom:10px;">
        {status_label}
      </div>
      <h1 style="margin:0;font-size:22px;font-weight:800;letter-spacing:-0.5px;">⚡ Worker Run Notification</h1>
      <p style="margin:6px 0 0 0;font-size:13px;color:rgba(255,255,255,0.85);">
        Run ID: <code style="background:rgba(255,255,255,0.2);padding:2px 6px;border-radius:4px;font-family:monospace;font-size:12px;">{html_lib.escape(run_id)}</code> · {now_str}
      </p>
    </div>

    <!-- Main Content -->
    <div style="padding:24px 28px;">
      
      <!-- Metrics Grid -->
      <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
        <tr>
          <td style="width:25%;padding:10px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px 0 0 8px;text-align:center;">
            <div style="font-size:20px;font-weight:800;color:#0F172A;">{total_fetched}</div>
            <div style="font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;margin-top:2px;">Scanned</div>
          </td>
          <td style="width:25%;padding:10px;background:#F8FAFC;border:1px solid #E2E8F0;text-align:center;">
            <div style="font-size:20px;font-weight:800;color:#2563EB;">{total_emitted}</div>
            <div style="font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;margin-top:2px;">Matched</div>
          </td>
          <td style="width:25%;padding:10px;background:#F8FAFC;border:1px solid #E2E8F0;text-align:center;">
            <div style="font-size:20px;font-weight:800;color:#059669;">{visa_enriched}</div>
            <div style="font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;margin-top:2px;">Visa-Tagged</div>
          </td>
          <td style="width:25%;padding:10px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:0 8px 8px 0;text-align:center;">
            <div style="font-size:20px;font-weight:800;color:#7C3AED;">{duration_display}</div>
            <div style="font-size:11px;font-weight:600;color:#64748B;text-transform:uppercase;margin-top:2px;">Duration</div>
          </td>
        </tr>
      </table>

      <!-- Input Parameters -->
      <div style="margin-bottom:20px;">
        <h2 style="font-size:14px;color:#334155;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 10px 0;border-bottom:1px solid #E2E8F0;padding-bottom:6px;">
          ⚙️ Run Configuration & Inputs
        </h2>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <tr>
            <td style="padding:6px 0;color:#64748B;font-weight:600;width:35%;">Job Titles</td>
            <td style="padding:6px 0;color:#0F172A;">{job_titles_str}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#64748B;font-weight:600;">Keywords</td>
            <td style="padding:6px 0;color:#0F172A;">{keywords_str}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#64748B;font-weight:600;">Target Countries</td>
            <td style="padding:6px 0;color:#0F172A;">{countries_str}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#64748B;font-weight:600;">Overseas Sources</td>
            <td style="padding:6px 0;color:#0F172A;">{'🟢 Enabled' if overseas_enabled else '⚪ Disabled'}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#64748B;font-weight:600;">AI Classification</td>
            <td style="padding:6px 0;color:#0F172A;">{'🟢 Enabled' if ai_enabled else '⚪ Disabled'}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#64748B;font-weight:600;">Max Results</td>
            <td style="padding:6px 0;color:#0F172A;">{max_results}</td>
          </tr>
        </table>
      </div>

      {error_section}
      {button_section}

    </div>

    <!-- Footer -->
    <div style="background:#F1F5F9;padding:14px 28px;border-top:1px solid #E2E8F0;font-size:12px;color:#64748B;text-align:center;">
      Automated notification sent via {html_lib.escape(inputs.get("email_provider", "Resend"))} · Visa Sponsorship Daily Jobs
    </div>

  </div>
</body>
</html>
"""
    return html


