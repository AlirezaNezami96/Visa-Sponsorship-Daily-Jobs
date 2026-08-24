"""Standalone HTML renderer for the run report (REPORT.html).

Produces a single self-contained HTML document (inline CSS, no external
resources, no backend) that opens cleanly in any browser and can be embedded in
an Apify Console iframe or downloaded. All dynamic values are HTML-escaped.
"""
from __future__ import annotations

import html
from typing import Any, Dict, List

from job_radar.reporting.model import RunReport, TopJobView

_STATUS_META = {
    "completed": ("Run completed successfully", "ok"),
    "completed_empty": ("Run completed — no matching jobs", "warn"),
    "timeout": ("Run ended at the time limit", "warn"),
    "failed": ("Run finished with an error", "err"),
}

_TONE_CLASS = {"strong": "tone-strong", "possible": "tone-possible", "neutral": "tone-neutral", "negative": "tone-negative"}


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _fmt_num(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def _stat_card(label: str, value: Any, sub: str = "") -> str:
    sub_html = f'<div class="stat-sub">{_esc(sub)}</div>' if sub else ""
    return (
        f'<div class="stat-card"><div class="stat-value">{_fmt_num(value)}</div>'
        f'<div class="stat-label">{_esc(label)}</div>{sub_html}</div>'
    )


def _chip(text: str) -> str:
    return f'<span class="chip">{_esc(text)}</span>'


def _criteria_section(report: RunReport) -> str:
    sc = report.searchCriteria or {}
    chips: List[str] = []
    if sc.get("keywords"):
        chips.append(_chip("Keywords: " + ", ".join(sc["keywords"])))
    if sc.get("countries"):
        chips.append(_chip("Countries: " + ", ".join(sc["countries"])))
    if sc.get("cities"):
        chips.append(_chip("Cities: " + ", ".join(sc["cities"])))
    if sc.get("remoteOnly"):
        chips.append(_chip("Remote only"))
    if sc.get("seniorityLevels"):
        chips.append(_chip("Seniority: " + ", ".join(sc["seniorityLevels"])))
    if sc.get("technologies"):
        chips.append(_chip("Tech: " + ", ".join(sc["technologies"])))
    if sc.get("visaSponsorshipOnly"):
        chips.append(_chip("Visa sponsorship only"))
    if sc.get("minVisaConfidence") not in (None, "", "unknown"):
        chips.append(_chip("Min visa confidence: " + str(sc["minVisaConfidence"])))
    chips.append(_chip("Posted within " + str(sc.get("postedWithinDays", 30)) + " days"))
    if sc.get("enableOverseasSources"):
        chips.append(_chip("Overseas sources enabled"))
    if not chips:
        return ""
    return (
        '<section class="section"><h2>Search Criteria</h2>'
        f'<div class="chips">{"".join(chips)}</div></section>'
    )


def _summary_section(report: RunReport) -> str:
    s = report.summary or {}
    cards = [
        _stat_card("Jobs scanned", s.get("jobsFetched", 0)),
        _stat_card("After filtering", s.get("jobsAfterFiltering", 0)),
        _stat_card("Matched jobs", s.get("jobsEmitted", 0)),
        _stat_card("Visa-relevant", s.get("visaRelevant", 0), "positive signal"),
        _stat_card("High-confidence", s.get("strongVisaEvidence", 0), "strong evidence"),
        _stat_card("Remote jobs", s.get("remoteJobs", 0)),
        _stat_card("Countries", s.get("countries", 0)),
        _stat_card("Companies", s.get("companies", 0)),
    ]
    return (
        '<section class="section"><h2>Key Statistics</h2>'
        f'<div class="stat-grid">{"".join(cards)}</div>'
        f'<p class="muted">Duplicates removed: {_fmt_num(s.get("duplicatesRemoved", 0))} '
        f'&middot; Sources OK: {_fmt_num(s.get("successfulSourceCount", 0))} '
        f'&middot; Sources failed: {_fmt_num(s.get("failedSourceCount", 0))} '
        f'&middot; Duration: {_esc(round(float(s.get("durationSeconds", 0) or 0), 1))}s</p>'
        '</section>'
    )


def _visa_badge(job: TopJobView) -> str:
    cls = _TONE_CLASS.get(job.visaTone, "tone-neutral")
    return f'<span class="badge {cls}">{_esc(job.visaEmoji)} {_esc(job.visaLabel)}</span>'


def _top_job_card(job: TopJobView) -> str:
    loc_bits = []
    if job.location:
        loc_bits.append(job.location)
    elif job.country and job.country not in ("Remote", "Other"):
        loc_bits.append(job.country)
    loc = ", ".join(loc_bits)
    flag = f'{job.countryFlag} ' if job.countryFlag else ""

    meta_lines = []
    if job.seniority or job.employmentType:
        bits = [b for b in (job.seniority, job.employmentType) if b]
        meta_lines.append("💼 " + " · ".join(_esc(b).capitalize() for b in bits))
    if job.workplace:
        meta_lines.append("🏠 " + _esc(job.workplace))
    if job.salary:
        meta_lines.append("💰 " + _esc(job.salary))
    if job.technologies:
        meta_lines.append("🛠 " + _esc(", ".join(job.technologies)))
    if job.postedAgo:
        meta_lines.append("📅 Posted " + _esc(job.postedAgo))

    meta_html = "".join(f'<div class="job-meta">{m}</div>' for m in meta_lines)

    reasons_html = ""
    if job.reasons:
        items = "".join(f"<li>{_esc(r)}</li>" for r in job.reasons)
        reasons_html = f'<div class="why"><div class="why-title">Why recommended</div><ul>{items}</ul></div>'

    evidence_html = ""
    if job.visaEvidence:
        evidence_html = f'<div class="job-evidence">Evidence: {_esc(job.visaEvidence)}</div>'

    apply_btn = ""
    if job.applyUrl:
        apply_btn = (
            f'<a class="btn" href="{_esc(job.applyUrl)}" target="_blank" rel="noopener noreferrer">Apply →</a>'
        )

    return f'''
<div class="job-card">
  <div class="job-head">
    <div class="job-rank">#{job.rank}</div>
    <div class="job-titlewrap">
      <div class="job-title">{_esc(job.title)}</div>
      <div class="job-company">{_esc(job.company)}</div>
      <div class="job-location">{flag}{_esc(loc)}</div>
    </div>
    <div class="job-score-wrap">
      <div class="job-score">{job.opportunityScore}</div>
      <div class="job-score-label">score</div>
    </div>
  </div>
  <div class="job-badges">{_visa_badge(job)}</div>
  {evidence_html}
  {meta_html}
  {reasons_html}
  <div class="job-actions">{apply_btn}</div>
</div>'''


def _top_matches_section(report: RunReport) -> str:
    if not report.topJobs:
        return ""
    cards = "".join(_top_job_card(j) for j in report.topJobs)
    return (
        f'<section class="section"><h2>Top {len(report.topJobs)} Opportunities</h2>'
        f'<div class="jobs">{cards}</div></section>'
    )


def _country_section(report: RunReport) -> str:
    rows = report.countryStats or []
    if not rows:
        return ""
    body = []
    for r in rows:
        flag = r.get("flag") or ""
        body.append(
            "<tr>"
            f'<td>{"🏳️ " if not flag else flag} {_esc(r["country"])}</td>'
            f'<td>{_fmt_num(r["jobs"])}</td>'
            f'<td>{_fmt_num(r["visaPositive"])}</td>'
            f'<td>{_fmt_num(r["highConfidence"])}</td>'
            "</tr>"
        )
    return (
        '<section class="section"><h2>Jobs by Country</h2><div class="table-wrap"><table>'
        '<thead><tr><th>Country</th><th>Jobs</th><th>Visa-positive</th><th>High-confidence</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div></section>'
    )


def _company_section(report: RunReport) -> str:
    rows = report.companyStats or []
    if not rows:
        return ""
    body = []
    for r in rows:
        countries = ", ".join(r.get("countries", [])[:4]) or "—"
        body.append(
            "<tr>"
            f'<td>{_esc(r["company"])}</td>'
            f'<td>{_fmt_num(r["jobs"])}</td>'
            f'<td>{_fmt_num(r["visaPositive"])}</td>'
            f'<td>{_esc(countries)}</td>'
            f'<td>{r.get("highestScore", 0)}</td>'
            "</tr>"
        )
    return (
        '<section class="section"><h2>Top Employers</h2><div class="table-wrap"><table>'
        '<thead><tr><th>Company</th><th>Jobs</th><th>Visa-positive</th><th>Countries</th><th>Best score</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div></section>'
    )


def _visa_section(report: RunReport) -> str:
    rows = report.visaStats or []
    if not rows:
        return ""
    body = []
    for r in rows:
        cls = _TONE_CLASS.get(r.get("tone"), "tone-neutral")
        body.append(
            "<tr>"
            f'<td><span class="badge {cls}">{_esc(r.get("emoji"))} {_esc(r.get("label"))}</span></td>'
            f'<td>{_fmt_num(r.get("count"))}</td>'
            "</tr>"
        )
    return (
        '<section class="section"><h2>Visa Evidence Breakdown</h2><div class="table-wrap"><table>'
        '<thead><tr><th>Signal</th><th>Jobs</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div></section>'
    )


def _source_section(report: RunReport) -> str:
    rows = report.sourceStats or []
    if not rows:
        return ""
    body = []
    for r in rows:
        status = r.get("status", "unknown")
        icon = "✅" if status == "ok" else ("⚠️" if status == "failed" else "•")
        body.append(
            "<tr>"
            f'<td>{_esc(r["source"])}</td>'
            f'<td>{_esc(r.get("trust"))}</td>'
            f'<td>{_fmt_num(r["jobs"])}</td>'
            f'<td>{icon} {_esc(status)}</td>'
            "</tr>"
        )
    return (
        '<section class="section"><h2>Sources</h2><div class="table-wrap"><table>'
        '<thead><tr><th>Source</th><th>Type / Trust</th><th>Final jobs</th><th>Status</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div></section>'
    )


def _empty_section(report: RunReport) -> str:
    sc = report.searchCriteria or {}
    s = report.summary or {}
    searched_bits = []
    if sc.get("keywords"):
        searched_bits.append("Keywords: " + ", ".join(sc["keywords"]))
    if sc.get("countries"):
        searched_bits.append("Countries: " + ", ".join(sc["countries"]))
    if sc.get("visaSponsorshipOnly"):
        searched_bits.append("Visa sponsorship only")
    searched = "".join(f"<li>{_esc(b)}</li>" for b in searched_bits) or "<li>No restrictive filters</li>"
    suggestions = "".join(f"<li>{_esc(x)}</li>" for x in report.suggestions)
    return f'''
<section class="section empty-state">
  <div class="empty-icon">🔎</div>
  <h2>No matching jobs were found.</h2>
  <p class="muted">We scanned <strong>{_fmt_num(s.get("jobsFetched", 0))}</strong> jobs across
  <strong>{_fmt_num(s.get("successfulSourceCount", 0))}</strong> sources, but none matched the current filters.</p>
  <div class="empty-cols">
    <div><h3>You searched</h3><ul>{searched}</ul></div>
    <div><h3>Try broadening</h3><ul>{suggestions}</ul></div>
  </div>
</section>'''


def _warnings_section(report: RunReport) -> str:
    if not report.warnings:
        return ""
    items = "".join(f"<li>{_esc(w)}</li>" for w in report.warnings)
    return f'<section class="section"><div class="warn-box"><strong>Notes</strong><ul>{items}</ul></div></section>'


_CSS = """
:root{
  --bg:#f6f8fb; --card:#ffffff; --ink:#14213d; --muted:#5b657a;
  --line:#e6eaf2; --accent:#2563eb; --accent-ink:#ffffff;
  --strong:#e8f7ee; --strong-ink:#127a3d; --strong-line:#bfe8cf;
  --possible:#fff7e0; --possible-ink:#9a6b00; --possible-line:#f2dfae;
  --neutral:#eef1f6; --neutral-ink:#4a5468; --neutral-line:#dbe1ec;
  --negative:#fdecec; --negative-ink:#b42318; --negative-line:#f5c2bd;
  --ok:#127a3d; --warn:#9a6b00; --err:#b42318;
  --radius:12px;
}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  line-height:1.5;-webkit-font-smoothing:antialiased;}
.wrap{max-width:960px;margin:0 auto;padding:24px 16px 64px;}
header.hero{background:linear-gradient(135deg,#14213d,#1f3a63);color:#fff;border-radius:var(--radius);
  padding:28px 24px;margin-bottom:24px;}
header.hero h1{margin:0 0 6px;font-size:22px;letter-spacing:.2px;}
header.hero .sub{opacity:.85;font-size:13px;}
.status-badge{display:inline-block;margin-top:12px;padding:5px 12px;border-radius:999px;font-size:12px;
  font-weight:600;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.25);}
.status-ok{background:#1d7a46;} .status-warn{background:#a4670a;} .status-err{background:#a52a1d;}
.section{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
  padding:20px 22px;margin-bottom:20px;}
.section h2{margin:0 0 16px;font-size:16px;}
.section h3{margin:0 0 8px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;}
.muted{color:var(--muted);font-size:13px;margin:10px 0 0;}
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
.stat-card{border:1px solid var(--line);border-radius:10px;padding:14px 12px;text-align:center;background:#fbfcfe;}
.stat-value{font-size:24px;font-weight:700;}
.stat-label{font-size:12px;color:var(--muted);margin-top:2px;}
.stat-sub{font-size:11px;color:var(--muted);opacity:.8;}
.chips{display:flex;flex-wrap:wrap;gap:8px;}
.chip{background:#eef3ff;color:#1f3a63;border:1px solid #d5e0fb;border-radius:999px;
  padding:4px 12px;font-size:12px;}
.jobs{display:grid;grid-template-columns:1fr;gap:14px;}
.job-card{border:1px solid var(--line);border-radius:12px;padding:16px;background:#fff;}
.job-head{display:flex;gap:14px;align-items:flex-start;}
.job-rank{font-weight:700;color:var(--muted);font-size:14px;min-width:34px;}
.job-titlewrap{flex:1;}
.job-title{font-weight:700;font-size:16px;}
.job-company{color:var(--accent);font-weight:600;font-size:14px;margin-top:2px;}
.job-location{color:var(--muted);font-size:13px;margin-top:2px;}
.job-score-wrap{text-align:center;min-width:56px;}
.job-score{font-size:26px;font-weight:800;color:var(--accent);}
.job-score-label{font-size:11px;color:var(--muted);}
.job-badges{margin-top:10px;display:flex;flex-wrap:wrap;gap:6px;}
.badge{display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;border:1px solid;}
.tone-strong{background:var(--strong);color:var(--strong-ink);border-color:var(--strong-line);}
.tone-possible{background:var(--possible);color:var(--possible-ink);border-color:var(--possible-line);}
.tone-neutral{background:var(--neutral);color:var(--neutral-ink);border-color:var(--neutral-line);}
.tone-negative{background:var(--negative);color:var(--negative-ink);border-color:var(--negative-line);}
.job-evidence{margin-top:8px;font-size:12px;color:var(--muted);font-style:italic;}
.job-meta{margin-top:6px;font-size:13px;color:var(--ink);}
.why{margin-top:10px;border-top:1px dashed var(--line);padding-top:8px;}
.why-title{font-size:12px;font-weight:700;color:var(--muted);margin-bottom:4px;}
.why ul{margin:0;padding-left:18px;}
.why li{font-size:13px;color:var(--ink);}
.job-actions{margin-top:12px;}
.btn{display:inline-block;background:var(--accent);color:var(--accent-ink);text-decoration:none;
  border-radius:8px;padding:8px 16px;font-size:13px;font-weight:600;}
.btn:hover{filter:brightness(1.08);}
.table-wrap{overflow-x:auto;}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:480px;}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);}
th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.3px;}
tbody tr:last-child td{border-bottom:none;}
.warn-box{background:var(--possible);border:1px solid var(--possible-line);color:var(--possible-ink);
  border-radius:10px;padding:12px 14px;font-size:13px;}
.warn-box ul{margin:6px 0 0;padding-left:18px;}
.empty-state{text-align:center;}
.empty-icon{font-size:40px;}
.empty-state h2{margin:8px 0 4px;}
.empty-cols{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:18px;text-align:left;}
.empty-cols ul{margin:0;padding-left:18px;}
.empty-cols li{font-size:13px;margin:3px 0;}
footer{color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:16px;}
@media (max-width:720px){
  .stat-grid{grid-template-columns:repeat(2,1fr);}
  .empty-cols{grid-template-columns:1fr;}
  .job-head{flex-wrap:wrap;}
}
"""


def render_report_html(report: RunReport) -> str:
    """Render the full standalone HTML document for a RunReport."""
    status_text, status_cls = _STATUS_META.get(report.status, ("Run finished", "warn"))
    generated = _esc(report.generatedAt[:19].replace("T", " "))
    sc = report.searchCriteria or {}
    criteria_line = ", ".join(sc.get("countries") or []) or ("Remote" if sc.get("remoteOnly") else "Global")
    keyword_line = ", ".join(sc.get("keywords") or []) or "All roles"

    if report.empty:
        body_sections = _empty_section(report) + _warnings_section(report)
    else:
        body_sections = (
            _summary_section(report)
            + _criteria_section(report)
            + _top_matches_section(report)
            + _country_section(report)
            + _company_section(report)
            + _visa_section(report)
            + _source_section(report)
            + _warnings_section(report)
            + _methodology_section(report)
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(report.actorTitle)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <h1>{_esc(report.actorTitle)}</h1>
    <div class="sub">{_esc(criteria_line)} &middot; {_esc(keyword_line)}</div>
    <div class="sub">Generated {generated} UTC</div>
    <span class="status-badge status-{status_cls}">{_esc(status_text)}</span>
  </header>
  {body_sections}
  <footer>
    {_esc(report.disclaimer)}
  </footer>
</div>
</body>
</html>"""


def _methodology_section(report: RunReport) -> str:
    s = report.summary or {}
    sc = report.searchCriteria or {}
    bits = [
        f"Sources searched: {_fmt_num(s.get('successfulSourceCount', 0))} ok, {_fmt_num(s.get('failedSourceCount', 0))} failed.",
        f"AI classification: {'enabled' if sc.get('enableAIClassification', False) else 'disabled'}.",
        f"Filters: keywords, countries, seniority, posted-within, and visa criteria as listed above.",
        "Limitations: signals are inferred from public data and may lag reality; always confirm with the employer.",
    ]
    items = "".join(f"<li>{_esc(b)}</li>" for b in bits)
    return f'<section class="section"><h2>Methodology</h2><ul>{items}</ul></section>'
