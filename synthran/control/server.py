"""Line-delimited JSON service for SynthRAN control without provider mutation."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Mapping, TextIO

from synthran.app import ApplicationController
from synthran.control.protocol import (
    CONTROL_VERSION,
    LOCAL_WRITE_METHODS,
    PROVIDER_READ_METHODS,
    SUPPORTED_METHODS,
    error_response,
    parse_request,
    success_response,
)
from synthran.resources.live_inventory import read_resource_inventory, resource_inventory_view
from synthran.workspace.access import Runner, ensure_slices_project_access, subprocess_runner
from synthran.workspace.context import resolve_workspace_authority
from synthran.workspace.desired import ExperimentDesiredState, RadioDesiredState
from synthran.workspace.model import AccessRecord, WorkspaceError, utc_now, validate_safe_name
from synthran.workspace.provider_experiments import (
    PROVIDER_READ_TIMEOUT_SECONDS,
    discover_slices_experiments,
    verified_slices_experiment,
)
from synthran.workspace.store import bind_slices_experiment, load_access_record


class ControlInputError(ValueError):
    """Validated client input that cannot be applied to local state."""


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


def _desired_experiment(params: Mapping[str, object]) -> tuple[ExperimentDesiredState, str | None]:
    allowed = {"intent", "radio_mode", "label"}
    if set(params) - allowed:
        raise ControlInputError("experiment.create contains unsupported fields")

    intent = params.get("intent", "iot-to-5g")
    radio_mode = params.get("radio_mode", "virtual")
    label = params.get("label")
    if not isinstance(intent, str):
        raise ControlInputError("experiment intent must be text")
    if not isinstance(radio_mode, str):
        raise ControlInputError("experiment radio mode must be text")
    if label is not None:
        if not isinstance(label, str):
            raise ControlInputError("experiment label must be text or null")
        if not label.strip() or len(label) > 120:
            raise ControlInputError(
                "experiment label must contain 1-120 visible characters"
            )

    radios = {
        "automatic": RadioDesiredState(),
        "virtual": RadioDesiredState(mode="virtual", backend="rfsim"),
        "physical": RadioDesiredState(mode="physical", backend="r2lab"),
    }
    radio = radios.get(radio_mode)
    if radio is None:
        raise ControlInputError("experiment radio mode is unsupported")

    try:
        desired = replace(ExperimentDesiredState.recommended(intent=intent), radio=radio)
    except WorkspaceError as exc:
        raise ControlInputError(str(exc)) from exc
    return desired, label


def _provider_name(params: Mapping[str, object]) -> str:
    if set(params) != {"provider_experiment"}:
        raise ControlInputError(
            "experiment.bind_provider requires only provider_experiment"
        )
    value = params.get("provider_experiment")
    if not isinstance(value, str):
        raise ControlInputError("provider experiment must be text")
    try:
        return validate_safe_name(value, "SLICES experiment")
    except WorkspaceError as exc:
        raise ControlInputError(str(exc)) from exc


class ControlService:
    """Serve validated local state, provider reads, and local configuration writes."""

    def __init__(
        self,
        *,
        start: Path | None = None,
        environment: Mapping[str, str] | None = None,
        provider_runner: Runner = subprocess_runner,
        provider_timeout_seconds: int = PROVIDER_READ_TIMEOUT_SECONDS,
    ) -> None:
        self.start = start
        self.environment = dict(os.environ if environment is None else environment)
        self.provider_runner = provider_runner
        self.provider_timeout_seconds = provider_timeout_seconds

    def handshake(self) -> dict[str, object]:
        return {
            "service": "synthran-control",
            "protocol": CONTROL_VERSION,
            "local_writes": bool(LOCAL_WRITE_METHODS),
            "provider_reads": bool(PROVIDER_READ_METHODS),
            "provider_mutation": False,
            "methods": sorted(SUPPORTED_METHODS),
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

    def resource_snapshot(self, *, now: datetime | None = None) -> dict[str, object]:
        current = (now or utc_now()).astimezone(timezone.utc)
        inventory = read_resource_inventory(
            start=self.start,
            environment=self.environment,
            runner=self.provider_runner,
            timeout_seconds=self.provider_timeout_seconds,
            now=current,
        )
        return resource_inventory_view(inventory, now=current)

    def create_experiment(
        self,
        params: Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        desired, label = _desired_experiment(params)
        controller = ApplicationController(start=self.start, environment=self.environment)
        record = controller.create_experiment(
            desired=desired,
            label=label,
            slices_experiment=None,
            activate=True,
            now=now,
        )
        return {
            "experiment_id": record.experiment_id,
            "intent": record.network_intent,
            "radio_mode": record.radio_mode,
            "provider_experiment": None,
        }

    def _verify_project_context(self) -> object:
        authority = resolve_workspace_authority(
            start=self.start,
            environment=self.environment,
        )
        username = authority.profile.slices_username
        if username is None:
            raise WorkspaceError("selected profile has no SLICES username")
        ensure_slices_project_access(
            workspace_root=authority.root,
            username=username,
            project=authority.slices_project,
            force=True,
            runner=self.provider_runner,
            timeout_seconds=self.provider_timeout_seconds,
        )
        return authority

    def provider_experiments(self) -> dict[str, object]:
        self._verify_project_context()
        choices = discover_slices_experiments(
            runner=self.provider_runner,
            timeout_seconds=self.provider_timeout_seconds,
        )
        return {"experiments": [choice.name for choice in choices]}

    def bind_provider_experiment(self, params: Mapping[str, object]) -> dict[str, object]:
        provider_experiment = _provider_name(params)
        before = resolve_workspace_authority(
            start=self.start,
            environment=self.environment,
        )
        active = before.active_experiment
        if active is None:
            raise ControlInputError("create a local experiment before binding a provider experiment")
        if active.slices_experiment is not None and active.slices_experiment != provider_experiment:
            raise ControlInputError(
                "active experiment already has a different SLICES provider binding"
            )

        self._verify_project_context()
        verified_slices_experiment(
            provider_experiment,
            runner=self.provider_runner,
            timeout_seconds=self.provider_timeout_seconds,
        )

        after = resolve_workspace_authority(
            start=self.start,
            environment=self.environment,
        )
        if after.experiment_id != active.experiment_id:
            raise WorkspaceError("active experiment changed while provider binding was verified")
        if after.active_experiment is None:
            raise WorkspaceError("active experiment disappeared while provider binding was verified")
        if (
            after.active_experiment.slices_experiment is not None
            and after.active_experiment.slices_experiment != provider_experiment
        ):
            raise WorkspaceError("provider binding changed while verification was in progress")

        bound = bind_slices_experiment(
            after.root,
            after.active_experiment.experiment_id,
            provider_experiment,
        )
        return {
            "experiment_id": bound.experiment_id,
            "provider_experiment": bound.slices_experiment,
        }

    def handle(self, value: object) -> dict[str, object]:
        request_id: str | None = None
        try:
            request_id, method, params = parse_request(value)
            if method == "system.handshake":
                if params:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message="system.handshake does not accept params",
                    )
                return success_response(request_id, self.handshake())
            if method == "workspace.snapshot":
                if params:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message="workspace.snapshot does not accept params",
                    )
                return success_response(request_id, self.workspace_snapshot())
            if method == "resources.snapshot":
                if params:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message="resources.snapshot does not accept params",
                    )
                return success_response(request_id, self.resource_snapshot())
            if method == "experiment.create":
                try:
                    result = self.create_experiment(params)
                except ControlInputError as exc:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message=str(exc),
                    )
                return success_response(request_id, result)
            if method == "provider.experiments":
                if params:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message="provider.experiments does not accept params",
                    )
                return success_response(request_id, self.provider_experiments())
            if method == "experiment.bind_provider":
                try:
                    result = self.bind_provider_experiment(params)
                except ControlInputError as exc:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message=str(exc),
                    )
                return success_response(request_id, result)
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
