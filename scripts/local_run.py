#!/usr/bin/env python3
"""
scripts/local_run.py

Local, billing-free dry run of the full Actor pipeline.

Runs the exact code path the Apify Actor uses (input_to_config -> run_pipeline)
but swaps the Apify dataset sink for an in-memory sink, so there is NO charging
and NO Apify account needed. Use it to exercise every input parameter before you
push to Apify.

Usage:
    python scripts/local_run.py --preset baseline
    python scripts/local_run.py --preset overseas-on --show 3
    python scripts/local_run.py --input my_input.json --output results.json

Presets (all the important scenarios):
    baseline          flag OFF — today's behavior, unchanged output shape
    overseas-on       flag ON — 20 overseas sources, defaults
    overseas-gulf     flag ON — only UAE/Qatar, government + manpower_agency
    overseas-open     flag ON — visaSponsorshipOnly=false (include unknowns)
    overseas-minconf  flag ON — minVisaConfidence=on_sponsor_list
                      (must EXCLUDE employer_sponsored_region jobs)
    overseas-details  flag ON — overseasFetchDetails=true
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from apify_actor.config_mapper import input_to_config  # noqa: E402
from job_radar.pipeline.orchestrator import run_pipeline  # noqa: E402
from job_radar.pipeline.sink import InMemoryJobSink  # noqa: E402

PRESETS: dict[str, dict] = {
    "baseline": {
        "keywords": ["engineer", "developer"],
        "countries": [],
        "visaSponsorshipOnly": True,
        "sources": ["greenhouse", "remoteok", "remotive"],
        "maxResults": 20,
        "maxRuntimeSecs": 300,
    },
    "overseas-on": {
        "enableOverseasSources": True,
        "overseasMaxSourcesPerRun": 20,
        "overseasBudgetSecs": 240,
        "visaSponsorshipOnly": True,
        "maxResults": 50,
        "maxRuntimeSecs": 300,
    },
    "overseas-gulf": {
        "enableOverseasSources": True,
        "overseasCategories": ["government", "manpower_agency"],
        "overseasDestinationCountries": ["UAE", "Qatar"],
        "overseasMaxSourcesPerRun": 20,
        "overseasBudgetSecs": 240,
        "visaSponsorshipOnly": True,
        "maxResults": 50,
        "maxRuntimeSecs": 300,
    },
    "overseas-open": {
        "enableOverseasSources": True,
        "overseasMaxSourcesPerRun": 15,
        "overseasBudgetSecs": 180,
        "visaSponsorshipOnly": False,
        "includeUnknownVisa": True,
        "maxResults": 50,
        "maxRuntimeSecs": 240,
    },
    "overseas-minconf": {
        "enableOverseasSources": True,
        "overseasMaxSourcesPerRun": 15,
        "overseasBudgetSecs": 180,
        "visaSponsorshipOnly": True,
        "minVisaConfidence": "on_sponsor_list",
        "maxResults": 50,
        "maxRuntimeSecs": 240,
    },
    "overseas-details": {
        "enableOverseasSources": True,
        "overseasMaxSourcesPerRun": 10,
        "overseasBudgetSecs": 180,
        "overseasFetchDetails": True,
        "overseasMaxDetailFetches": 50,
        "visaSponsorshipOnly": True,
        "maxResults": 30,
        "maxRuntimeSecs": 300,
    },
}


async def _run(actor_input: dict) -> tuple[list[dict], dict]:
    config = input_to_config(actor_input)
    sink = InMemoryJobSink()
    result = await asyncio.wait_for(run_pipeline(config, sink), timeout=float(config.max_runtime_secs))
    records = [j.to_apify_dict(include_description=config.include_description) for j in sink.jobs]
    return records, result.stats


def _print_report(records: list[dict], stats: dict, show: int, actor_input: dict) -> None:
    print("\n" + "=" * 70)
    print("INPUT:", json.dumps(actor_input, ensure_ascii=False))
    print("=" * 70)

    print("\nRUN_STATS:")
    for key in ("totalFetched", "totalFiltered", "totalDeduplicated",
                "uniqueSurvivingJobs", "simhashDuplicates", "visaPassedJobs",
                "visaEnrichedJobs", "totalEmitted", "durationSeconds"):
        print(f"  {key:20s}: {stats.get(key)}")
    fails = stats.get("failedSources") or []
    if fails:
        print(f"  failedSources       : {len(fails)}")
        for f in fails[:5]:
            print(f"    - {f}")

    print(f"\nEMITTED RECORDS: {len(records)}")
    if records:
        print("DATASET KEYS:", ", ".join(sorted(records[0].keys())))
        overseas = [r for r in records if r.get("source") == "overseas"]
        print(f"  overseas records    : {len(overseas)}")
        signals = {}
        for r in records:
            signals[r.get("visaSignal")] = signals.get(r.get("visaSignal"), 0) + 1
        print("  visaSignal breakdown:", signals)

        for r in records[:show]:
            print("\n-" * 30)
            print(json.dumps(r, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Local billing-free Actor run.")
    parser.add_argument("--preset", choices=sorted(PRESETS), help="Use a built-in scenario input.")
    parser.add_argument("--input", help="Path to an Apify-style input JSON file.")
    parser.add_argument("--show", type=int, default=2, help="Print first N records in full.")
    parser.add_argument("--output", help="Write all emitted records to this JSON file.")
    args = parser.parse_args()

    if args.input:
        actor_input = json.loads(Path(args.input).read_text(encoding="utf-8"))
    elif args.preset:
        actor_input = PRESETS[args.preset]
    else:
        parser.error("Pass --preset <name> or --input <file.json>")

    records, stats = asyncio.run(_run(actor_input))
    _print_report(records, stats, args.show, actor_input)

    if args.output:
        Path(args.output).write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote {len(records)} records to {args.output}")


if __name__ == "__main__":
    main()
