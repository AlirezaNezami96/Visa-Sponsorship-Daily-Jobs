"""Registry of available job source adapters."""
from __future__ import annotations

import logging
from typing import Dict, List, Type

from job_radar.models.config import JobSearchConfig
from job_radar.sources.arbeitnow import ArbeitnowAdapter
from job_radar.sources.ashby import AshbyAdapter
from job_radar.sources.base import SourceAdapter
from job_radar.sources.greenhouse import GreenhouseAdapter
from job_radar.sources.himalayas import HimalayasAdapter
from job_radar.sources.hn_whoshiring import HNWhoHiringAdapter
from job_radar.sources.jobicy import JobicyAdapter
from job_radar.sources.lever import LeverAdapter
from job_radar.sources.personio import PersonioAdapter
from job_radar.sources.remoteok import RemoteOKAdapter
from job_radar.sources.remotive import RemotiveAdapter
from job_radar.sources.smartrecruiters import SmartRecruitersAdapter
from job_radar.sources.workable import WorkableAdapter

logger = logging.getLogger(__name__)

SOURCE_REGISTRY: Dict[str, Type[SourceAdapter]] = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "workable": WorkableAdapter,
    "smartrecruiters": SmartRecruitersAdapter,
    "personio": PersonioAdapter,
    "remoteok": RemoteOKAdapter,
    "remotive": RemotiveAdapter,
    "arbeitnow": ArbeitnowAdapter,
    "himalayas": HimalayasAdapter,
    "hn_whoshiring": HNWhoHiringAdapter,
    "jobicy": JobicyAdapter,
}


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
