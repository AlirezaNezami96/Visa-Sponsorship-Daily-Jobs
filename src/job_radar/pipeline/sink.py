"""Sink protocol and implementations for consuming pipeline results."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from job_radar.models.job import Job

logger = logging.getLogger(__name__)


class JobSink(ABC):
    """Abstract interface for consuming pipeline results.
    Personal workflow and Apify Actor implement this differently.
    """

    @abstractmethod
    async def emit(self, jobs: List[Job]) -> None:
        """Write final jobs to the output destination."""
        pass

    @abstractmethod
    async def emit_stats(self, stats: Dict[str, Any]) -> None:
        """Write run statistics."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Cleanup resources."""
        pass


class InMemoryJobSink(JobSink):
    """In-memory sink used for testing, CLI inspection, or synchronous consumption."""

    def __init__(self) -> None:
        self.jobs: List[Job] = []
        self.stats: Dict[str, Any] = {}
        self.closed: bool = False

    async def emit(self, jobs: List[Job]) -> None:
        self.jobs.extend(jobs)

    async def emit_stats(self, stats: Dict[str, Any]) -> None:
        self.stats.update(stats)

    async def close(self) -> None:
        self.closed = True


class PersonalSink(JobSink):
    """Personal workflow sink: handles legacy dictionaries, email digests, and state persistence."""

    def __init__(
        self,
        dry_run: bool = False,
        seen_file: str = "seen_jobs.json",
        send_email: bool = True,
        send_empty_digests: bool = False,
    ) -> None:
        self.dry_run = dry_run
        self.seen_file = seen_file
        self.send_email = send_email
        self.send_empty_digests = send_empty_digests
        self.emitted_jobs: List[Job] = []
        self.stats: Dict[str, Any] = {}

    async def emit(self, jobs: List[Job]) -> None:
        self.emitted_jobs.extend(jobs)

    async def emit_stats(self, stats: Dict[str, Any]) -> None:
        self.stats.update(stats)

    async def close(self) -> None:
        logger.info("Personal sink closed. Total emitted jobs: %d", len(self.emitted_jobs))
