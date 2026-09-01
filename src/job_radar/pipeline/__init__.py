"""Pipeline package for job_radar."""
from __future__ import annotations

from job_radar.pipeline.orchestrator import PipelineResult, run_pipeline
from job_radar.pipeline.sink import InMemoryJobSink, JobSink, PersonalSink, SupabaseJobSink

__all__ = [
    "run_pipeline",
    "PipelineResult",
    "JobSink",
    "InMemoryJobSink",
    "PersonalSink",
    "SupabaseJobSink",
]
