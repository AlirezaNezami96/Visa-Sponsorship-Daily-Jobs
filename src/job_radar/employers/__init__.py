"""
src/job_radar/employers/__init__.py

First-Class Employer Intelligence & Identity Resolution Layer.
"""
from __future__ import annotations

from job_radar.employers.model import Employer, EmployerSponsorshipRecord
from job_radar.employers.resolver import EmployerResolver

__all__ = [
    "Employer",
    "EmployerSponsorshipRecord",
    "EmployerResolver",
]
