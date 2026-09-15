#!/usr/bin/env python3
"""Opt-in post-run S3 archival for a completed SynthRAN result directory."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from synthran.archive import archive_directory


def _git_revision() -> str:
    p = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    return p.stdout.strip() if p.returncode == 0 else "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="result directory to archive")
    parser.add_argument("--alias", default=os.getenv("SYNTHRAN_ARCHIVE_ALIAS"))
    parser.add_argument("--bucket", default=os.getenv("SYNTHRAN_ARCHIVE_BUCKET"))
    parser.add_argument("--prefix", default=os.getenv("SYNTHRAN_ARCHIVE_PREFIX"))
    parser.add_argument("--experiment")
    parser.add_argument("--campaign-id")
    parser.add_argument("--source-revision")
    parser.add_argument("--remote-suffix", default="result")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()

    root = args.path.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"result directory does not exist: {root}")
    if not args.alias or not args.bucket or not args.prefix:
        parser.error(
            "--alias, --bucket and --prefix are required "
            "(or set SYNTHRAN_ARCHIVE_ALIAS/BUCKET/PREFIX)"
        )

    campaign_path = root / "campaign.json"
    campaign = {}
    if campaign_path.is_file():
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        if campaign.get("status") not in {None, "complete"} and not args.allow_incomplete:
            parser.error("campaign is not complete; use --allow-incomplete only for an intentional checkpoint")
    experiment = args.experiment or campaign.get("experiment")
    campaign_id = args.campaign_id or campaign.get("campaign_id") or root.name
    source_revision = (
        args.source_revision
        or campaign.get("source_revision")
        or _git_revision()
    )
    if not experiment:
        parser.error("--experiment is required when campaign.json does not provide it")

    result = archive_directory(
        root,
        settings={
            "enabled": True,
            "backend": "s3",
            "alias": args.alias,
            "bucket": args.bucket,
            "prefix": args.prefix,
            "remote_verify": True,
        },
        experiment=str(experiment),
        campaign_id=str(campaign_id),
        archive_kind="result-directory",
        archive_id=root.name,
        phase="post-run",
        source_revision=str(source_revision),
        remote_suffix=args.remote_suffix,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
