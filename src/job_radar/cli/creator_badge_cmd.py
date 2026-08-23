"""CLI entrypoint for Video Creator Badge Overlay Service."""
from __future__ import annotations

import argparse
import logging
import sys

from job_radar.creator_badge import (
    CreatorBadgeError,
    CreatorBadgeService,
    create_badge_preview,
    create_creator_badge_video,
    generate_video_preview,
)

logger = logging.getLogger("job_radar.creator_badge")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Overlay or replace personal creator badge on videos."
    )
    parser.add_argument(
        "input",
        help="Input video file path (or output path if using --badge-only)",
    )
    parser.add_argument(
        "output",
        nargs="?",
        help="Output video file path (required unless --badge-only with 1 arg)",
    )
    parser.add_argument(
        "--name",
        default="Alireza Nezami",
        help="Creator display name (default: 'Alireza Nezami')",
    )
    parser.add_argument(
        "--username",
        default="alireza-nezami",
        help="Creator username handle (default: 'alireza-nezami')",
    )
    parser.add_argument(
        "--profile-image",
        default=None,
        help="Custom profile image file path",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Process only first few seconds of video for fast preview",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=3.0,
        help="Preview duration in seconds when --preview is enabled (default: 3.0)",
    )
    parser.add_argument(
        "--badge-only",
        action="store_true",
        help="Generate only the transparent PNG badge preview without processing video",
    )
    parser.add_argument(
        "--target-res",
        default="1920x1080",
        help="Target reference resolution for --badge-only mode (e.g. '1920x1080', '1080x1920')",
    )
    parser.add_argument(
        "--no-cover",
        action="store_true",
        help="Do not cover existing watermarks/badges underneath the new badge",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Mode 1: Badge PNG Preview Only
    if args.badge_only:
        out_path = args.output or args.input
        try:
            parts = args.target_res.lower().split("x")
            w, h = int(parts[0]), int(parts[1])
            res = (w, h)
        except Exception:
            res = (1920, 1080)

        try:
            result = create_badge_preview(
                output_path=out_path,
                target_resolution=res,
                name=args.name,
                username=args.username,
                profile_image_path=args.profile_image,
            )
            print(f"✅ Generated creator badge preview PNG: {result}")
            return
        except CreatorBadgeError as err:
            logger.error("Failed to generate badge preview: %s", err)
            sys.exit(1)

    # Mode 2: Video Processing
    if not args.output:
        parser.error("Both input and output video paths are required when processing video.")

    try:
        if args.preview:
            result = generate_video_preview(
                input_path=args.input,
                output_path=args.output,
                duration=args.duration,
                name=args.name,
                username=args.username,
                profile_image_path=args.profile_image,
                remove_existing_badge=not args.no_cover,
            )
            print(f"✅ Generated {args.duration}s video preview with badge: {result}")
        else:
            result = create_creator_badge_video(
                input_path=args.input,
                output_path=args.output,
                name=args.name,
                username=args.username,
                profile_image_path=args.profile_image,
                remove_existing_badge=not args.no_cover,
            )
            print(f"✅ Successfully created badged video: {result}")

    except CreatorBadgeError as err:
        logger.error("Creator Badge processing failed: %s", err)
        sys.exit(1)
    except Exception as err:
        logger.exception("Unexpected error during video processing: %s", err)
        sys.exit(1)


if __name__ == "__main__":
    main()
