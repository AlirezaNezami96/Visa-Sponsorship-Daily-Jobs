"""Apify Key-Value Store writer for the run report layer.

This is the only place that couples the reusable reporting layer to the Apify
SDK. It builds a ``RunReport`` from the pipeline result and writes the
human-friendly outputs to the run's default Key-Value Store:

  * ``REPORT.json``  — machine-readable run summary / top matches / stats
  * ``REPORT.html``  — standalone, responsive HTML report (renders in an
                        iframe in the Apify Console Output tab via the
                        output schema)

Writing the report is strictly additive and defensive: a failure here never
fails the Actor run.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job
from job_radar.reporting.model import build_run_report
from job_radar.reporting.render_html import render_report_html
from job_radar.reporting.render_json import report_to_dict

logger = logging.getLogger(__name__)

REPORT_JSON_KEY = "REPORT.json"
REPORT_HTML_KEY = "REPORT.html"


async def write_apify_reports(
    config: JobSearchConfig,
    jobs: List[Job],
    stats: Optional[Dict[str, Any]],
    successful_sources: Optional[List[str]],
    failed_sources: Optional[List[Dict[str, str]]],
    status: str = "completed",
) -> Dict[str, str]:
    """Build the RunReport and write REPORT.json / REPORT.html to the KVS.

    Returns a mapping of output name -> KV record key (for logging). Never
    raises: any error is swallowed and logged so reporting cannot break a run.
    """
    written: Dict[str, str] = {}
    try:
        # Local import keeps the module importable without the Apify SDK present.
        from apify import Actor

        report = build_run_report(
            jobs=jobs,
            config=config,
            stats=stats or {},
            successful_sources=successful_sources or [],
            failed_sources=failed_sources or [],
            status=status,
        )

        # Machine-readable summary (REPORT.json)
        await Actor.set_value(REPORT_JSON_KEY, report_to_dict(report))
        written["reportJson"] = REPORT_JSON_KEY

        # Human-friendly standalone HTML report (REPORT.html)
        await Actor.set_value(
            REPORT_HTML_KEY,
            render_report_html(report),
            content_type="text/html; charset=utf-8",
        )
        written["reportHtml"] = REPORT_HTML_KEY

        _log_human_summary(report)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Report generation failed (non-fatal): %s", e)
    return written


def _log_human_summary(report: Any) -> None:
    """Emit a concise, friendly run summary to the Actor log."""
    try:
        from apify import Actor
    except Exception:  # pragma: no cover
        return

    s = report.summary or {}
    emitted = s.get("jobsEmitted", 0)
    if report.empty:
        Actor.log.info("=" * 50)
        Actor.log.info("VISA SPONSORSHIP JOBS — RUN COMPLETED")
        Actor.log.info("No matching jobs were found.")
        Actor.log.info(
            "Scanned %s jobs across %s sources. See REPORT.html for suggestions.",
            s.get("jobsFetched", 0), s.get("successfulSourceCount", 0),
        )
        Actor.log.info("=" * 50)
        return

    Actor.log.info("=" * 50)
    Actor.log.info("VISA SPONSORSHIP JOBS — RUN COMPLETED")
    Actor.log.info("✅ Run completed successfully")
    Actor.log.info("%s jobs scanned", s.get("jobsFetched", 0))
    Actor.log.info("%s jobs matched", emitted)
    Actor.log.info("%s jobs with visa-related evidence", s.get("visaRelevant", 0))
    Actor.log.info("%s high-confidence opportunities", s.get("strongVisaEvidence", 0))
    Actor.log.info("Outputs: REPORT.html (visual), REPORT.json (data), Dataset (all jobs)")
    Actor.log.info("=" * 50)
