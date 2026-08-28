"""Tests for sponsor database presence and non-empty validation."""
from pathlib import Path
import pytest

from job_radar.visa.db import load_all_sponsors


def test_missing_db_raises_runtime_error(tmp_path: Path):
    missing_path = tmp_path / "nonexistent.db"
    with pytest.raises(RuntimeError, match="missing"):
        load_all_sponsors(db_path=missing_path, allow_empty=False)


def test_empty_db_raises_runtime_error(tmp_path: Path):
    empty_path = tmp_path / "empty.db"
    empty_path.touch()
    with pytest.raises(RuntimeError, match="empty"):
        load_all_sponsors(db_path=empty_path, allow_empty=False)


def test_allow_empty_flag_bypasses_error(tmp_path: Path):
    missing_path = tmp_path / "nonexistent.db"
    res = load_all_sponsors(db_path=missing_path, allow_empty=True)
    assert res == {}
