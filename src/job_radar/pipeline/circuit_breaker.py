"""Circuit breaker pattern backed by the `service_circuits` table.

Protects external calls (source scrapers, AI providers, Wikimedia, email senders)
from cascading failures. States:
    closed  → normal operation, calls proceed
    open    → after N consecutive failures, all calls skipped for cooldown period
    half_open → after cooldown, one probe call allowed; success → closed, failure → open

The circuit state is persisted in Supabase so it survives across GitHub Actions runs
and is visible in the admin console.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_COOLDOWN_MINUTES = 30


class CircuitBreaker:
    """Circuit breaker backed by the `service_circuits` table."""

    def __init__(
        self,
        client: Any,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
    ):
        self._client = client
        self._failure_threshold = failure_threshold
        self._cooldown_minutes = cooldown_minutes

    def _ensure_row(self, name: str) -> dict[str, Any]:
        """Ensure a circuit row exists and return it."""
        resp = (
            self._client.table("service_circuits")
            .select("*")
            .eq("name", name)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            return resp.data

        # Insert new circuit
        self._client.table("service_circuits").insert({
            "name": name,
            "consecutive_failures": 0,
            "state": "closed",
        }).execute()

        return {
            "name": name,
            "consecutive_failures": 0,
            "state": "closed",
            "opened_at": None,
            "last_failure_at": None,
            "last_success_at": None,
        }

    def is_open(self, name: str) -> bool:
        """Check if the circuit is open (calls should be skipped).

        If the circuit is open and the cooldown has elapsed, transition
        to half_open (one probe call allowed).
        """
        row = self._ensure_row(name)
        state = row.get("state", "closed")

        if state == "closed":
            return False

        if state == "half_open":
            return False  # Allow the probe call

        if state == "open":
            opened_at = row.get("opened_at")
            if opened_at:
                if isinstance(opened_at, str):
                    opened_at = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
                cooldown = timedelta(minutes=self._cooldown_minutes)
                if datetime.now(timezone.utc) - opened_at >= cooldown:
                    # Cooldown elapsed → half_open
                    self._update(name, {
                        "state": "half_open",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })
                    logger.info("Circuit %s → half_open (cooldown elapsed)", name)
                    return False  # Allow probe call
            return True  # Still within cooldown

        return False

    def record_success(self, name: str) -> None:
        """Record a successful call. Closes the circuit."""
        now = datetime.now(timezone.utc).isoformat()
        self._ensure_row(name)
        self._update(name, {
            "consecutive_failures": 0,
            "state": "closed",
            "last_success_at": now,
            "updated_at": now,
        })
        logger.debug("Circuit %s: success recorded, state=closed", name)

    def record_failure(self, name: str) -> None:
        """Record a failed call. May open the circuit."""
        row = self._ensure_row(name)
        now = datetime.now(timezone.utc).isoformat()
        failures = row.get("consecutive_failures", 0) + 1
        current_state = row.get("state", "closed")

        update: dict[str, Any] = {
            "consecutive_failures": failures,
            "last_failure_at": now,
            "updated_at": now,
        }

        if current_state == "half_open":
            # Probe failed → back to open
            update["state"] = "open"
            update["opened_at"] = now
            logger.warning("Circuit %s: probe failed → open (failures=%d)", name, failures)
        elif failures >= self._failure_threshold:
            update["state"] = "open"
            update["opened_at"] = now
            logger.warning(
                "Circuit %s: OPENED after %d consecutive failures (threshold=%d)",
                name, failures, self._failure_threshold,
            )
        else:
            update["state"] = current_state  # Stay in current state

        self._update(name, update)

    def get_state(self, name: str) -> dict[str, Any]:
        """Get the current circuit state."""
        return self._ensure_row(name)

    def get_all_circuits(self) -> list[dict[str, Any]]:
        """Get all circuit states."""
        resp = self._client.table("service_circuits").select("*").execute()
        return resp.data if resp and resp.data else []

    def reset(self, name: str) -> None:
        """Manually reset a circuit to closed."""
        now = datetime.now(timezone.utc).isoformat()
        self._update(name, {
            "consecutive_failures": 0,
            "state": "closed",
            "opened_at": None,
            "updated_at": now,
        })
        logger.info("Circuit %s manually reset to closed", name)

    def _update(self, name: str, data: dict[str, Any]) -> None:
        self._client.table("service_circuits").update(data).eq("name", name).execute()
