"""Line-delimited JSON service for the SynthRAN workbench."""

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
from synthran.control.live_operations import refresh_slices_control_state
from synthran.control.operation_api import (
    OperationInputError,
    approve_operation,
    cancel_operation,
    execute_operation,
    inspect_operation_action,
    plan_operation,
    read_operation,
)
from synthran.control.protocol import (
    CONTROL_VERSION,
    LOCAL_WRITE_METHODS,
    PROVIDER_MUTATION_METHODS,
    PROVIDER_READ_METHODS,
    SUPPORTED_METHODS,
    error_response,
    parse_request,
    success_response,
)
from synthran.operations.journal import active_mutation_path
from synthran.resources.catalog import reviewed_resource_descriptors
from synthran.workspace.access import (
    Runner,
    ensure_slices_project_access,
    probe_slices_project_access,
    subprocess_runner,
)
from synthran.workspace.configuration import (
    available_profiles,
    configuration_root,
    first_use_snapshot,
    resolve_ssh_identity_reference,
    switch_workspace_profile,
    update_workspace_defaults,
)
from synthran.workspace.context import resolve_workspace_authority
from synthran.workspace.desired import (
    ExperimentDesiredState,
    PlacementDesiredState,
    RadioDesiredState,
)
from synthran.workspace.desired_store import load_desired_state
from synthran.workspace.initialization import InitializationRequest, initialize_controller_workspace
from synthran.workspace.model import (
    AccessRecord,
    WorkspaceError,
    utc_now,
    validate_profile_name,
    validate_safe_name,
)
from synthran.workspace.provider_experiments import (
    PROVIDER_READ_TIMEOUT_SECONDS,
    discover_slices_experiments,
    verified_slices_experiment,
)
from synthran.workspace.store import (
    access_path,
    bind_slices_experiment,
    load_access_record,
    load_profile,
    save_access_record,
    verify_profile_identity,
)


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


def _desired_experiment(
    params: Mapping[str, object],
) -> tuple[ExperimentDesiredState, str | None]:
    allowed = {
        "intent",
        "radio_mode",
        "label",
        "placement",
        "core_node",
        "ran_node",
    }
    if set(params) - allowed:
        raise ControlInputError("experiment.create contains unsupported fields")

    intent = params.get("intent", "iot-to-5g")
    radio_mode = params.get("radio_mode", "virtual")
    placement_mode = params.get("placement", "automatic")
    core_node = params.get("core_node")
    ran_node = params.get("ran_node")
    label = params.get("label")
    if not isinstance(intent, str):
        raise ControlInputError("experiment intent must be text")
    if not isinstance(radio_mode, str):
        raise ControlInputError("experiment radio mode must be text")
    if not isinstance(placement_mode, str):
        raise ControlInputError("experiment placement must be text")
    if core_node is not None and not isinstance(core_node, str):
        raise ControlInputError("core node must be text or null")
    if ran_node is not None and not isinstance(ran_node, str):
        raise ControlInputError("RAN node must be text or null")
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

    if placement_mode == "automatic":
        if core_node is not None or ran_node is not None:
            raise ControlInputError("automatic placement cannot pin core or RAN nodes")
        placement = PlacementDesiredState(mode="automatic")
    elif placement_mode == "manual":
        if core_node is None or ran_node is None:
            raise ControlInputError("manual placement requires core and RAN nodes")
        if core_node == ran_node:
            raise ControlInputError("core and RAN nodes must be different")
        try:
            placement = PlacementDesiredState(
                mode="manual",
                core_node=core_node,
                ran_node=ran_node,
            )
        except WorkspaceError as exc:
            raise ControlInputError(str(exc)) from exc
    else:
        raise ControlInputError("experiment placement must be automatic or manual")

    try:
        desired = replace(
            ExperimentDesiredState.recommended(intent=intent),
            radio=radio,
            placement=placement,
        )
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


def _profile_name(params: Mapping[str, object]) -> str:
    if set(params) != {"profile_name"}:
        raise ControlInputError("workspace.switch_profile requires only profile_name")
    value = params.get("profile_name")
    if not isinstance(value, str):
        raise ControlInputError("profile name must be text")
    try:
        return validate_profile_name(value)
    except WorkspaceError as exc:
        raise ControlInputError(str(exc)) from exc


