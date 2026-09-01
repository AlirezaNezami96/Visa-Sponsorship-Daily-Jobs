"""Registry of available job source adapters."""
from __future__ import annotations

import logging
from typing import Dict, List, Type

from job_radar.models.config import JobSearchConfig
from job_radar.sources.arbeitnow import ArbeitnowAdapter
from job_radar.sources.ashby import AshbyAdapter
from job_radar.sources.base import SourceAdapter
from job_radar.sources.bamboohr import BambooHRAdapter
from job_radar.sources.greenhouse import GreenhouseAdapter
from job_radar.sources.himalayas import HimalayasAdapter
from job_radar.sources.hn_whoshiring import HNWhoHiringAdapter
from job_radar.sources.jobicy import JobicyAdapter
from job_radar.sources.lever import LeverAdapter
from job_radar.sources.personio import PersonioAdapter
from job_radar.sources.recruitee import RecruiteeAdapter
from job_radar.sources.remoteok import RemoteOKAdapter
from job_radar.sources.remotive import RemotiveAdapter
from job_radar.sources.smartrecruiters import SmartRecruitersAdapter
from job_radar.sources.taleo import TaleoAdapter
from job_radar.sources.workable import WorkableAdapter
from job_radar.sources.workday import WorkdayAdapter
from job_radar.sources.bayt import BaytAdapter
from job_radar.sources.bumeran import BumeranAdapter
from job_radar.sources.computrabajo import ComputrabajoAdapter
from job_radar.sources.energyjobline import EnergyJoblineAdapter
from job_radar.sources.gulftalent import GulfTalentAdapter
from job_radar.sources.healthcare_placement import HealthcarePlacementAdapter
from job_radar.sources.jaabz import JaabzAdapter
from job_radar.sources.jobstreet import JobStreetAdapter
from job_radar.sources.rigzone import RigzoneAdapter
from job_radar.sources.weworkremotely import WeWorkRemotelyAdapter

logger = logging.getLogger(__name__)

SOURCE_REGISTRY: Dict[str, Type[SourceAdapter]] = {
    # Direct ATS Platforms (10)
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "workable": WorkableAdapter,
    "smartrecruiters": SmartRecruitersAdapter,
    "personio": PersonioAdapter,
    "workday": WorkdayAdapter,
    "bamboohr": BambooHRAdapter,
    "taleo": TaleoAdapter,
    "recruitee": RecruiteeAdapter,
    # Remote & Tech Aggregators (7)
    "weworkremotely": WeWorkRemotelyAdapter,
    "remoteok": RemoteOKAdapter,
    "remotive": RemotiveAdapter,
    "arbeitnow": ArbeitnowAdapter,
    "himalayas": HimalayasAdapter,
    "hn_whoshiring": HNWhoHiringAdapter,
    "jobicy": JobicyAdapter,
    # Regional Generalist Boards (5)
    "computrabajo": ComputrabajoAdapter,
    "bumeran": BumeranAdapter,
    "jobstreet": JobStreetAdapter,
    "bayt": BaytAdapter,
    "gulftalent": GulfTalentAdapter,
    # Industry & Vertical Sources (3)
    "rigzone": RigzoneAdapter,
    "energyjobline": EnergyJoblineAdapter,
    "healthcare_placement": HealthcarePlacementAdapter,
    # Dedicated Visa Sources (1)
    "jaabz": JaabzAdapter,
}


def list_available_adapters() -> Dict[str, Type[SourceAdapter]]:
    """Return dictionary of all available source adapter classes."""
    return dict(SOURCE_REGISTRY)


def get_enabled_sources(config: JobSearchConfig) -> List[SourceAdapter]:
    """Return instantiated adapters for requested sources."""
    if not config.sources:
        # Return all registered adapters by default
        adapters = [cls() for cls in SOURCE_REGISTRY.values()]
    else:
        adapters = []
        for s_name in config.sources:
            normalized = s_name.lower().strip()
            if normalized in SOURCE_REGISTRY:
                adapters.append(SOURCE_REGISTRY[normalized]())
            else:
                logger.warning("Requested source '%s' is not recognized; skipping.", s_name)

    # Overseas expansion pack is flag-gated, not selectable via `sources`.
    if getattr(config, "enable_overseas_sources", False):
        from job_radar.sources.overseas.adapter import OverseasAdapter
        adapters.append(OverseasAdapter(config))

    return adapters
