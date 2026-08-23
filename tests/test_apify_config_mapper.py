"""Tests for Apify input_to_config mapper."""
from apify_actor.config_mapper import input_to_config


def test_config_mapper_nested_sections():
    actor_input = {
        "searchCriteria": {
            "keywords": ["Kotlin", "Android"],
            "excludeKeywords": ["Lead"],
            "countries": ["Germany", "United Kingdom"],
            "remoteOnly": True,
        },
        "visaFilters": {
            "visaSponsorshipOnly": True,
            "includeUnknownVisa": True,
            "minVisaConfidence": "on_sponsor_list",
            "excludeExplicitNoSponsorship": True,
        },
        "sources": {
            "sources": ["greenhouse", "lever"],
            "companyUrls": ["https://boards.greenhouse.io/stripe"],
        },
        "jobFilters": {
            "seniorityLevels": ["junior", "mid"],
            "postedWithinDays": 14,
            "minSalary": 75000,
            "salaryCurrency": "EUR",
        },
        "aiClassification": {
            "enableAIClassification": True,
            "minimumRelevanceScore": 0.6,
            "maxAICalls": 150,
        },
        "outputOptions": {
            "maxResults": 100,
            "sortBy": "composite_score",
            "includeDescription": False,
        },
    }

    config = input_to_config(actor_input)

    assert config.keywords == ["Kotlin", "Android"]
    assert config.exclude_keywords == ["Lead"]
    assert config.countries == ["Germany", "United Kingdom"]
    assert config.remote_only is True
    assert config.visa_sponsorship_only is True
    assert config.include_unknown_visa is True
    assert config.min_visa_confidence == "on_sponsor_list"
    assert config.sources == ["greenhouse", "lever"]
    assert config.company_urls == ["https://boards.greenhouse.io/stripe"]
    assert config.posted_within_days == 14
    assert config.min_salary == 75000
    assert config.salary_currency == "EUR"
    assert config.enable_ai_classification is True
    assert config.max_ai_calls == 150
    assert config.max_results == 100
    assert config.include_description is False


def test_config_mapper_flat_input():
    actor_input = {
        "keywords": ["Machine Learning"],
        "remoteOnly": True,
        "includeUnknownVisa": False,
        "maxResults": 50,
        "enableAIClassification": False,
    }

    config = input_to_config(actor_input)

    assert config.keywords == ["Machine Learning"]
    assert config.remote_only is True
    assert config.include_unknown_visa is False
    assert config.max_results == 50
    assert config.enable_ai_classification is False
    assert config.posted_within_days == 30  # Default preserved