def _initialization_request(
    params: Mapping[str, object],
    *,
    root: Path,
    environment: Mapping[str, str],
) -> InitializationRequest:
    allowed = {
        "profile_name",
        "project",
        "reuse_profile",
        "slices_username",
        "r2lab_slice",
        "r2lab_identity",
        "reservation_minutes",
        "placement",
    }
    if set(params) - allowed:
        raise ControlInputError("workspace.initialize contains unsupported fields")

    profile_name = params.get("profile_name", "default")
    project = params.get("project")
    reuse_profile = params.get("reuse_profile", False)
    slices_username = params.get("slices_username")
    r2lab_slice = params.get("r2lab_slice")
    r2lab_identity = params.get("r2lab_identity")
    reservation_minutes = params.get("reservation_minutes", 120)
    placement = params.get("placement", "automatic")

    if not isinstance(profile_name, str):
        raise ControlInputError("profile name must be text")
    if not isinstance(project, str):
        raise ControlInputError("SLICES project must be text")
    if not isinstance(reuse_profile, bool):
        raise ControlInputError("reuse_profile must be boolean")
    if slices_username is not None and not isinstance(slices_username, str):
        raise ControlInputError("SLICES username must be text or null")
    if r2lab_slice is not None and not isinstance(r2lab_slice, str):
        raise ControlInputError("R2Lab slice must be text or null")
    if r2lab_identity is not None and not isinstance(r2lab_identity, str):
        raise ControlInputError("R2Lab identity must be text or null")
    if not isinstance(reservation_minutes, int) or isinstance(
        reservation_minutes, bool
    ):
        raise ControlInputError("reservation duration must be an integer")
    if not isinstance(placement, str):
        raise ControlInputError("placement must be text")

    try:
        return InitializationRequest(
            root=root,
            project=project,
            profile_name=profile_name,
            slices_username=slices_username,
            r2lab_slice=r2lab_slice,
            r2lab_identity=(
                resolve_ssh_identity_reference(r2lab_identity, environment)
                if r2lab_identity is not None
                else None
            ),
            reservation_minutes=reservation_minutes,
            placement=placement,
            reuse_profile=reuse_profile,
        )
    except WorkspaceError as exc:
        raise ControlInputError(str(exc)) from exc


def _workspace_defaults(params: Mapping[str, object]) -> tuple[int, str]:
    if set(params) != {"reservation_minutes", "placement"}:
        raise ControlInputError(
            "workspace.update_defaults requires reservation_minutes and placement"
        )
    reservation_minutes = params.get("reservation_minutes")
    placement = params.get("placement")
    if not isinstance(reservation_minutes, int) or isinstance(
        reservation_minutes, bool
    ):
        raise ControlInputError("reservation duration must be an integer")
    if not isinstance(placement, str):
        raise ControlInputError("placement must be text")
    if reservation_minutes < 10 or reservation_minutes > 1440:
        raise ControlInputError(
            "reservation duration must be between 10 and 1440 minutes"
        )
    if placement not in {"automatic", "manual"}:
        raise ControlInputError("placement must be automatic or manual")
    return reservation_minutes, placement


