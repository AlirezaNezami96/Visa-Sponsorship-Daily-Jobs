"""Exponential backoff and retry helper for social publishing operations.
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from job_radar.social.adapters import PublishResult

logger = logging.getLogger(__name__)


def execute_with_retry(
    fn: Callable[[], PublishResult],
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
) -> PublishResult:
    """Execute a publishing operation with retry on retryable errors.

    Permanent errors (401/403/404/etc.) skip retry immediately.
    """
    last_result = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = fn()
            last_result = result
            if result.ok:
                return result

            if result.permanent or not result.retryable or attempt >= max_attempts:
                return result

            # Calculate backoff delay
            if result.retry_after and result.retry_after > 0:
                delay = min(result.retry_after, max_delay)
            else:
                delay = min(initial_delay * (2 ** (attempt - 1)) + random.uniform(0.1, 0.5), max_delay)

            logger.info("Publish failed (attempt %d/%d): %s. Retrying in %.2fs", attempt, max_attempts, result.error, delay)
            time.sleep(delay)
        except Exception as e:
            logger.warning("Unexpected exception during publish execution (attempt %d): %s", attempt, e)
            from job_radar.social.adapters import PublishResult
            return PublishResult(ok=False, error=str(e), permanent=True)

    from job_radar.social.adapters import PublishResult
    return last_result or PublishResult(ok=False, error="Max retry attempts exhausted", retryable=False, permanent=True)
