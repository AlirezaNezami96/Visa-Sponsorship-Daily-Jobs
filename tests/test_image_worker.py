"""Tests for image worker batching and render logic."""
from unittest.mock import MagicMock, patch
import pytest

from job_radar.pipeline.image_worker import render_and_upload


def test_render_and_upload_missing_job():
    """Verify clean failure when job does not exist."""
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    res = render_and_upload(mock_client, "nonexistent-id")
    assert res["ok"] is False
    assert "not found" in res["error"]