class ControlService:
    """Serve validated local state, provider reads, and approved live actions."""

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
            "provider_mutation": bool(PROVIDER_MUTATION_METHODS),
            "methods": sorted(SUPPORTED_METHODS),
        }

    def setup_inspect(self) -> dict[str, object]:
        return first_use_snapshot(start=self.start, environment=self.environment)

    def initialize_workspace(
        self,
        params: Mapping[str, object],
    ) -> dict[str, object]:
        root = configuration_root(self.start)
        request = _initialization_request(
            params,
            root=root,
            environment=self.environment,
        )
        result = initialize_controller_workspace(
            request,
            environment=self.environment,
            slices_runner=self.provider_runner,
            r2lab_runner=self.provider_runner,
            timeout_seconds=self.provider_timeout_seconds,
        )
        return {
            "profile": result.workspace.profile,
            "project": result.workspace.project,
            "reservation_minutes": result.workspace.reservation_minutes,
            "placement": result.workspace.placement,
            "r2lab_configured": result.r2lab_access is not None,
        }

    def workspace_snapshot(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        current = (now or utc_now()).astimezone(timezone.utc)
        controller = ApplicationController(
            start=self.start,
            environment=self.environment,
        )
        snapshot = controller.snapshot(now=current)
        authority = controller.authority

        slices_record = load_access_record(controller.root, "slices")
        if slices_record is not None and (
            slices_record.subject != authority.profile.slices_username
            or slices_record.scope != authority.slices_project
        ):
            slices_record = None
        r2lab_record = load_access_record(controller.root, "r2lab")
        if r2lab_record is not None and (
            r2lab_record.subject != authority.r2lab_slice
            or r2lab_record.scope != "faraday.inria.fr"
            or r2lab_record.identity_fingerprint
            != authority.r2lab_identity_fingerprint
        ):
            r2lab_record = None
        identity_name = (
            authority.r2lab_identity.name
            if authority.r2lab_identity is not None
            else None
        )

        placement_mode: str | None = None
        core_node: str | None = None
        ran_node: str | None = None
        if authority.active_experiment is not None:
            desired = load_desired_state(
                controller.root,
                authority.active_experiment.experiment_id,
            )
            placement_mode = desired.placement.mode
            core_node = desired.placement.core_node
            ran_node = desired.placement.ran_node

        compute_nodes = sorted(
            descriptor.resource_id
            for descriptor in reviewed_resource_descriptors()
            if descriptor.provider == "slices" and descriptor.kind == "compute"
        )

        return {
            "workspace": {
                "profile": snapshot.profile,
                "project": snapshot.project,
                "reservation_minutes": authority.workspace.reservation_minutes,
                "placement": authority.workspace.placement,
            },
            "profiles": [
                item.to_dict() for item in available_profiles(self.environment)
            ],
            "compute_nodes": compute_nodes,
            "experiment": {
                "id": snapshot.experiment_id,
                "provider_experiment": snapshot.provider_experiment,
                "intent": snapshot.intent,
                "radio_mode": snapshot.radio_mode,
                "placement_mode": placement_mode,
                "core_node": core_node,
                "ran_node": ran_node,
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

    def update_defaults(self, params: Mapping[str, object]) -> dict[str, object]:
        reservation_minutes, placement = _workspace_defaults(params)
        authority = resolve_workspace_authority(
            start=self.start,
            environment=self.environment,
        )
        updated = update_workspace_defaults(
            authority.root,
            reservation_minutes=reservation_minutes,
            placement=placement,
        )
        return {
            "reservation_minutes": updated.reservation_minutes,
            "placement": updated.placement,
        }

    def switch_profile(self, params: Mapping[str, object]) -> dict[str, object]:
        profile_name = _profile_name(params)
        before = resolve_workspace_authority(
            start=self.start,
            environment=self.environment,
        )
        if before.profile.name == profile_name:
            return {"profile": profile_name, "project": before.slices_project}
        if active_mutation_path(before.root).exists():
            raise ControlInputError("cannot switch profile while a provider change is active")

        if before.active_experiment is not None:
            snapshot = ApplicationController(
                start=before.root,
                environment=self.environment,
            ).snapshot()
            if (
                before.active_experiment.slices_experiment is not None
                or snapshot.lifecycle != "CONFIGURED"
            ):
                raise ControlInputError(
                    "switch profile before binding or starting the active network configuration"
                )

        try:
            target = load_profile(profile_name, environment=self.environment)
            verify_profile_identity(target)
        except WorkspaceError as exc:
            raise ControlInputError(str(exc)) from exc
        if target.slices_username is None:
            raise ControlInputError("selected profile has no SLICES username")

        verified = probe_slices_project_access(
            username=target.slices_username,
            project=before.slices_project,
            runner=self.provider_runner,
            timeout_seconds=self.provider_timeout_seconds,
        )
        updated = switch_workspace_profile(
            before.root,
            profile_name=profile_name,
        )
        save_access_record(before.root, verified)
        access_path(before.root, "r2lab").unlink(missing_ok=True)
        return {"profile": updated.profile, "project": updated.project}

    def create_experiment(
        self,
        params: Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        desired, label = _desired_experiment(params)
        controller = ApplicationController(
            start=self.start,
            environment=self.environment,
        )
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
            "placement": desired.placement.mode,
            "core_node": desired.placement.core_node,
            "ran_node": desired.placement.ran_node,
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

    def bind_provider_experiment(
        self,
        params: Mapping[str, object],
    ) -> dict[str, object]:
        provider_experiment = _provider_name(params)
        before = resolve_workspace_authority(
            start=self.start,
            environment=self.environment,
        )
        active = before.active_experiment
        if active is None:
            raise ControlInputError(
                "create a local experiment before binding a provider experiment"
            )
        if (
            active.slices_experiment is not None
            and active.slices_experiment != provider_experiment
        ):
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
            raise WorkspaceError(
                "active experiment changed while provider binding was verified"
            )
        if after.active_experiment is None:
            raise WorkspaceError(
                "active experiment disappeared while provider binding was verified"
            )
        if (
            after.active_experiment.slices_experiment is not None
            and after.active_experiment.slices_experiment != provider_experiment
        ):
            raise WorkspaceError(
                "provider binding changed while verification was in progress"
            )

        bound = bind_slices_experiment(
            after.root,
            after.active_experiment.experiment_id,
            provider_experiment,
        )
        return {
            "experiment_id": bound.experiment_id,
            "provider_experiment": bound.slices_experiment,
        }

    def _operation_inventory(self) -> object:
        return refresh_slices_control_state(
            start=self.start,
            environment=self.environment,
            runner=self.provider_runner,
        )

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
            if method == "setup.inspect":
                if params:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message="setup.inspect does not accept params",
                    )
                return success_response(request_id, self.setup_inspect())
            if method == "workspace.initialize":
                try:
                    result = self.initialize_workspace(params)
                except ControlInputError as exc:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message=str(exc),
                    )
                return success_response(request_id, result)
            if method == "workspace.snapshot":
                if params:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message="workspace.snapshot does not accept params",
                    )
                return success_response(request_id, self.workspace_snapshot())
            if method == "workspace.update_defaults":
                try:
                    result = self.update_defaults(params)
                except ControlInputError as exc:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message=str(exc),
                    )
                return success_response(request_id, result)
            if method == "workspace.switch_profile":
                try:
                    result = self.switch_profile(params)
                except ControlInputError as exc:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message=str(exc),
                    )
                return success_response(request_id, result)
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
                return success_response(
                    request_id,
                    self.provider_experiments(),
                )
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
            if method == "operation.inspect":
                try:
                    inventory = self._operation_inventory()
                    result = inspect_operation_action(
                        start=self.start,
                        environment=self.environment,
                        params=params,
                        inventory=inventory,
                    )
                except OperationInputError as exc:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message=str(exc),
                    )
                return success_response(request_id, result)
            if method == "operation.plan":
                try:
                    inventory = self._operation_inventory()
                    result = plan_operation(
                        start=self.start,
                        environment=self.environment,
                        params=params,
                        inventory=inventory,
                    )
                except OperationInputError as exc:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message=str(exc),
                    )
                return success_response(request_id, result)
            if method == "operation.read":
                try:
                    result = read_operation(
                        start=self.start,
                        environment=self.environment,
                        params=params,
                    )
                except OperationInputError as exc:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message=str(exc),
                    )
                return success_response(request_id, result)
            if method == "operation.approve":
                try:
                    result = approve_operation(
                        start=self.start,
                        environment=self.environment,
                        params=params,
                    )
                except OperationInputError as exc:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message=str(exc),
                    )
                return success_response(request_id, result)
            if method == "operation.execute":
                try:
                    result = execute_operation(
                        start=self.start,
                        environment=self.environment,
                        params=params,
                        runner=self.provider_runner,
                    )
                except OperationInputError as exc:
                    return error_response(
                        request_id,
                        code="invalid_params",
                        message=str(exc),
                    )
                return success_response(request_id, result)
            if method == "operation.cancel":
                try:
                    result = cancel_operation(
                        start=self.start,
                        environment=self.environment,
                        params=params,
                    )
                except OperationInputError as exc:
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
        output_stream.write(
            json.dumps(response, separators=(",", ":"), sort_keys=True)
        )
        output_stream.write("\n")
        output_stream.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args(argv)
    serve(ControlService(start=args.workspace))
    return 0
