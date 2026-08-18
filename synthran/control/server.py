"""Line-delimited JSON service exposing local SynthRAN state without mutation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Mapping, TextIO

from synthran.app import ApplicationController
from synthran.control.protocol import (
    CONTROL_VERSION,
    READ_ONLY_METHODS,
    error_response,
    parse_request,
    success_response,
)
from synthran.workspace.model import AccessRecord, WorkspaceError, utc_now
from synthran.workspace.store import load_access_record


def _access_summary(record: AccessRecord | None, *, now: datetime) -> dict[str, object]:
    if record is None:
        return {
            "verified": False,
            "fresh": False,
            "verified_at_utc": None,
            "refresh_after_utc": None,
            "access_until_utc": None,
        }
    return {
        "verified": True,
        "fresh": record.is_fresh(now),
        "verified_at_utc": record.verified_at_utc,
        "refresh_after_utc": record.refresh_after_utc,
        "access_until_utc": record.access_until_utc,
    }


class ControlService:
    """Serve read-only local state through a small versioned method set."""

    def __init__(
        self,
        *,
        start: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.start = start
        self.environment = dict(os.environ if environment is None else environment)

    def handshake(self) -> dict[str, object]:
        return {
            "service": "synthran-control",
            "protocol": CONTROL_VERSION,
            "read_only": True,
            "methods": sorted(READ_ONLY_METHODS),
        }

    def workspace_snapshot(self, *, now: datetime | None = None) -> dict[str, object]:
        current = (now or utc_now()).astimezone(timezone.utc)
        controller = ApplicationController(start=self.start, environment=self.environment)
        snapshot = controller.snapshot(now=current)
        authority = controller.authority

        slices_record = load_access_record(controller.root, "slices")
        r2lab_record = load_access_record(controller.root, "r2lab")
        identity_name = (
            authority.r2lab_identity.name
            if authority.r2lab_identity is not None
            else None
        )

        return {
            "workspace": {
                "profile": snapshot.profile,
                "project": snapshot.project,
                "reservation_minutes": authority.workspace.reservation_minutes,
                "placement": authority.workspace.placement,
            },
            "experiment": {
                "id": snapshot.experiment_id,
                "provider_experiment": snapshot.provider_experiment,
                "intent": snapshot.intent,
                "radio_mode": snapshot.radio_mode,
                "lifecycle": snapshot.lifecycle,
            },
            "access": {
                "slices": {
                    "configured": authority.profile.slices_username is not None,
                    "subject": authority.profile.slices_username,
                    **_access_summary(slices_record, now=current),
                },
                "r2lab": {
                    "configured": authority.r2lab_slice is not None,
                    "slice": authority.r2lab_slice,
                    "identity_name": identity_name,
                    **_access_summary(r2lab_record, now=current),
                },
            },
            "observations": [item.to_dict() for item in snapshot.observations],
            "next_steps": list(snapshot.next_steps),
            "blocks": list(snapshot.blocks),
        }

    def handle(self, value: object) -> dict[str, object]:
        request_id: str | None = None
        try:
            request_id, method, params = parse_request(value)
            if params:
                return error_response(
                    request_id,
                    code="invalid_params",
                    message="this read-only method does not accept params",
                )
            if method == "system.handshake":
                return success_response(request_id, self.handshake())
            if method == "workspace.snapshot":
                return success_response(request_id, self.workspace_snapshot())
            return error_response(
                request_id,
                code="method_not_found",
                message="control method is not supported",
            )
        except WorkspaceError as exc:
            return error_response(
                request_id,
                code="workspace_error",
                message=str(exc),
            )


def serve(
    service: ControlService,
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> None:
    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            response = error_response(
                None,
                code="invalid_json",
                message="control input must be valid JSON",
            )
        else:
            response = service.handle(value)
        output_stream.write(json.dumps(response, separators=(",", ":"), sort_keys=True))
        output_stream.write("\n")
        output_stream.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args(argv)
    serve(ControlService(start=args.workspace))
    return 0
