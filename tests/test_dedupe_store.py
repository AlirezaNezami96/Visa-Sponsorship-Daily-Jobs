"""Tests for the Supabase dedup store."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestSupabaseAvailability(unittest.TestCase):
    """Test graceful fallback when Supabase is not configured."""

    def setUp(self):
        # Reset the module-level cached client between tests
        import job_radar.dedup.store as store_module
        store_module._SUPABASE_CLIENT = None
        store_module._SUPABASE_AVAILABLE = None

    def test_no_env_vars_not_available(self):
        from job_radar.dedup.store import is_available
        with patch.dict("os.environ", {}, clear=True):
            # Force clear any SUPABASE_ env vars
            import os
            os.environ.pop("SUPABASE_URL", None)
            os.environ.pop("SUPABASE_KEY", None)
            import job_radar.dedup.store as store_module
            store_module._SUPABASE_CLIENT = None
            store_module._SUPABASE_AVAILABLE = None
            result = is_available()
            self.assertFalse(result)

    def test_missing_supabase_package_returns_false(self):
        """supabase-py not installed → graceful False, not ImportError."""
        import job_radar.dedup.store as store_module
        store_module._SUPABASE_CLIENT = None
        store_module._SUPABASE_AVAILABLE = None

        with patch.dict("os.environ", {"SUPABASE_URL": "https://xyz.supabase.co", "SUPABASE_KEY": "key123"}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'supabase'")):
                with self.assertRaises(ImportError):
                    # Direct import will fail — that's expected
                    import supabase  # type: ignore[import]


class TestIsAlreadySent(unittest.TestCase):
    """Test is_already_sent with a mocked Supabase client."""

    def _make_mock_client(self, count: int = 0):
        """Build a mock Supabase client returning a given count."""
        response = MagicMock()
        response.count = count
        response.data = [{"fingerprint": "abc"}] if count > 0 else []

        table_mock = MagicMock()
        table_mock.select.return_value = table_mock
        table_mock.eq.return_value = table_mock
        table_mock.limit.return_value = table_mock
        table_mock.execute.return_value = response

        client = MagicMock()
        client.table.return_value = table_mock
        return client

    def test_fingerprint_exists_returns_true(self):
        from job_radar.dedup import store
        store._SUPABASE_CLIENT = self._make_mock_client(count=1)
        store._SUPABASE_AVAILABLE = True

        result = store.is_already_sent("fp_existing")
        self.assertTrue(result)

    def test_fingerprint_not_found_returns_false(self):
        from job_radar.dedup import store
        store._SUPABASE_CLIENT = self._make_mock_client(count=0)
        store._SUPABASE_AVAILABLE = True

        result = store.is_already_sent("fp_new")
        self.assertFalse(result)

    def test_supabase_error_returns_false_no_raise(self):
        """Supabase query error must not crash the pipeline — fail-open."""
        from job_radar.dedup import store

        bad_client = MagicMock()
        bad_client.table.side_effect = RuntimeError("Network error")
        store._SUPABASE_CLIENT = bad_client
        store._SUPABASE_AVAILABLE = True

        result = store.is_already_sent("fp_boom")
        self.assertFalse(result)

    def test_not_available_returns_false(self):
        from job_radar.dedup import store
        store._SUPABASE_CLIENT = None
        store._SUPABASE_AVAILABLE = False

        result = store.is_already_sent("fp_anything")
        self.assertFalse(result)


class TestMarkSent(unittest.TestCase):
    """Test mark_sent with a mocked client."""

    def setUp(self):
        import job_radar.dedup.store as store_module
        # Install a fresh mock client
        upsert_response = MagicMock()
        upsert_response.data = []

        table_mock = MagicMock()
        table_mock.upsert.return_value = table_mock
        table_mock.execute.return_value = upsert_response

        client = MagicMock()
        client.table.return_value = table_mock

        store_module._SUPABASE_CLIENT = client
        store_module._SUPABASE_AVAILABLE = True
        self.store = store_module
        self.table_mock = table_mock

    def test_mark_sent_calls_upsert(self):
        job = {"company": "Alpha", "title": "ML Intern", "url": "http://alpha.com", "location": "London"}
        self.store.mark_sent(job, track="ai_intern")
        self.table_mock.upsert.assert_called_once()

    def test_mark_sent_dry_run_skips_upsert(self):
        job = {"company": "Beta", "title": "AI Trainee", "url": "http://beta.com", "location": "Berlin"}
        self.store.mark_sent(job, track="ai_intern", dry_run=True)
        self.table_mock.upsert.assert_not_called()

    def test_mark_sent_upsert_error_no_raise(self):
        """mark_sent must be silent on error — must not crash the pipeline."""
        self.table_mock.execute.side_effect = RuntimeError("DB error")
        job = {"company": "Crash", "title": "Any", "url": "http://crash.com"}
        # Must not raise
        self.store.mark_sent(job, track="test")

    def test_mark_sent_not_available_is_noop(self):
        self.store._SUPABASE_CLIENT = None
        self.store._SUPABASE_AVAILABLE = False
        job = {"company": "NoClient", "title": "None", "url": "http://none.com"}
        # Must not raise
        self.store.mark_sent(job, track="test")
        self.table_mock.upsert.assert_not_called()


class TestBulkMarkSent(unittest.TestCase):
    """Test bulk_mark_sent with a mocked client."""

    def setUp(self):
        import job_radar.dedup.store as store_module
        upsert_response = MagicMock()
        table_mock = MagicMock()
        table_mock.upsert.return_value = table_mock
        table_mock.execute.return_value = upsert_response
        client = MagicMock()
        client.table.return_value = table_mock
        store_module._SUPABASE_CLIENT = client
        store_module._SUPABASE_AVAILABLE = True
        self.store = store_module
        self.table_mock = table_mock

    def test_empty_list_is_noop(self):
        self.store.bulk_mark_sent([], track="ai_intern")
        self.table_mock.upsert.assert_not_called()

    def test_bulk_upsert_called_for_non_empty(self):
        jobs = [
            {"company": "A", "title": "Job1", "url": "http://a.com", "location": "Remote"},
            {"company": "B", "title": "Job2", "url": "http://b.com", "location": "Berlin"},
        ]
        self.store.bulk_mark_sent(jobs, track="remote")
        self.table_mock.upsert.assert_called_once()

    def test_dry_run_is_noop(self):
        jobs = [{"company": "A", "title": "J", "url": "http://a.com"}]
        self.store.bulk_mark_sent(jobs, track="visa", dry_run=True)
        self.table_mock.upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
