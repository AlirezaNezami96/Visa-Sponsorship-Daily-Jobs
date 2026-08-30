#!/usr/bin/env python3
"""Check social media credentials via read-only ping endpoints without posting.

Usage:
  python scripts/check_social_credentials.py [--platform <x|bluesky|mastodon|linkedin|telegram|discord|devto|all>]

Exits with:
  0: All configured platforms passed validation (missing secrets are reported as NOT_CONFIGURED).
  1: One or more configured platforms failed credential validation.
"""
import argparse
import sys

from job_radar.social.adapters import ADAPTERS, get_adapter


def check_credentials_for_platform(platform: str) -> tuple[str, str, str]:
    adapter = get_adapter(platform)
    if not adapter:
        return platform, "UNKNOWN_PLATFORM", "No adapter found"

    ok, details = adapter.check_credentials()
    if details == "NOT_CONFIGURED":
        return platform, "NOT_CONFIGURED", "Secrets not set in environment"

    if ok:
        return platform, "OK", details
    return platform, "FAILED", details


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate social media publishing credentials via read-only pings.")
    parser.add_argument("--platform", default="all", choices=["all", "x", "bluesky", "mastodon", "linkedin", "telegram", "discord", "devto"])
    args = parser.parse_args(argv)

    platforms_to_check = list(ADAPTERS.keys()) if args.platform == "all" else [args.platform]

    print(f"\n{'='*70}")
    print(f"{'Platform':<12} | {'Status':<16} | {'Details'}")
    print(f"{'='*70}")

    has_failures = False

    for p in platforms_to_check:
        platform_name, status, details = check_credentials_for_platform(p)
        if status == "FAILED":
            has_failures = True
            badge = f"\033[91m{status:<16}\033[0m"
        elif status == "OK":
            badge = f"\033[92m{status:<16}\033[0m"
        else:
            badge = f"\033[93m{status:<16}\033[0m"

        print(f"{platform_name:<12} | {badge} | {details}")

    print(f"{'='*70}\n")

    if has_failures:
        print("❌ One or more configured platform credentials failed validation.")
        return 1

    print("✅ All configured platform credentials validated successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
