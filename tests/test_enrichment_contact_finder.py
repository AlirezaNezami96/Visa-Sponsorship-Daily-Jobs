"""Unit tests for contact finder, scrapers, search links, and fallback instructions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from job_radar.enrichment.contact_finder import ContactFinder, build_fallback_instructions
from job_radar.enrichment.email_finder import extract_emails_from_text, find_emails_for_contact
from job_radar.enrichment.linkedin_finder import (
    build_linkedin_search_url,
    generate_company_recruiter_search_links,
)
from job_radar.enrichment.pattern_matcher import (
    generate_email_patterns,
    get_generic_company_emails,
)


def test_email_pattern_matcher():
    patterns = generate_email_patterns("John", "Doe", "acme.com")
    emails = [p["email"] for p in patterns]
    assert "john.doe@acme.com" in emails
    assert "j.doe@acme.com" in emails
    assert "johndoe@acme.com" in emails
    for p in patterns:
        assert p["email_status"] == "pattern_guess"
        assert p["confidence"] <= 30


def test_generic_company_emails():
    emails = get_generic_company_emails("https://techcorp.io/")
    assert "careers@techcorp.io" in emails
    assert "talent@techcorp.io" in emails
    assert "jobs@techcorp.io" in emails


def test_linkedin_search_urls():
    links = generate_company_recruiter_search_links("Acme Corp", "Backend Engineer")
    assert "recruiter_search" in links
    assert "talent_acquisition_search" in links
    assert "hiring_manager_search" in links
    assert "department_lead_search" in links
    assert "Acme%20Corp%20recruiter" in links["recruiter_search"] or "Acme+Corp+recruiter" in links["recruiter_search"]


def test_extract_emails_from_text():
    jd = "Please send questions to recruiting@company.com or contact our lead recruiter at alex.smith@company.com."
    found = extract_emails_from_text(jd)
    emails = {e["email"]: e for e in found}
    assert "recruiting@company.com" in emails
    assert emails["recruiting@company.com"]["email_status"] == "generic"
    assert "alex.smith@company.com" in emails
    assert emails["alex.smith@company.com"]["email_status"] == "verified"


def test_build_fallback_instructions_contains_all_four_steps():
    instructions = build_fallback_instructions(
        company_name="Stripe",
        company_domain="stripe.com",
        job_title="Staff Infrastructure Engineer",
        job_url="https://stripe.com/jobs/123",
    )
    assert len(instructions) == 4
    steps = [i["step"] for i in instructions]
    assert steps == [1, 2, 3, 4]
    assert "LinkedIn" in instructions[0]["title"]
    assert "Hiring Manager" in instructions[1]["title"]
    assert "Original Job Posting" in instructions[2]["title"]
    assert "Department Mailboxes" in instructions[3]["title"]


def test_contact_finder_orchestration():
    finder = ContactFinder()
    mock_html = """
    <html>
      <body>
        <div class="team-member">
          <h3>Alice Johnson</h3>
          <p class="role">Head of Talent</p>
        </div>
      </body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.text = mock_html

    with patch("requests.get", return_value=mock_resp):
        res = finder.find_contacts_for_job(
            job_id="job_555",
            company_name="Acme Tech",
            company_domain="acmetech.com",
            job_title="Senior Python Developer",
            job_description="Contact us at jobs@acmetech.com",
            job_url="https://acmetech.com/jobs/555",
        )

        assert res["success"] is True
        assert res["count"] >= 1
        assert len(res["fallback_instructions"]) == 4
        assert "recruiter_search" in res["search_links"]
