"""JSON renderer for the run report (REPORT.json).

Produces a clean, stable, machine-readable structure useful for API consumers,
automation, and downstream AI agents. Only data already present in the report
model is emitted — nothing is recomputed.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict

from job_radar.reporting.model import RunReport


def report_to_dict(report: RunReport) -> Dict[str, Any]:
    """Convert the RunReport dataclass to a plain JSON-serializable dict."""
    data = dataclasses.asdict(report)
    # Ensure the structure is stable and only contains supported primitives.
    return json.loads(json.dumps(data, default=str))


def report_to_json_string(report: RunReport, indent: int = 2) -> str:
    """Serialize the RunReport to a pretty-printed JSON string."""
    return json.dumps(report_to_dict(report), indent=indent, ensure_ascii=False, default=str)
