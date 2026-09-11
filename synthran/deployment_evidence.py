"""Validate fresh observed deployment evidence before state transitions."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from .deployment_state import bindings_match_deployment, content_hash, read_json


def _parse_observed_at(value: object) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("live deployment evidence has no observation timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("live deployment evidence has an invalid observation timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("live deployment evidence observation timestamp has no timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_live_evidence(
    candidate_path: str | Path,
    evidence_path: str | Path,
    *,
    max_age_seconds: int | None = 300,
) -> dict:
    """Require observed evidence for physical/R2Lab UE readiness.

    RFSIM currently retains its existing software-UE acceptance path. Physical
    and R2Lab deployments must provide complete live modem/session bindings and
    a fresh observation made after UE connection.
    """

    candidate = read_json(candidate_path)
    evidence = read_json(evidence_path)
    deployment = candidate.get("deployment", {})

    if candidate.get("deployment_hash") != content_hash(deployment):
        raise ValueError("candidate deployment identity failed its integrity check")
    if evidence.get("deployment_hash") != candidate.get("deployment_hash"):
        raise ValueError("live deployment evidence does not match the requested deployment")
    if evidence.get("cluster_identity_verified") is not True:
        raise ValueError("live deployment evidence does not prove the cluster identity")

    platform = deployment.get("platform")
    if platform in {"physical", "r2lab"}:
        bindings = evidence.get("bindings")
        if not isinstance(bindings, list) or not bindings_match_deployment(deployment, bindings):
            raise ValueError(
                "live deployment evidence does not contain complete matching UE bindings"
            )
        observed_at = _parse_observed_at(evidence.get("observed_at"))
        if max_age_seconds is not None:
            if max_age_seconds < 0:
                raise ValueError("maximum evidence age cannot be negative")
            age = (dt.datetime.now(dt.timezone.utc) - observed_at).total_seconds()
            if age < -30:
                raise ValueError("live deployment evidence is timestamped in the future")
            if age > max_age_seconds:
                raise ValueError(
                    f"live deployment evidence is stale ({age:.0f}s old; maximum {max_age_seconds}s)"
                )

    return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m synthran.deployment_evidence")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--max-age-seconds", type=int, default=300)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        validate_live_evidence(
            args.candidate,
            args.evidence,
            max_age_seconds=args.max_age_seconds,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
