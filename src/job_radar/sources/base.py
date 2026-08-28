"""Source adapter base interface and abstractions."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from job_radar.models.config import JobSearchConfig
from job_radar.models.job import Job

logger = logging.getLogger(__name__)


class SourceAdapter(ABC):
    """Base interface for all job sources."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique source identifier: 'greenhouse', 'lever', etc."""
        pass

    @property
    @abstractmethod
    def source_type(self) -> str:
        """'ats' | 'job_board' | 'aggregator'"""
        pass

    @abstractmethod
    async def fetch(
        self,
        config: JobSearchConfig,
    ) -> List[Job]:
        """
        Fetch jobs from this source.
        Must return normalized Job objects.
        Must NOT raise exceptions for network errors - return empty list and log.
        Must respect config.max_per_source limit.
        """
        pass

    @abstractmethod
    def supports_company_urls(self) -> bool:
        """Whether this adapter can fetch from specific company URLs."""
        pass

    async def fetch_by_company(
        self,
        company_url: str,
        config: JobSearchConfig,
    ) -> List[Job]:
        """Optional: fetch from a specific company career page."""
        raise NotImplementedError(f"Adapter '{self.name}' does not implement fetch_by_company.")
