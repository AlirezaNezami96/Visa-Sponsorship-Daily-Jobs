"""Validation tests for .actor/actor.json metadata file."""
import json
from pathlib import Path


def test_actor_json_validity():
    actor_json_path = Path(".actor/actor.json")
    assert actor_json_path.exists(), ".actor/actor.json must exist"

    with open(actor_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data.get("actorSpecification") == 1
    assert data.get("name") == "visa-sponsorship-jobs-scraper"
    assert data.get("version") == "1.0"
    assert data.get("dockerContextDir") == ".."
    assert "pricing" not in data, "actor.json should not contain custom pricing block (configured in Console)"
    assert data.get("dockerfile") == "./Dockerfile"
    assert data.get("input") == "./input_schema.json"
    assert data.get("minMemoryMbytes") == 512
