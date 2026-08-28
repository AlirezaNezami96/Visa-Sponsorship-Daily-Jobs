"""Reusable, engine-independent run-report layer for the Visa Sponsorship Actor.

Produces a single structured ``RunReport`` from pipeline outputs and renders it
to JSON and standalone HTML. Kept separate from the scraping pipeline and from
the Apify SDK so it is fully unit-testable offline.
"""
from __future__ import annotations

from job_radar.reporting.model import (
    ACTOR_TITLE,
    DISCLAIMER,
    RunReport,
    TopJobView,
    build_run_report,
)
from job_radar.reporting.render_json import report_to_dict, report_to_json_string
from job_radar.reporting.render_html import render_report_html

__all__ = [
    "ACTOR_TITLE",
    "DISCLAIMER",
    "RunReport",
    "TopJobView",
    "build_run_report",
    "report_to_dict",
    "report_to_json_string",
    "render_report_html",
]
