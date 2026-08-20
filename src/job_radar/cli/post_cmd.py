"""CLI entrypoint for LinkedIn Post generation and approval publishing."""
from __future__ import annotations

import argparse
import logging

from job_radar.social.generator import generate_and_dispatch_post
from job_radar.social.publisher import check_and_publish_post

logger = logging.getLogger("job_radar.social")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="LinkedIn Post Generation and Publishing")
    parser.add_argument(
        "action",
        choices=["generate", "publish", "check"],
        nargs="?",
        default="generate",
        help="Action to execute: generate draft or check/publish approved post",
    )
    args = parser.parse_args()

    if args.action == "generate":
        generate_and_dispatch_post()
    else:
        check_and_publish_post()


if __name__ == "__main__":
    main()
