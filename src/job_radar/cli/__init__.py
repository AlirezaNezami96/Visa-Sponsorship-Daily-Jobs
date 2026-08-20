"""CLI entrypoints subpackage for job_radar."""
from job_radar.cli.funding_cmd import run as run_funding
from job_radar.cli.junior_ai_cmd import run as run_junior_ai
from job_radar.cli.radar_cmd import run as run_radar
from job_radar.cli.remote_cmd import run as run_remote

__all__ = [
    "run_radar",
    "run_remote",
    "run_junior_ai",
    "run_funding",
]
