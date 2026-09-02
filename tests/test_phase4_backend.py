"""
Automated unit and integration test suite for VisaLane Phase 4 Backend API.
Verifies locales, localized reference data, blog/content engine,
fallback semantics (is_fallback: True), admin authentication boundaries,
and Supabase integration branches.
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from engine.api.main import app
from engine.api.cache import clear_all_caches
from engine.api.jobs_models import (
    JobDetail,
    StructuredJobLocation,
    BaseSalary,
    SalaryValue,
    CompanySummary,
    to_job_posting_json_ld,
)
from engine.api.jobs_routes import (
    ADMIN_SECRET_KEY,
    clear_mock_stores,
    limiter,
    set_mock_posts_store,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_phase4_data():
    """Seed sample content posts and translations."""
    try:
        limiter.reset()
    except Exception:
        pass
    clear_all_caches()
    clear_mock_stores()

    now = datetime.datetime.now(datetime.timezone.utc)
    one_day_ago = (now - datetime.timedelta(days=1)).isoformat()
    two_days_ago = (now - datetime.timedelta(days=2)).isoformat()

    post1_id = "p1111111-1111-1111-1111-111111111111"
    post2_id = "p2222222-2222-2222-2222-222222222222"
    post3_id = "p3333333-3333-3333-3333-333333333333"

    posts_store = {
        post1_id: {
            "id": post1_id,
            "slug": "germany-opportunity-card-chancenkarte-guide",
            "category": "policy-radar",
            "author": "VisaLane Policy Team",
            "canonical_locale": "en",
            "status": "published",
            "featured_image_url": "https://img.visalane.com/chancenkarte.jpg",
            "published_at": one_day_ago,
            "updated_at": one_day_ago,
        },
        post2_id: {
            "id": post2_id,
            "slug": "uk-skilled-worker-salary-thresholds",
            "category": "guide",
            "author": "Immigration Intelligence Unit",
            "canonical_locale": "en",
            "status": "published",
            "featured_image_url": "https://img.visalane.com/uk-thresholds.jpg",
            "published_at": two_days_ago,
            "updated_at": two_days_ago,
        },
        # Draft post (should not appear in public lists)
        post3_id: {
            "id": post3_id,
            "slug": "draft-unreleased-immigration-report",
            "category": "data-report",
            "author": "VisaLane Data Team",
            "canonical_locale": "en",
            "status": "draft",
            "published_at": one_day_ago,
            "updated_at": one_day_ago,
        },
    }
    translations_store = {
        post1_id: {
            "en": {
                "id": "t1-en",
                "post_id": post1_id,
                "locale": "en",
                "title": "Germany Opportunity Card (Chancenkarte) 2026: Complete Guide",
                "body_markdown": "# Germany Opportunity Card Guide\nEverything you need to know about the points-based immigration system.",
                "meta_description": "Complete breakdown of the German Chancenkarte opportunity card criteria and requirements.",
            },
            "es": {
                "id": "t1-es",
                "post_id": post1_id,
                "locale": "es",
                "title": "Tarjeta de Oportunidad de Alemania (Chancenkarte) 2026: Guía Completa",
                "body_markdown": "# Guía de la Tarjeta de Oportunidad\nTodo lo que necesitas saber sobre el sistema de puntos.",
                "meta_description": "Desglose completo de los criterios y requisitos de la Chancenkarte alemana.",
            },
            "ar": {
                "id": "t1-ar",
                "post_id": post1_id,
                "locale": "ar",
                "title": "بطاقة الفرص الألمانية (Chancenkarte) 2026: الدليل الشامل",
                "body_markdown": "# دليل بطاقة الفرص الألمانية\nكل ما تحتاج لمعرفته حول نظام الهجرة القائم على النقاط في ألمانيا.",
                "meta_description": "تفاصيل شاملة حول معايير وشروط بطاقة الفرص الألمانية الجديدة.",
            },
        },
        post2_id: {
            "en": {
                "id": "t2-en",
                "post_id": post2_id,
                "locale": "en",
                "title": "UK Skilled Worker Visa: 2026 Going Rates & Salary Thresholds",
                "body_markdown": "# UK Skilled Worker Salary Guide\nNavigating minimum salary requirements for international tech hires.",
                "meta_description": "Official 2026 salary threshold tables for UK Skilled Worker visa sponsorship.",
            },
        },
        post3_id: {
            "en": {
                "id": "t3-en",
                "post_id": post3_id,
                "locale": "en",
                "title": "Unreleased Draft Report",
                "body_markdown": "# Draft Content",
                "meta_description": "Draft",
            },
        },
    }

    set_mock_posts_store(posts_store, translations_store)

    yield

    try:
        limiter.reset()
    except Exception:
        pass
    clear_all_caches()
    clear_mock_stores()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Supported Locales Endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_locales_endpoint():
    """Verify GET /api/v1/locales returns all 4 supported languages with RTL flags."""
    res = client.get("/api/v1/locales")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 4

    locales_map = {l["code"]: l for l in data}
    assert "en" in locales_map
    assert "es" in locales_map
    assert "pt" in locales_map
    assert "ar" in locales_map

    # Arabic must be RTL
    assert locales_map["ar"]["is_rtl"] is True
    assert locales_map["ar"]["native_label"] == "العربية"

    # English is default
    assert locales_map["en"]["default"] is True
    assert locales_map["en"]["is_rtl"] is False

    # Spanish and Portuguese
    assert locales_map["es"]["native_label"] == "Español"
    assert locales_map["pt"]["native_label"] == "Português"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Localized Reference Data & Fallback
# ─────────────────────────────────────────────────────────────────────────────

def test_localized_countries_endpoint():
    """Verify /api/v1/countries?locale= returns translated labels with English fallback."""
    # 1. Spanish
    res_es = client.get("/api/v1/countries?locale=es")
    assert res_es.status_code == 200
    c_map_es = {c["slug"]: c for c in res_es.json()}
    assert c_map_es["germany"]["label"] == "Alemania"
    assert c_map_es["germany"]["is_fallback"] is False
    assert c_map_es["united-kingdom"]["label"] == "Reino Unido"

    # 2. Portuguese
    res_pt = client.get("/api/v1/countries?locale=pt")
    assert res_pt.status_code == 200
    c_map_pt = {c["slug"]: c for c in res_pt.json()}
    assert c_map_pt["germany"]["label"] == "Alemanha"
    assert c_map_pt["germany"]["is_fallback"] is False

    # 3. Arabic
    res_ar = client.get("/api/v1/countries?locale=ar")
    assert res_ar.status_code == 200
    c_map_ar = {c["slug"]: c for c in res_ar.json()}
    assert c_map_ar["germany"]["label"] == "ألمانيا"
    assert c_map_ar["germany"]["is_fallback"] is False
    assert c_map_ar["united-states"]["label"] == "الولايات المتحدة"

    # 4. Unsupported locale code 'xx' -> gracefully falls back to English with is_fallback: True
    res_xx = client.get("/api/v1/countries?locale=xx")
    assert res_xx.status_code == 200
    c_map_xx = {c["slug"]: c for c in res_xx.json()}
    assert c_map_xx["germany"]["label"] == "Germany"
    assert c_map_xx["germany"]["is_fallback"] is True


def test_localized_visa_types_endpoint():
    """Verify /api/v1/visa-types?locale= returns translated visa names with fallback."""
    res_ar = client.get("/api/v1/visa-types?locale=ar")
    assert res_ar.status_code == 200
    v_map_ar = {v["slug"]: v for v in res_ar.json()}
    assert v_map_ar["eu-blue-card"]["label"] == "البطاقة الزرقاء للاتحاد الأوروبي"
    assert v_map_ar["eu-blue-card"]["is_fallback"] is False
    assert v_map_ar["skilled-worker"]["label"] == "تأشيرة العامل الماهر"

    # Fallback test
    res_xx = client.get("/api/v1/visa-types?locale=xx")
    assert res_xx.status_code == 200
    v_map_xx = {v["slug"]: v for v in res_xx.json()}
    assert v_map_xx["eu-blue-card"]["label"] == "EU Blue Card"
    assert v_map_xx["eu-blue-card"]["is_fallback"] is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. Posts Listing & Detail with Locale Fallback
# ─────────────────────────────────────────────────────────────────────────────

def test_posts_listing_with_translated_and_fallback_items():
    """
    Verify GET /api/v1/posts:
    - Post 1 has Spanish translation -> is_fallback: False
    - Post 2 is English-only -> returns English canonical content with is_fallback: True
    - Post 3 is draft -> excluded from public listing
    """
    res = client.get("/api/v1/posts?locale=es")
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] == 2

    post_map = {p["slug"]: p for p in data["results"]}
    assert "draft-unreleased-immigration-report" not in post_map

    # Post 1 (translated in Spanish)
    p1 = post_map["germany-opportunity-card-chancenkarte-guide"]
    assert "Tarjeta de Oportunidad" in p1["title"]
    assert p1["locale"] == "es"
    assert p1["is_fallback"] is False

    # Post 2 (English only)
    p2 = post_map["uk-skilled-worker-salary-thresholds"]
    assert "UK Skilled Worker" in p2["title"]
    assert p2["locale"] == "en"
    assert p2["is_fallback"] is True

    # Category filter
    res_cat = client.get("/api/v1/posts?category=policy-radar&locale=en")
    assert res_cat.status_code == 200
    assert res_cat.json()["total_count"] == 1
    assert res_cat.json()["results"][0]["category"] == "policy-radar"

    # Pagination
    res_page = client.get("/api/v1/posts?page=1&page_size=1")
    assert res_page.status_code == 200
    assert len(res_page.json()["results"]) == 1
    assert res_page.json()["total_count"] == 2


def test_post_detail_fallback_and_arabic_rendering():
    """Verify GET /api/v1/posts/{slug} renders Arabic translation or falls back gracefully."""
    # 1. Post 1 in Arabic (Translated)
    res_ar = client.get("/api/v1/posts/germany-opportunity-card-chancenkarte-guide?locale=ar")
    assert res_ar.status_code == 200
    data_ar = res_ar.json()
    assert "بطاقة الفرص الألمانية" in data_ar["title"]
    assert "دليل بطاقة الفرص الألمانية" in data_ar["body_markdown"]
    assert data_ar["locale"] == "ar"
    assert data_ar["is_fallback"] is False
    assert set(data_ar["available_locales"]) == {"en", "es", "ar"}

    # 2. Post 2 in Arabic (Untranslated -> English fallback)
    res_fallback = client.get("/api/v1/posts/uk-skilled-worker-salary-thresholds?locale=ar")
    assert res_fallback.status_code == 200
    data_fb = res_fallback.json()
    assert "UK Skilled Worker Visa" in data_fb["title"]
    assert data_fb["locale"] == "en"
    assert data_fb["is_fallback"] is True

    # 3. Post in unsupported locale 'xx' -> English fallback
    res_xx = client.get("/api/v1/posts/germany-opportunity-card-chancenkarte-guide?locale=xx")
    assert res_xx.status_code == 200
    assert res_xx.json()["is_fallback"] is True
    assert "Germany Opportunity Card" in res_xx.json()["title"]

    # 4. Draft post detail -> 404 for public
    res_draft = client.get("/api/v1/posts/draft-unreleased-immigration-report")
    assert res_draft.status_code == 404

    # 5. Non-existent post -> 404
    res_404 = client.get("/api/v1/posts/non-existent-blog-slug")
    assert res_404.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 4. Admin Post Management & Auth Boundary Tests
# ─────────────────────────────────────────────────────────────────────────────

def test_admin_post_endpoints_auth_boundary():
    """
    Verify strict 3-state auth boundary on POST/PUT /api/v1/admin/posts:
    1. Zero auth -> 401 Unauthorized
    2. Non-admin auth -> 403 Forbidden
    3. Admin auth -> 200/201 Success
    """
    create_payload = {
        "slug": "netherlands-30-percent-ruling-update-2026",
        "category": "policy-radar",
        "author": "VisaLane Tax & Legal Team",
        "canonical_locale": "en",
        "status": "published",
        "translations": [
            {
                "locale": "en",
                "title": "Netherlands 30% Tax Ruling 2026 Updates",
                "body_markdown": "# 30% Ruling Overview\nKey changes for expat tax exemptions in the Netherlands.",
                "meta_description": "Analysis of the Dutch 30 percent ruling amendments.",
            },
            {
                "locale": "es",
                "title": "Actualizaciones de la Regla del 30% en Países Bajos 2026",
                "body_markdown": "# Resumen de la Regla del 30%\nCambios clave para expatriados en los Países Bajos.",
                "meta_description": "Análisis de las modificaciones de la regla del 30 por ciento.",
            },
        ],
    }

    # State 1: Zero auth -> 401
    res_no_auth = client.post("/api/v1/admin/posts", json=create_payload)
    assert res_no_auth.status_code == 401

    # Empty token -> 401
    res_empty_auth = client.post(
        "/api/v1/admin/posts",
        json=create_payload,
        headers={"Authorization": "Bearer   "},
    )
    assert res_empty_auth.status_code == 401

    # State 2: Non-admin auth -> 403
    res_user_auth = client.post(
        "/api/v1/admin/posts",
        json=create_payload,
        headers={"Authorization": "Bearer regular-user-token"},
    )
    assert res_user_auth.status_code == 403

    # State 3: Admin auth via X-Admin-Key -> 201 Created
    res_admin_key = client.post(
        "/api/v1/admin/posts",
        json=create_payload,
        headers={"X-Admin-Key": ADMIN_SECRET_KEY},
    )
    assert res_admin_key.status_code == 201
    created_post = res_admin_key.json()
    assert created_post["slug"] == "netherlands-30-percent-ruling-update-2026"
    assert created_post["title"] == "Netherlands 30% Tax Ruling 2026 Updates"

    # State 3b: Admin auth via Bearer admin token -> 200 OK update
    update_payload = {
        "author": "Senior Tax Partner",
        "category": "guide",
        "status": "published",
        "featured_image_url": "https://img.visalane.com/nl30.jpg",
        "translations": [
            {
                "locale": "pt",
                "title": "Regra fiscal dos 30% na Holanda 2026",
                "body_markdown": "# Visão Geral dos 30%\nMudanças para expatriados.",
                "meta_description": "Guia em português da regra fiscal holandesa.",
            }
        ],
    }
    res_update = client.put(
        "/api/v1/admin/posts/netherlands-30-percent-ruling-update-2026",
        json=update_payload,
        headers={"Authorization": "Bearer admin-token-secret"},
    )
    assert res_update.status_code == 200
    updated_post = res_update.json()
    assert updated_post["author"] == "Senior Tax Partner"
    assert updated_post["category"] == "guide"
    assert "pt" in updated_post["available_locales"]

    # Public retrieval check in Portuguese
    pub_res = client.get("/api/v1/posts/netherlands-30-percent-ruling-update-2026?locale=pt")
    assert pub_res.status_code == 200
    assert pub_res.json()["title"] == "Regra fiscal dos 30% na Holanda 2026"
    assert pub_res.json()["is_fallback"] is False

    # Update non-existent post -> 404
    res_up_404 = client.put(
        "/api/v1/admin/posts/non-existent-post-id",
        json={"author": "No Body"},
        headers={"X-Admin-Key": ADMIN_SECRET_KEY},
    )
    assert res_up_404.status_code == 404


def test_job_posting_json_ld_edge_cases():
    """Verify schema.org JSON-LD edge cases (equal min/max salary, validThrough, etc.)."""
    detail = JobDetail(
        id="99999999-9999-9999-9999-999999999999",
        slug="fixed-salary-role",
        title="Lead Architect",
        description="Lead role description.",
        hiring_organization=CompanySummary(name="ArchCorp", website="https://arch.com", logo_url="https://img.logo/arch.png"),
        date_posted="2026-09-01T08:00:00Z",
        valid_through="2026-12-31T23:59:59Z",
        base_salary=BaseSalary(currency="EUR", value=SalaryValue(min=100000, max=100000, unit_text="YEAR")),
        job_status="Open",
        apply_url="https://arch.com/apply",
    )
    json_ld = to_job_posting_json_ld(detail)
    assert json_ld["baseSalary"]["value"]["value"] == 100000
    assert json_ld["validThrough"] == "2026-12-31T23:59:59Z"


def test_supabase_client_mock_branches():
    """Test Supabase fallback branches when client is present."""
    mock_supabase = MagicMock()
    mock_user_res = MagicMock()
    mock_user = MagicMock()
    mock_user.role = "admin"
    mock_user.id = "admin-uuid"
    mock_user.user_metadata = {"is_admin": True}
    mock_user_res.user = mock_user
    mock_supabase.auth.get_user.return_value = mock_user_res

    with patch("engine.api.jobs_routes._get_supabase_client", return_value=mock_supabase):
        # Admin auth with supabase token
        create_payload = {
            "slug": "supabase-test-post",
            "category": "guide",
            "translations": [{"locale": "en", "title": "Supabase Guide", "body_markdown": "Body"}],
        }
        res = client.post(
            "/api/v1/admin/posts",
            json=create_payload,
            headers={"Authorization": "Bearer supabase_token_abc"},
        )
        assert res.status_code == 201
