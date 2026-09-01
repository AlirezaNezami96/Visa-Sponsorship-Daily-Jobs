"""Tests verifying admin security architecture and SQL migrations."""
import re
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent


def test_admin_migration_sql_structure():
    migration_file = ROOT_DIR / "supabase" / "migrations" / "2026090101_max_security_admin_crm.sql"
    assert migration_file.exists(), "Admin security migration missing"

    content = migration_file.read_text()

    # 1. Table definitions
    assert "CREATE TABLE IF NOT EXISTS public.admin_users" in content
    assert "CREATE TABLE IF NOT EXISTS public.admin_audit_log" in content
    assert "CREATE TABLE IF NOT EXISTS public.admin_stepup_challenges" in content

    # 2. Security definer functions
    assert "CREATE OR REPLACE FUNCTION public.is_admin()" in content
    assert "SECURITY DEFINER" in content
    assert "CREATE OR REPLACE FUNCTION public.is_admin_owner()" in content

    # 3. RLS policies
    assert "ALTER TABLE public.admin_users ENABLE ROW LEVEL SECURITY;" in content
    assert "ALTER TABLE public.admin_audit_log ENABLE ROW LEVEL SECURITY;" in content
    assert "CREATE POLICY \"admin_read_users\" ON public.admin_users" in content
    assert "CREATE POLICY \"owner_write_users\" ON public.admin_users" in content
    assert "CREATE POLICY \"admin_read_audit\" ON public.admin_audit_log" in content

    # 4. Initial seed
    assert "alirezanezami96@gmail.com" in content
    assert "'owner'" in content


def test_admin_security_headers_defined():
    http_file = ROOT_DIR / "supabase" / "functions" / "_shared" / "http.ts"
    assert http_file.exists()

    content = http_file.read_text()
    assert "Strict-Transport-Security" in content
    assert "Content-Security-Policy" in content
    assert "X-Frame-Options" in content
    assert "DENY" in content
    assert "nosniff" in content
    assert "strict-origin-when-cross-origin" in content


def test_admin_edge_functions_wired():
    funcs_dir = ROOT_DIR / "supabase" / "functions"
    required_funcs = [
        "admin-metrics",
        "admin-retry",
        "admin-stepup",
        "admin-sessions",
        "admin-audit",
        "admin-users",
        "admin-login-notify",
    ]
    for func in required_funcs:
        fn_path = funcs_dir / func / "index.ts"
        assert fn_path.exists(), f"Edge function {func} is missing"
        fn_code = fn_path.read_text()
        assert "verifyAdminSession" in fn_code, f"{func} does not use verifyAdminSession"
