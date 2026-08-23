"""Google Drive Storage Client for Durable Media Archiving.

Supports Service Account credentials passed as a JSON string (GitHub Secrets),
file path, or local credentials.json.
Provides predictable hierarchical folder management and idempotent media caching.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]


class GoogleDriveStorageClient:
    """Handles persistent media archiving and retrieval to/from Google Drive."""

    def __init__(
        self,
        credentials_json: Optional[str] = None,
        root_folder_id: Optional[str] = None,
    ):
        self.raw_credentials = credentials_json or os.environ.get("GOOGLE_DRIVE_CREDENTIALS")
        self.root_folder_id = (
            root_folder_id
            or os.environ.get("GOOGLE_DRIVE_ROOT_FOLDER_ID")
            or os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
        ).strip()
        self._service = None
        self._folder_cache: Dict[str, str] = {}
        self._init_service()

    def _get_credentials_object(self):
        """Constructs Google OAuth2 service account credentials."""
        from google.oauth2 import service_account

        # 1. Direct JSON string from env var (supports base64 and escaped newlines)
        if self.raw_credentials:
            raw = self.raw_credentials.strip()

            # Attempt base64 decoding if not starting with {
            if not (raw.startswith("{") and raw.endswith("}")):
                import base64
                try:
                    decoded = base64.b64decode(raw).decode("utf-8")
                    if decoded.strip().startswith("{") and decoded.strip().endswith("}"):
                        raw = decoded.strip()
                except Exception:
                    pass

            if raw.startswith("{") and raw.endswith("}"):
                try:
                    info = json.loads(raw)
                    # Normalize escaped newlines in private_key if present
                    if "private_key" in info and "\\n" in info["private_key"]:
                        info["private_key"] = info["private_key"].replace("\\n", "\n")
                    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
                except Exception as e:
                    logger.warning("Failed to parse JSON from GOOGLE_DRIVE_CREDENTIALS: %s", e)
            elif Path(raw).exists():
                return service_account.Credentials.from_service_account_file(raw, scopes=SCOPES)

        # 2. GOOGLE_APPLICATION_CREDENTIALS
        gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if gac and Path(gac).exists():
            return service_account.Credentials.from_service_account_file(gac, scopes=SCOPES)

        # 3. Standard file candidates
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        candidates = [
            repo_root / "credentials.json",
            repo_root / "engine" / "credentials.json",
            Path("credentials.json"),
            Path("engine/credentials.json"),
        ]
        for cand in candidates:
            if cand.exists() and cand.is_file():
                return service_account.Credentials.from_service_account_file(str(cand), scopes=SCOPES)

        return None

    def _init_service(self) -> None:
        try:
            creds = self._get_credentials_object()
            if creds:
                from googleapiclient.discovery import build
                self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
                logger.info("✅ Connected to Google Drive storage service.")
        except Exception as e:
            logger.debug("Google Drive client not initialized: %s", e)
            self._service = None

    @property
    def is_configured(self) -> bool:
        return self._service is not None

    def get_or_create_folder(self, folder_name: str, parent_id: Optional[str] = None) -> str:
        """Finds or creates a folder under parent_id (or root_folder_id)."""
        if not self.is_configured:
            return ""

        effective_parent = parent_id or self.root_folder_id
        cache_key = f"{effective_parent}:{folder_name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        query = (
            f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        if effective_parent:
            query += f" and '{effective_parent}' in parents"

        try:
            results = (
                self._service.files()
                .list(q=query, spaces="drive", fields="files(id, name)", pageSize=1)
                .execute()
            )
            files = results.get("files", [])
            if files:
                folder_id = files[0]["id"]
                self._folder_cache[cache_key] = folder_id
                return folder_id

            # Create new folder
            metadata: Dict[str, Any] = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder",
            }
            if effective_parent:
                metadata["parents"] = [effective_parent]

            folder = self._service.files().create(body=metadata, fields="id").execute()
            folder_id = folder.get("id")
            self._folder_cache[cache_key] = folder_id
            return folder_id
        except Exception as exc:
            logger.error("Failed to get or create folder '%s': %s", folder_name, exc)
            return ""

    def get_post_media_folder(self, source_post_id: str) -> str:
        """Ensures hierarchy: 'LinkedIn Automation/Source Media/<source_post_id>'."""
        if not self.is_configured:
            return ""

        top_folder = self.get_or_create_folder("LinkedIn Automation", parent_id=self.root_folder_id or None)
        source_media_folder = self.get_or_create_folder("Source Media", parent_id=top_folder or None)
        post_folder = self.get_or_create_folder(str(source_post_id), parent_id=source_media_folder or None)
        return post_folder

    def find_file(self, filename: str, folder_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Finds an existing file in folder_id by name."""
        if not self.is_configured:
            return None

        query = f"name = '{filename}' and trashed = false"
        if folder_id:
            query += f" and '{folder_id}' in parents"

        try:
            results = (
                self._service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="files(id, name, mimeType, size, md5Checksum, webViewLink)",
                    pageSize=1,
                )
                .execute()
            )
            files = results.get("files", [])
            return files[0] if files else None
        except Exception as e:
            logger.debug("Error finding file '%s': %s", filename, e)
            return None

    def upload_file(
        self,
        content: bytes | Path,
        filename: str,
        mime_type: str = "application/octet-stream",
        folder_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Uploads file content to Google Drive, returning file metadata."""
        if not self.is_configured:
            return None

        from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload

        # Check if file already exists
        existing = self.find_file(filename, folder_id)
        if existing:
            logger.info("File '%s' already exists in Google Drive (id=%s).", filename, existing.get("id"))
            return existing

        file_metadata: Dict[str, Any] = {"name": filename}
        if folder_id:
            file_metadata["parents"] = [folder_id]

        try:
            if isinstance(content, Path):
                media = MediaFileUpload(str(content), mimetype=mime_type, resumable=True)
            else:
                media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=True)

            uploaded = (
                self._service.files()
                .create(
                    body=file_metadata,
                    media_body=media,
                    fields="id, name, mimeType, size, md5Checksum, webViewLink",
                )
                .execute()
            )
            logger.info("Successfully uploaded '%s' to Google Drive (id=%s)", filename, uploaded.get("id"))
            return uploaded
        except Exception as exc:
            logger.error("Failed to upload '%s' to Google Drive: %s", filename, exc)
            return None

    def download_file(self, file_id: str, destination_path: Path) -> Optional[Path]:
        """Downloads a file from Google Drive to local destination_path."""
        if not self.is_configured:
            return None

        from googleapiclient.http import MediaIoBaseDownload

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            request = self._service.files().get_media(fileId=file_id)
            with open(destination_path, "wb") as f:
                downloader = MediaIoBaseDownload(f, request, chunksize=1024 * 1024 * 5)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
            logger.info("Downloaded Drive file %s to %s", file_id, destination_path)
            return destination_path
        except Exception as exc:
            logger.error("Failed to download Google Drive file %s: %s", file_id, exc)
            return None
