"""Tests for overseas-expansion fields in the Apify input -> config mapper."""
from apify_actor.config_mapper import input_to_config


def test_defaults_preserve_current_behavior_flag_off():
    cfg = input_to_config({})
    assert cfg.enable_overseas_sources is False
    assert cfg.overseas_categories == [
        "government",
        "manpower_agency",
        "aggregator",
        "remote_board",
        "visa_specialist",
        "unknown_board",
    ]
    assert cfg.overseas_destination_countries == []
    assert cfg.overseas_max_sources_per_run == 150
    assert cfg.overseas_concurrency == 20
    assert cfg.overseas_fetch_details is False
    assert cfg.overseas_max_detail_fetches == 300
    assert cfg.overseas_simhash_dedup is True
    assert cfg.overseas_simhash_threshold == 6
    assert cfg.respect_robots_txt is True


def test_flag_off_on_empty_input():
    cfg = input_to_config(None)
    assert cfg.enable_overseas_sources is False


def test_section_dict_input():
    cfg = input_to_config({
        "maxRuntimeSecs": 3000,
        "overseasExpansion": {
            "enableOverseasSources": True,
            "overseasCategories": ["government", "manpower_agency"],
            "overseasDestinationCountries": ["UAE", "Qatar"],
            "overseasMaxSourcesPerRun": 40,
            "overseasConcurrency": 10,
            "overseasBudgetSecs": 900,
            "overseasFetchDetails": True,
            "overseasMaxDetailFetches": 100,
            "overseasSimhashDedup": False,
            "overseasSimhashThreshold": 8,
            "respectRobotsTxt": False,
        },
    })
    assert cfg.enable_overseas_sources is True
    assert cfg.overseas_categories == ["government", "manpower_agency"]
    assert cfg.overseas_destination_countries == ["UAE", "Qatar"]
    assert cfg.overseas_max_sources_per_run == 40
    assert cfg.overseas_concurrency == 10
    assert cfg.overseas_budget_secs == 900
    assert cfg.overseas_fetch_details is True
    assert cfg.overseas_max_detail_fetches == 100
    assert cfg.overseas_simhash_dedup is False
    assert cfg.overseas_simhash_threshold == 8
    assert cfg.respect_robots_txt is False


def test_flat_keys_input():
    cfg = input_to_config({
        "maxRuntimeSecs": 3000,
        "enableOverseasSources": True,
        "overseasCategories": "government,visa_specialist",
        "overseasBudgetSecs": 1200,
        "overseasConcurrency": 15,
    })
    assert cfg.enable_overseas_sources is True
    assert cfg.overseas_categories == ["government", "visa_specialist"]
    assert cfg.overseas_budget_secs == 1200
    assert cfg.overseas_concurrency == 15


def test_section_dict_beats_flat_keys():
    cfg = input_to_config({
        "maxRuntimeSecs": 3000,
        "enableOverseasSources": False,
        "overseasExpansion": {"enableOverseasSources": True},
    })
    assert cfg.enable_overseas_sources is True


def test_budget_clamped_to_eighty_percent_of_max_runtime():
    # maxRuntimeSecs=1000 -> cap 800
    cfg = input_to_config({"maxRuntimeSecs": 1000, "overseasBudgetSecs": 3000})
    assert cfg.overseas_budget_secs == 800


def test_budget_clamped_to_floor_of_60s():
    # maxRuntimeSecs=300 -> 0.8*300=240 < requested? no: requested default 600 -> 240.
    # Explicit tiny maxRuntime with explicit tiny budget clamps at the 60s floor.
    cfg = input_to_config({"maxRuntimeSecs": 60, "overseasBudgetSecs": 10})
    assert cfg.overseas_budget_secs == 60
    cfg = input_to_config({"maxRuntimeSecs": 300})
    assert cfg.overseas_budget_secs == 240


def test_concurrency_clamped():
    assert input_to_config({"overseasConcurrency": 1}).overseas_concurrency == 5
    assert input_to_config({"overseasConcurrency": 999}).overseas_concurrency == 40


def test_max_sources_clamped():
    assert input_to_config({"overseasMaxSourcesPerRun": 1}).overseas_max_sources_per_run == 10
    assert input_to_config({"overseasMaxSourcesPerRun": 99999}).overseas_max_sources_per_run == 573


def test_other_sections_still_map_with_overseas_present():
    cfg = input_to_config({
        "searchCriteria": {"keywords": ["welder"]},
        "overseasExpansion": {"enableOverseasSources": True},
    })
    assert cfg.keywords == ["welder"]
    assert cfg.enable_overseas_sources is True
