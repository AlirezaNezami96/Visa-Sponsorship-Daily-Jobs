"""Tests for the job freshness filter."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone


class TestIsFreshEnough(unittest.TestCase):
    """Test freshness filter with various date formats."""

    def setUp(self):
        from job_radar.filters.freshness import is_fresh_enough
        self.is_fresh = is_fresh_enough

    # ---- Fail-open cases ----

    def test_no_date_field_returns_true(self):
        self.assertTrue(self.is_fresh({}))

    def test_empty_string_returns_true(self):
        self.assertTrue(self.is_fresh({"date_posted": ""}))

    def test_none_value_returns_true(self):
        self.assertTrue(self.is_fresh({"date_posted": None}))

    def test_unparseable_string_returns_true(self):
        self.assertTrue(self.is_fresh({"date_posted": "two weeks ago sometime maybe"}))

    def test_garbage_returns_true(self):
        self.assertTrue(self.is_fresh({"date_posted": "🦆🦆🦆"}))

    # ---- Fresh sentinels ----

    def test_just_posted(self):
        self.assertTrue(self.is_fresh({"date_posted": "Just posted"}))

    def test_today(self):
        self.assertTrue(self.is_fresh({"date_posted": "Today"}))

    def test_just_posted_case_insensitive(self):
        self.assertTrue(self.is_fresh({"date_posted": "JUST POSTED"}))

    # ---- Stale sentinels ----

    def test_30_plus_days_ago_stale(self):
        self.assertFalse(self.is_fresh({"date_posted": "30+ days ago"}, max_age_days=5))

    def test_more_than_30_days_stale(self):
        self.assertFalse(self.is_fresh({"date_posted": "more than 30 days ago"}, max_age_days=5))

    def test_over_30_days_stale(self):
        self.assertFalse(self.is_fresh({"date_posted": "over 30 days ago"}, max_age_days=5))

    # ---- Relative: days ago ----

    def test_1_day_ago_fresh(self):
        self.assertTrue(self.is_fresh({"date_posted": "1 day ago"}, max_age_days=5))

    def test_yesterday_fresh(self):
        self.assertTrue(self.is_fresh({"date_posted": "yesterday"}, max_age_days=5))

    def test_3_days_ago_fresh(self):
        self.assertTrue(self.is_fresh({"date_posted": "3 days ago"}, max_age_days=5))

    def test_5_days_ago_exactly_fresh(self):
        self.assertTrue(self.is_fresh({"date_posted": "5 days ago"}, max_age_days=5))

    def test_6_days_ago_stale(self):
        self.assertFalse(self.is_fresh({"date_posted": "6 days ago"}, max_age_days=5))

    def test_10_days_ago_stale(self):
        self.assertFalse(self.is_fresh({"date_posted": "10 days ago"}, max_age_days=5))

    # ---- Relative: hours ago ----

    def test_2_hours_ago_fresh(self):
        self.assertTrue(self.is_fresh({"date_posted": "2 hours ago"}, max_age_days=5))

    def test_48_hours_ago_still_fresh_within_window(self):
        # 48 hours = 2 days — within max_age_days=5
        self.assertTrue(self.is_fresh({"date_posted": "48 hours ago"}, max_age_days=5))

    # ---- Relative: minutes ago ----

    def test_30_minutes_ago(self):
        self.assertTrue(self.is_fresh({"date_posted": "30 minutes ago"}, max_age_days=5))

    # ---- Relative: weeks ago ----

    def test_1_week_ago_stale_with_5_day_window(self):
        self.assertFalse(self.is_fresh({"date_posted": "1 week ago"}, max_age_days=5))

    def test_1_week_ago_fresh_with_10_day_window(self):
        self.assertTrue(self.is_fresh({"date_posted": "1 week ago"}, max_age_days=10))

    # ---- ISO date ----

    def test_iso_date_today_fresh(self):
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        self.assertTrue(self.is_fresh({"date_posted": today}, max_age_days=5))

    def test_iso_date_yesterday_fresh(self):
        yesterday = (datetime.now(tz=timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertTrue(self.is_fresh({"date_posted": yesterday}, max_age_days=5))

    def test_iso_date_old_stale(self):
        old = (datetime.now(tz=timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        self.assertFalse(self.is_fresh({"date_posted": old}, max_age_days=5))

    def test_iso_datetime_with_utc_fresh(self):
        recent = (datetime.now(tz=timezone.utc) - timedelta(hours=3)).isoformat()
        self.assertTrue(self.is_fresh({"date_posted": recent}, max_age_days=5))

    def test_iso_datetime_with_z_suffix_fresh(self):
        recent = (datetime.now(tz=timezone.utc) - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertTrue(self.is_fresh({"date_posted": recent}, max_age_days=5))

    # ---- Alternate field names ----

    def test_posted_at_field(self):
        self.assertTrue(self.is_fresh({"posted_at": "1 day ago"}, max_age_days=5))

    def test_created_at_field(self):
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        self.assertTrue(self.is_fresh({"created_at": today}, max_age_days=5))

    def test_published_at_field(self):
        self.assertTrue(self.is_fresh({"published_at": "Just posted"}, max_age_days=5))

    # ---- filter_fresh_jobs batch helper ----

    def test_filter_fresh_jobs_drops_stale(self):
        from job_radar.filters.freshness import filter_fresh_jobs
        jobs = [
            {"title": "Fresh", "date_posted": "1 day ago"},
            {"title": "Stale", "date_posted": "30+ days ago"},
            {"title": "No date"},
        ]
        result = filter_fresh_jobs(jobs, max_age_days=5)
        titles = [j["title"] for j in result]
        self.assertIn("Fresh", titles)
        self.assertIn("No date", titles)
        self.assertNotIn("Stale", titles)


if __name__ == "__main__":
    unittest.main()
