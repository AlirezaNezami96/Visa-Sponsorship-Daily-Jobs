"""LinkedIn REST API Publisher for Text, Image, Multi-Image, and Video Posts."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import requests

from job_radar.social.publisher import get_linkedin_api_version, upload_image_to_linkedin

logger = logging.getLogger(__name__)


class LinkedInRepurposePublisher:
    """Handles publishing finalized repurposed content and media to LinkedIn."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        person_urn: Optional[str] = None,
    ):
        self.access_token = access_token or os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
        self.person_urn = (
            person_urn
            or os.environ.get("LINKEDIN_PERSON_URN")
            or "urn:li:person:aAOQrAt7pG"
        ).strip()
        if self.person_urn and not self.person_urn.startswith("urn:li:person:"):
            self.person_urn = f"urn:li:person:{self.person_urn}"

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token and self.person_urn)

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "LinkedIn-Version": get_linkedin_api_version(),
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    def upload_video_to_linkedin(self, video_path: Path) -> Optional[str]:
        """
        Uploads a video to LinkedIn via the Videos API:
          1. POST https://api.linkedin.com/rest/videos?action=initializeUpload
          2. PUT video bytes to uploadUrl
          Returns: video_urn (e.g. 'urn:li:video:...') or None
        """
        if not self.is_configured or not video_path.exists():
            return None

        file_size = video_path.stat().st_size
        init_url = "https://api.linkedin.com/rest/videos?action=initializeUpload"
        init_body = {
            "initializeUploadRequest": {
                "owner": self.person_urn,
                "fileSizeBytes": file_size,
                "uploadCaptions": False,
                "uploadThumbnail": False,
            }
        }

        try:
            init_res = requests.post(init_url, headers=self._get_headers(), json=init_body, timeout=20)
            if init_res.status_code != 200:
                logger.error("LinkedIn video initializeUpload failed (%d): %s", init_res.status_code, init_res.text)
                return None

            data = init_res.json().get("value", {})
            video_urn = data.get("video")
            instructions = data.get("uploadInstructions", [])
            if not video_urn or not instructions:
                logger.error("Invalid response from LinkedIn video init: %s", data)
                return None

            upload_url = instructions[0].get("uploadUrl")
            put_headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/octet-stream",
            }

            logger.info("Uploading video bytes (%d bytes) to LinkedIn...", file_size)
            with open(video_path, "rb") as vf:
                put_res = requests.put(upload_url, headers=put_headers, data=vf, timeout=120)

            if 200 <= put_res.status_code < 300:
                logger.info("Successfully uploaded video to LinkedIn (URN: %s)", video_urn)
                return video_urn
            else:
                logger.error("Video binary upload to LinkedIn failed (%d): %s", put_res.status_code, put_res.text)

        except Exception as exc:
            logger.error("Exception during LinkedIn video upload: %s", exc)

        return None

    def post_comment(self, post_urn: str, comment_text: str) -> bool:
        """Posts a first comment CTA under the newly published post."""
        if not self.is_configured or not post_urn or not comment_text:
            return False

        import urllib.parse
        encoded_urn = urllib.parse.quote(post_urn, safe="")
        comment_url = f"https://api.linkedin.com/rest/socialActions/{encoded_urn}/comments"
        body = {
            "actor": self.person_urn,
            "message": {"text": comment_text.strip()},
        }

        try:
            r = requests.post(comment_url, headers=self._get_headers(), json=body, timeout=15)
            if 200 <= r.status_code < 300:
                logger.info("Successfully posted first comment CTA to LinkedIn post %s", post_urn)
                return True
            else:
                logger.warning("Posting first comment CTA returned status %d: %s", r.status_code, r.text)
        except Exception as e:
            logger.warning("Could not post first comment to LinkedIn: %s", e)
        return False

    def publish_post(
        self,
        text: str,
        media_files: Optional[List[Path]] = None,
        media_type: str = "none",
        first_comment: Optional[str] = None,
        dry_run: bool = False,
    ) -> Tuple[bool, int, str, str, str]:
        """
        Publishes text commentary, attached media, and optional first-comment CTA to LinkedIn.
        Returns: (success, status_code, post_urn, response_text, post_url)
        """
        if dry_run:
            logger.info("[DRY RUN] LinkedIn publish simulated successfully.")
            sim_urn = "urn:li:share:simulated_dry_run_post_12345"
            sim_url = f"https://www.linkedin.com/feed/update/{sim_urn}/"
            if first_comment:
                logger.info("[DRY RUN] First comment CTA simulated: %s", first_comment)
            return True, 201, sim_urn, "Dry run simulated", sim_url

        if not self.is_configured:
            return False, 0, "", "LinkedIn credentials not configured (LINKEDIN_ACCESS_TOKEN / PERSON_URN)", ""

        post_url_endpoint = "https://api.linkedin.com/rest/posts"
        body: Dict[str, Any] = {
            "author": self.person_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED"},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        # ── 1. Video Attachment ──
        if media_type == "video" and media_files and len(media_files) > 0:
            video_urn = self.upload_video_to_linkedin(media_files[0])
            if video_urn:
                body["content"] = {
                    "media": {
                        "id": video_urn,
                        "title": "Technical AI Demo",
                    }
                }
            else:
                logger.warning("Video upload failed; falling back to text-only publish.")

        # ── 2. Single Image Attachment ──
        elif media_type == "image" and media_files and len(media_files) > 0:
            with open(media_files[0], "rb") as img_f:
                img_bytes = img_f.read()
            img_urn = upload_image_to_linkedin(self.access_token, self.person_urn, img_bytes)
            if img_urn:
                body["content"] = {
                    "media": {
                        "id": img_urn,
                        "altText": "Article Infographic",
                    }
                }

        # ── 3. Multi-Image Attachment ──
        elif media_type == "multi_image" and media_files and len(media_files) > 0:
            images_payload = []
            for img_p in media_files:
                if img_p.exists():
                    with open(img_p, "rb") as img_f:
                        img_urn = upload_image_to_linkedin(self.access_token, self.person_urn, img_f.read())
                    if img_urn:
                        images_payload.append({"id": img_urn, "altText": "Visual Slide"})

            if images_payload:
                if len(images_payload) == 1:
                    body["content"] = {"media": images_payload[0]}
                else:
                    body["content"] = {"multiImage": {"images": images_payload}}

        try:
            logger.info("Sending publication request to LinkedIn...")
            resp = requests.post(post_url_endpoint, headers=self._get_headers(), json=body, timeout=30)
            status_code = resp.status_code
            res_text = resp.text

            if 200 <= status_code < 300:
                post_urn = resp.headers.get("x-restli-id") or resp.headers.get("X-RestLi-Id") or ""
                post_url = f"https://www.linkedin.com/feed/update/{post_urn}/" if post_urn else ""
                logger.info("✅ Published successfully to LinkedIn! (URN: %s)", post_urn)

                # Post first-comment CTA if present
                if first_comment and first_comment.strip() and post_urn:
                    self.post_comment(post_urn, first_comment)

                return True, status_code, post_urn, res_text, post_url
            else:
                logger.error("LinkedIn publish failed with status %d: %s", status_code, res_text)
                return False, status_code, "", res_text, ""

        except Exception as exc:
            logger.error("Network error during LinkedIn post creation: %s", exc)
            return False, 0, "", str(exc), ""
