"""Supabase Client for LinkedIn Source Posts Repurposing Pipeline.

Supports both supabase-py and native PostgREST REST API operations.
Provides atomic reservations, idempotent upserts, and lifecycle status transitions.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)


class SupabaseStorageClient:
    """Handles communication with Supabase for source posts and media metadata."""

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
    ):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = (
            key
            or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            or os.environ.get("SUPABASE_KEY", "")
        ).strip()
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        if not self.url or not self.key:
            logger.debug("Supabase URL or Key not configured.")
            return

        try:
            from supabase import create_client
            self._client = create_client(self.url, self.key)
        except ImportError:
            logger.debug("supabase-py not installed; falling back to direct PostgREST REST API.")
            self._client = None
        except Exception as e:
            logger.warning("Failed to initialize supabase-py client: %s; falling back to REST API.", e)
            self._client = None

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.key)

    def _rest_headers(self) -> Dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    # ── Source Post Operations ──

    def upsert_source_post(self, post_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Upserts a source post record using (source_platform, source_post_id) as conflict target."""
        if not self.is_configured:
            logger.debug("Supabase not configured, skipping upsert.")
            return None

        # Clean null values / format JSONB if needed
        payload = dict(post_data)
        if "source_json" in payload and isinstance(payload["source_json"], (dict, list)):
            payload["source_json"] = payload["source_json"]

        if self._client:
            try:
                res = (
                    self._client.table("source_posts")
                    .upsert(payload, on_conflict="source_platform,source_post_id")
                    .execute()
                )
                if res.data and len(res.data) > 0:
                    return res.data[0]
            except Exception as e:
                logger.warning("supabase-py upsert failed: %s. Trying direct REST API.", e)

        # Fallback to direct PostgREST
        rest_url = f"{self.url}/rest/v1/source_posts?on_conflict=source_platform,source_post_id"
        headers = self._rest_headers()
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
        try:
            resp = requests.post(rest_url, headers=headers, json=payload, timeout=20)
            if resp.status_code in (200, 201):
                data = resp.json()
                return data[0] if isinstance(data, list) and data else None
            else:
                logger.error("REST upsert_source_post error (%d): %s", resp.status_code, resp.text)
        except Exception as exc:
            logger.error("REST upsert_source_post request failed: %s", exc)
        return None

    def upsert_source_media(self, media_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Inserts or updates a source_post_media entry."""
        if not self.is_configured:
            return None

        payload = dict(media_data)
        if self._client:
            try:
                res = self._client.table("source_post_media").upsert(payload).execute()
                if res.data and len(res.data) > 0:
                    return res.data[0]
            except Exception as e:
                logger.warning("supabase-py media upsert failed: %s", e)

        rest_url = f"{self.url}/rest/v1/source_post_media"
        headers = self._rest_headers()
        try:
            resp = requests.post(rest_url, headers=headers, json=payload, timeout=20)
            if resp.status_code in (200, 201):
                data = resp.json()
                return data[0] if isinstance(data, list) and data else None
        except Exception as exc:
            logger.error("REST upsert_source_media request failed: %s", exc)
        return None

    def reserve_next_post(
        self,
        worker_id: str = "github_action",
        max_failures: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        Atomically selects and reserves the next available source post.
        Uses the Postgres RPC function 'reserve_next_source_post' if available,
        with a safe conditional update fallback.
        """
        if not self.is_configured:
            logger.warning("Supabase not configured, cannot reserve post.")
            return None

        # 1. Try RPC call
        if self._client:
            try:
                res = self._client.rpc(
                    "reserve_next_source_post",
                    {"p_worker_id": worker_id, "p_max_failures": max_failures},
                ).execute()
                if res.data and len(res.data) > 0:
                    return res.data[0]
            except Exception as e:
                logger.warning("RPC reserve_next_source_post failed via SDK: %s", e)

        # 2. Try RPC via REST endpoint
        rpc_url = f"{self.url}/rest/v1/rpc/reserve_next_source_post"
        try:
            resp = requests.post(
                rpc_url,
                headers=self._rest_headers(),
                json={"p_worker_id": worker_id, "p_max_failures": max_failures},
                timeout=20,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    return data[0]
                elif isinstance(data, dict) and data:
                    return data
        except Exception as exc:
            logger.debug("REST RPC call failed: %s", exc)

        # 3. Fallback: Conditional update on first available row
        try:
            fetch_url = (
                f"{self.url}/rest/v1/source_posts?"
                f"processing_status=eq.available&failure_count=lt.{max_failures}&"
                f"order=media_archived.desc,id.asc&limit=1"
            )
            fetch_resp = requests.get(fetch_url, headers=self._rest_headers(), timeout=15)
            if fetch_resp.status_code == 200:
                candidates = fetch_resp.json()
                if candidates and isinstance(candidates, list):
                    cand_id = candidates[0]["id"]
                    # Attempt atomic conditional update
                    patch_url = f"{self.url}/rest/v1/source_posts?id=eq.{cand_id}&processing_status=eq.available"
                    patch_resp = requests.patch(
                        patch_url,
                        headers=self._rest_headers(),
                        json={
                            "processing_status": "reserved",
                            "reserved_by": worker_id,
                            "reserved_at": "now()",
                        },
                        timeout=15,
                    )
                    if patch_resp.status_code in (200, 204):
                        data = patch_resp.json()
                        if data and isinstance(data, list):
                            return data[0]
        except Exception as exc:
            logger.error("Fallback reservation query failed: %s", exc)

        return None

    def update_post_status(
        self,
        post_id: int,
        status: str,
        execution_id: Optional[str] = None,
        **extra_fields: Any,
    ) -> bool:
        """
        Updates the lifecycle status of a source post.
        Optionally checks reserved_by matching execution_id for exactly-once safety.
        """
        if not self.is_configured:
            return False

        payload: Dict[str, Any] = {
            "processing_status": status,
            "updated_at": "now()",
            **extra_fields,
        }

        query_params = f"id=eq.{post_id}"
        if execution_id:
            query_params += f"&reserved_by=eq.{execution_id}"

        rest_url = f"{self.url}/rest/v1/source_posts?{query_params}"
        headers = self._rest_headers()
        try:
            resp = requests.patch(rest_url, headers=headers, json=payload, timeout=20)
            return resp.status_code in (200, 204)
        except Exception as exc:
            logger.error("Failed to update post status %d: %s", post_id, exc)
            return False

    def get_post_by_id(self, post_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single source post record by its database ID."""
        if not self.is_configured:
            return None

        rest_url = f"{self.url}/rest/v1/source_posts?id=eq.{post_id}&limit=1"
        try:
            resp = requests.get(rest_url, headers=self._rest_headers(), timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data[0] if isinstance(data, list) and data else None
        except Exception as exc:
            logger.error("Failed to fetch post %d: %s", post_id, exc)
        return None

    def get_media_for_post(self, post_id: int) -> List[Dict[str, Any]]:
        """Retrieves all media records associated with a source post."""
        if not self.is_configured:
            return []

        rest_url = f"{self.url}/rest/v1/source_post_media?source_post_id=eq.{post_id}&order=id.asc"
        try:
            resp = requests.get(rest_url, headers=self._rest_headers(), timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else []
        except Exception as exc:
            logger.error("Failed to fetch media for post %d: %s", post_id, exc)
        return []

    def get_available_posts_count(self) -> int:
        """Returns the number of available source posts remaining."""
        if not self.is_configured:
            return 0

        rest_url = f"{self.url}/rest/v1/source_posts?processing_status=eq.available&select=id"
        headers = self._rest_headers()
        headers["Prefer"] = "count=exact"
        try:
            resp = requests.get(rest_url, headers=headers, timeout=15)
            range_header = resp.headers.get("Content-Range", "")
            if "/" in range_header:
                count_str = range_header.split("/")[-1]
                if count_str.isdigit():
                    return int(count_str)
            if resp.status_code == 200:
                return len(resp.json())
        except Exception as exc:
            logger.debug("Failed to count available posts: %s", exc)
        return 0
