"""Comprehensive Automated Test Suite for LinkedIn Content Repurposing Pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from job_radar.repurpose import (
    ContentDeduplicator,
    ContentRewriter,
    ImportSummary,
    LinkedInRepurposePublisher,
    MediaManager,
    MediaType,
    ProcessingStatus,
    RepurposeOrchestrator,
    SourcePostImporter,
    SourcePostMediaRecord,
    SourcePostRecord,
    SourcePostSelector,
)
from job_radar.storage.google_drive_client import GoogleDriveStorageClient
from job_radar.storage.supabase_client import SupabaseStorageClient


# ── 1. Content Normalization & Exact Deduplication Tests ──

def test_content_deduplicator_normalization():
    dedup = ContentDeduplicator()
    raw = "  Hello   World!\r\nCheck this out: https://example.com/blog?utm_source=linkedin&trk=feed_post \n\n\nAwesome.  "
    norm = dedup.normalize_text(raw)

    assert "utm_source" not in norm
    assert "trk=" not in norm
    assert "\r" not in norm
    assert "\n\n\n" not in norm
    assert norm.startswith("hello world!")


def test_exact_duplicate_hash_matching():
    dedup = ContentDeduplicator()
    text1 = "Redis cache strategies: 1. Cache-Aside 2. Write-Through"
    text2 = "  redis cache strategies:   1. Cache-Aside 2. Write-Through\n "

    hash1 = dedup.compute_content_hash(text1)
    hash2 = dedup.compute_content_hash(text2)

    assert hash1 == hash2


# ── 2. Near-Duplicate Detection Tests ──

def test_near_duplicate_detection_token_similarity():
    dedup = ContentDeduplicator()
    canonical_text = "Here are 4 open-source observability tools every software engineer should bookmark today in 2026."
    near_variant = "Here are 4 open-source observability tools every software engineer must bookmark today in 2026."

    is_dup, matched_id, score = dedup.is_near_duplicate(
        near_variant,
        [("post_101", canonical_text)],
        jaccard_threshold=0.80,
    )

    assert is_dup is True
    assert matched_id == "post_101"
    assert score > 0.80


def test_near_duplicate_different_posts():
    dedup = ContentDeduplicator()
    text_a = "Understanding Git worktrees will completely change your multi-branch productivity."
    text_b = "Redis Cache Invalidation Strategies you must know for backend interviews."

    is_dup, matched_id, score = dedup.is_near_duplicate(
        text_b,
        [("post_101", text_a)],
        jaccard_threshold=0.70,
    )

    assert is_dup is False
    assert score < 0.30


# ── 3. JSON Ingestion & Idempotent Import Tests ──

def test_json_ingestion_and_media_extraction(tmp_path):
    sample_json = [
        {
            "type": "post",
            "id": "11111",
            "content": "First post with video",
            "author": {"name": "Ram Maheshwari", "publicIdentifier": "rammcodes"},
            "postVideo": {"videoUrl": "https://example.com/v.mp4"},
            "postImages": [],
        },
        {
            "type": "post",
            "id": "22222",
            "content": "Second post with image",
            "author": {"name": "Ram Maheshwari", "publicIdentifier": "rammcodes"},
            "postVideo": {},
            "postImages": [{"url": "https://example.com/img1.jpg"}],
        },
        {
            "type": "post",
            "id": "33333",
            "content": "First post with video",  # Exact duplicate of 11111
            "author": {"name": "Ram Maheshwari", "publicIdentifier": "rammcodes"},
            "postVideo": {"videoUrl": "https://example.com/v.mp4"},
            "postImages": [],
        },
    ]

    json_path = tmp_path / "test_posts.json"
    json_path.write_text(json.dumps(sample_json), encoding="utf-8")

    mock_supabase = MagicMock(spec=SupabaseStorageClient)
    mock_supabase.is_configured = False  # In-memory test

    importer = SourcePostImporter(supabase_client=mock_supabase)
    summary = importer.import_dataset(json_path, dry_run=True)

    assert summary.total_parsed == 3
    assert summary.new_imported == 2
    assert summary.exact_duplicates == 1
    assert summary.posts_with_videos == 2
    assert summary.posts_with_images == 1


# ── 4. Atomic Selection & Reservation Tests ──

def test_source_post_selector_reservation_success():
    mock_supabase = MagicMock(spec=SupabaseStorageClient)
    mock_supabase.is_configured = True
    mock_supabase.reserve_next_post.return_value = {
        "id": 42,
        "source_post_id": "7494632582014406656",
        "content": "Test content for reservation",
        "media_type": "video",
        "failure_count": 0,
    }

    selector = SourcePostSelector(supabase_client=mock_supabase)
    post, worker_id = selector.select_and_reserve_post()

    assert post is not None
    assert post.id == 42
    assert post.source_post_id == "7494632582014406656"
    assert post.media_type == "video"
    assert "gha_" in worker_id or "worker_" in worker_id


def test_source_post_selector_exhausted_dataset():
    mock_supabase = MagicMock(spec=SupabaseStorageClient)
    mock_supabase.is_configured = True
    mock_supabase.reserve_next_post.return_value = None
    mock_supabase.get_available_posts_count.return_value = 0

    selector = SourcePostSelector(supabase_client=mock_supabase)
    post, worker_id = selector.select_and_reserve_post()

    assert post is None


def test_source_post_selector_release_reservation():
    mock_supabase = MagicMock(spec=SupabaseStorageClient)
    mock_supabase.is_configured = True
    mock_supabase.get_post_by_id.return_value = {"failure_count": 1}
    mock_supabase.update_post_status.return_value = True

    selector = SourcePostSelector(supabase_client=mock_supabase)
    success = selector.release_reservation(
        post_id=42,
        execution_id="worker_123",
        retryable=True,
        error_message="Network timeout",
    )

    assert success is True
    mock_supabase.update_post_status.assert_called_once()
    call_kwargs = mock_supabase.update_post_status.call_args.kwargs
    assert call_kwargs["status"] == ProcessingStatus.AVAILABLE.value
    assert call_kwargs["failure_count"] == 2


def test_source_post_selector_permanent_failure_after_3_retries():
    mock_supabase = MagicMock(spec=SupabaseStorageClient)
    mock_supabase.is_configured = True
    mock_supabase.get_post_by_id.return_value = {"failure_count": 2}
    mock_supabase.update_post_status.return_value = True

    selector = SourcePostSelector(supabase_client=mock_supabase)
    selector.release_reservation(
        post_id=42,
        execution_id="worker_123",
        retryable=True,
        error_message="Third failure",
    )

    call_kwargs = mock_supabase.update_post_status.call_args.kwargs
    assert call_kwargs["status"] == ProcessingStatus.FAILED.value
    assert call_kwargs["failure_count"] == 3


# ── 5. Gemini Rewriter & Quality Validation Tests ──

def test_rewriter_sanitize_and_branding_stripping():
    rewriter = ContentRewriter()
    raw_adapted = (
        "Here is the rewritten LinkedIn post:\n\n"
        "Modern observability requires 4 key pillars:\n"
        "- OpenTelemetry for collection\n"
        "- SigNoz & Prometheus for storage\n"
        "- Grafana for visualization\n\n"
        "Follow Ram Maheshwari and rammcodes for more! Repost if you found this helpful."
    )

    sanitized = rewriter.sanitize_output(
        raw_adapted,
        author_name="Ram Maheshwari",
        author_username="rammcodes",
    )

    assert "Here is the rewritten" not in sanitized
    assert "Ram Maheshwari" not in sanitized
    assert "rammcodes" not in sanitized
    assert "Follow" not in sanitized
    assert "Repost" not in sanitized
    assert "OpenTelemetry" in sanitized


def test_rewriter_validation_too_close_to_source():
    rewriter = ContentRewriter()
    source = "Git worktrees allow you to keep multiple branches active simultaneously."
    verbatim_copy = "Git worktrees allow you to keep multiple branches active simultaneously."

    valid, err = rewriter.validate_adaptation(verbatim_copy, source)
    assert valid is False
    assert "too close to source" in err.lower() or "shares too many exact tokens" in err.lower()


def test_rewriter_validation_success():
    rewriter = ContentRewriter()
    source = (
        "Stop doing git pull --rebase blindly.\n"
        "Understanding Git worktrees will completely change your multi-branch productivity:\n"
        "- Keep 3 branches active simultaneously without stash or context switching\n"
        "Command: git worktree add ../feature-branch feature"
    )
    original_adaptation = (
        "Context-switching between branches in Git usually means constant stashing and rebuilding dependencies.\n\n"
        "A cleaner approach is using Git Worktrees:\n"
        "• Check out independent branches into separate directories\n"
        "• Run test suites in one terminal while coding features in another\n\n"
        "Setup:\n"
        "`git worktree add ../feature-work feature`\n\n"
        "Have you used worktrees in your local workflow?"
    )

    valid, err = rewriter.validate_adaptation(original_adaptation, source, "Ram Maheshwari", "rammcodes")
    assert valid is True
    assert err is None


# ── 6. Media Manager & Video Processing Branch Tests ──

def test_media_manager_video_processing(tmp_path):
    mock_drive = MagicMock(spec=GoogleDriveStorageClient)
    mock_drive.is_configured = False
    mock_supabase = MagicMock(spec=SupabaseStorageClient)
    mock_supabase.is_configured = False
    mock_supabase.get_media_for_post.return_value = []

    mgr = MediaManager(drive_client=mock_drive, supabase_client=mock_supabase)

    post = SourcePostRecord(
        id=1,
        source_post_id="post_vid_1",
        media_type=MediaType.VIDEO.value,
        source_json={"postVideo": {"videoUrl": "https://example.com/vid.mp4"}},
    )

    def fake_download(url, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake mp4 video bytes")
        return dest

    with patch.object(mgr, "download_url_to_file", side_effect=fake_download):
        with patch("job_radar.repurpose.media_manager.create_creator_badge_video") as mock_badge:
            def fake_badge(input_path, output_path, **kwargs):
                Path(output_path).write_bytes(b"fake badged video bytes")
                return Path(output_path)

            mock_badge.side_effect = fake_badge

            ok, media_files, err = mgr.prepare_post_media(post, tmp_path)
            assert ok is True
            assert len(media_files) == 1
            assert "branded_post_vid_1.mp4" in str(media_files[0])


# ── 7. LinkedIn Publisher Tests ──

def test_linkedin_publisher_dry_run():
    publisher = LinkedInRepurposePublisher(access_token="test_token", person_urn="urn:li:person:12345")
    ok, code, urn, res, url = publisher.publish_post(
        text="Test commentary text",
        media_type="none",
        dry_run=True,
    )

    assert ok is True
    assert code == 201
    assert "simulated" in urn


# ── 8. Master Orchestrator End-to-End Test ──

def test_linkedin_publisher_multi_image_payload(tmp_path):
    img1 = tmp_path / "img1.jpg"
    img2 = tmp_path / "img2.jpg"
    img1.write_bytes(b"image 1 bytes")
    img2.write_bytes(b"image 2 bytes")

    publisher = LinkedInRepurposePublisher(access_token="test_tok", person_urn="urn:li:person:123")
    with patch("job_radar.repurpose.publisher.upload_image_to_linkedin", side_effect=["urn:li:image:1", "urn:li:image:2"]):
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.headers = {"x-restli-id": "urn:li:share:9999"}
            mock_post.return_value.text = "Created"

            ok, code, urn, res, url = publisher.publish_post(
                text="Multi-image post",
                media_files=[img1, img2],
                media_type="multi_image",
            )
            assert ok is True
            assert urn == "urn:li:share:9999"
            sent_body = mock_post.call_args.kwargs["json"]
            assert "multiImage" in sent_body["content"]
            assert len(sent_body["content"]["multiImage"]["images"]) == 2


def test_cli_import_posts_execution(tmp_path):
    sample_file = tmp_path / "sample.json"
    sample_file.write_text(json.dumps([{
        "type": "post",
        "id": "999001",
        "content": "CLI test content",
        "author": {"name": "Test Author", "publicIdentifier": "testauthor"},
    }]), encoding="utf-8")

    from job_radar.cli.import_posts_cmd import main
    import sys
    orig = sys.argv
    try:
        sys.argv = ["job-radar-import-posts", "--file", str(sample_file), "--dry-run"]
        main()
    finally:
        sys.argv = orig


def test_cli_republish_execution():
    from job_radar.cli.republish_cmd import main
    import sys
    orig = sys.argv
    try:
        sys.argv = ["job-radar-republish", "--dry-run"]
        with patch("job_radar.repurpose.orchestrator.RepurposeOrchestrator.run") as mock_run:
            from job_radar.repurpose.models import RepurposeJobResult
            mock_run.return_value = RepurposeJobResult(success=True, status="published", linkedin_post_urn="urn:li:share:1")
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
    finally:
        sys.argv = orig


def test_rewriter_validation_short_meme_caption():
    rewriter = ContentRewriter()
    source_short = "❌️ Walking Dead\n✅️ Walking Dev"
    adapted_short = "❌️ Coding Dead\n✅️ Coding Dev"

    valid, err = rewriter.validate_adaptation(adapted_short, source_short, "Ram Maheshwari", "rammcodes")
    assert valid is True
    assert err is None


def test_google_drive_base64_and_escaped_newline_credentials():
    import base64
    fake_info = {
        "type": "service_account",
        "project_id": "test-proj",
        "private_key_id": "12345",
        "private_key": "-----BEGIN PRIVATE KEY-----\\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC7\\n-----END PRIVATE KEY-----\\n",
        "client_email": "test@test-proj.iam.gserviceaccount.com",
    }
    json_str = json.dumps(fake_info)
    b64_str = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

    client = GoogleDriveStorageClient(credentials_json=b64_str)
    # Ensure client didn't crash during credential unpacking
    assert client.root_folder_id == "" or isinstance(client.root_folder_id, str)


def test_import_real_rammcodes_dataset():
    dataset_path = Path("assets/rammcodes posts.json")
    if not dataset_path.exists():
        pytest.skip("assets/rammcodes posts.json not present")

    mock_supabase = MagicMock(spec=SupabaseStorageClient)
    mock_supabase.is_configured = False

    importer = SourcePostImporter(supabase_client=mock_supabase)
    summary = importer.import_dataset(dataset_path, dry_run=True)

    assert summary.total_parsed == 200
    assert summary.new_imported == 113
    assert summary.exact_duplicates == 87
    assert summary.errors == []


