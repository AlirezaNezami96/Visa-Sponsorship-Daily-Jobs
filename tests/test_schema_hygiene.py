"""Schema hygiene regression test — verifies that all columns referenced in Python code exist in SQL migrations."""
from pathlib import Path
import pytest

MIGRATIONS_DIR = Path(__file__).parent.parent / "supabase" / "migrations"


def test_platform_post_published_columns_in_migrations():
    """Verify all 7 platform post published columns exist in migration SQL files."""
    required_columns = [
        "telegram_post_published",
        "discord_post_published",
        "slack_post_published",
        "bluesky_post_published",
        "mastodon_post_published",
        "linkedin_post_published",
        "x_post_published",
    ]

    all_sql = ""
    for sql_file in MIGRATIONS_DIR.glob("*.sql"):
        all_sql += sql_file.read_text() + "\n"

    for col in required_columns:
        assert col in all_sql, f"Missing column {col} in supabase/migrations/*.sql"


def test_pipeline_functions_and_tables_in_migrations():
    """Verify core tables and functions exist in migrations."""
    all_sql = ""
    for sql_file in MIGRATIONS_DIR.glob("*.sql"):
        all_sql += sql_file.read_text() + "\n"

    required_entities = [
        "job_processing",
        "service_circuits",
        "processing_quarantine",
        "platform_post_config",
        "metrics_daily",
        "pipeline_health",
        "admin_users",
        "record_metric",
        "claim_next_post_job",
        "job-cards",
    ]

    for entity in required_entities:
        assert entity in all_sql, f"Missing entity/function {entity} in supabase/migrations/*.sql"
