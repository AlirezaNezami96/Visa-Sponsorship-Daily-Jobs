"""
Google Indexing API Service for VisaLane.
Notifies Google immediately when job postings are created/updated (URL_UPDATED)
or when job postings are expired/closed (URL_DELETED).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

INDEXING_API_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"


class GoogleIndexingService:
    def __init__(self):
        self._credentials = None
        self._enabled = False
        self._init_credentials()

    def _init_credentials(self) -> None:
        """Initialize Google OAuth2 service account credentials if provided."""
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_INDEXING_CREDENTIALS_PATH")
        cred_json = os.environ.get("GOOGLE_INDEXING_CREDENTIALS_JSON")

        if cred_path and os.path.exists(cred_path):
            try:
                from google.oauth2 import service_account
                self._credentials = service_account.Credentials.from_service_account_file(
                    cred_path,
                    scopes=["https://www.googleapis.com/auth/indexing"],
                )
                self._enabled = True
                logger.info("Google Indexing API initialized with credentials file: %s", cred_path)
            except Exception as e:
                logger.warning("Failed to load Google Indexing credentials file: %s", e)

        elif cred_json:
            try:
                from google.oauth2 import service_account
                info = json.loads(cred_json)
                self._credentials = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=["https://www.googleapis.com/auth/indexing"],
                )
                self._enabled = True
                logger.info("Google Indexing API initialized from JSON environment variable.")
            except Exception as e:
                logger.warning("Failed to load Google Indexing credentials JSON: %s", e)
        else:
            logger.debug("Google Indexing API not configured (optional service account missing).")

    @property
    def is_configured(self) -> bool:
        return self._enabled and self._credentials is not None

    async def notify_url_updated(self, url: str) -> Dict[str, Any]:
        """Notify Google that a job URL has been created or updated."""
        return await self._publish_notification(url, "URL_UPDATED")

    async def notify_url_deleted(self, url: str) -> Dict[str, Any]:
        """Notify Google that a job URL has been closed or removed."""
        return await self._publish_notification(url, "URL_DELETED")

    async def _publish_notification(self, url: str, action: str) -> Dict[str, Any]:
        """Send notification payload to Google Indexing API."""
        if not self.is_configured:
            logger.debug("Google Indexing skipped for %s (%s): API unconfigured.", url, action)
            return {"success": True, "skipped": True, "reason": "unconfigured"}

        try:
            import google.auth.transport.requests
            import httpx

            # Refresh token
            request = google.auth.transport.requests.Request()
            self._credentials.refresh(request)
            token = self._credentials.token

            payload = {
                "url": url,
                "type": action,
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(INDEXING_API_ENDPOINT, json=payload, headers=headers)
                if resp.status_code in (200, 202):
                    logger.info("Google Indexing API notified: %s for %s", action, url)
                    return {"success": True, "response": resp.json()}
                else:
                    logger.warning("Google Indexing API returned %s: %s", resp.status_code, resp.text)
                    return {"success": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            logger.warning("Google Indexing API request failed for %s (%s): %s", url, action, e)
            return {"success": False, "error": str(e)}


_SERVICE_INSTANCE = None


def get_indexing_service() -> GoogleIndexingService:
    global _SERVICE_INSTANCE
    if _SERVICE_INSTANCE is None:
        _SERVICE_INSTANCE = GoogleIndexingService()
    return _SERVICE_INSTANCE
