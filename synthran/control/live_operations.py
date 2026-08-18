"""Live execution boundary for the accepted virtual SLICES/RFSIM path."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from typing import Mapping, Sequence

from synthran.app import ApplicationController
from synthran.dependencies import load_lock
from synthran.fiveg_ansible import NetworkInventory, build_network_plan, load_inventory
from synthran.live_preflight import (
    POS_TIMEZONE,
    Runner,
    run_live_preflight,
    save_live_evidence,
    ssh_command,
    subprocess_runner,
    verify_allocations,
    verify_reservation,
)
from synthran.network.resources import (
    SUPPORTED_NODES,
    build_resource_preparation_plan,
    execute_resource_preparation,
)
from synthran.network.runtime import (
    execute_network_deployment,
    save_network_evidence,
    verify_network_path,
)
from synthran.network_runtime import run_command
from synthran.operations import load_plan, load_state
from synthran.resources.catalog import reviewed_resource_descriptors
from synthran.resources.model import (
    ProviderResourceSnapshot,
    ResourceInventory,
    ResourceState,
)
from synthran.slices_controller import SlicesControllerError, verify_slices_controller
from synthran.workspace.desired_store import load_desired_state
from synthran.workspace.model import WorkspaceError, format_utc, utc_now, validate_operation_id
from synthran.workspace.observed import Observation
from synthran.workspace.observed_store import load_observed_state, observed_state_path


RESOURCE_FRESHNESS = timedelta(minutes=5)
RUNTIME_FRESHNESS = timedelta(minutes=10)
POS_TIMEOUT_SECONDS = 60
LIVE_OPERATION_KINDS = frozenset(
    {"reserve", "allocate", "prepare", "up", "verify-path", "recover-allocation", "down"}
)
RESERVATION_ID_RE = re.compile(r"^[0-9]+$")
SAFE_PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
NETWORK_DIMENSIONS = ("kubernetes", "core", "ran", "ue", "pdu", "upf", "radio")


class LiveOperationError(WorkspaceError):
    """A validated live action could not be completed safely."""


def _json_array(text: str, label: str) -> tuple[Mapping[str, object], ...]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LiveOperationError(f"{label} did not return JSON") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise LiveOperationError(f"{label} must return an array of objects")
    return tuple(value)


def _json_object(text: str, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LiveOperationError(f"{label} did not return JSON") from exc
    if not isinstance(value, dict):
        raise LiveOperationError(f"{label} must return one JSON object")
    return value


def _identifier(record: Mapping[str, object], label: str) -> str:
    value = record.get("id")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    if isinstance(value, str) and SAFE_PROVIDER_ID_RE.fullmatch(value.strip()):
        return value.strip()
    raise LiveOperationError(f"{label} is missing or unsafe")


def _owner(record: Mapping[str, object], label: str) -> str:
    value = record.get("owner")
    if not isinstance(value, str) or not value.strip():
        raise LiveOperationError(f"{label} is missing")
    return value.strip()


def _nodes(value: object, label: str) -> set[str]:
    if not isinstance(value, list):
        raise LiveOperationError(f"{label} has no node array")
    result: set[str] = set()
    for item in value:
        if isinstance(item, str) and item.strip():
            result.add(item.strip())
            continue
        if isinstance(item, dict):
            candidate = next(
                (
                    item.get(key)
                    for key in ("id", "name", "node")
                    if isinstance(item.get(key), str) and str(item.get(key)).strip()
                ),
                None,
            )
            if isinstance(candidate, str):
                result.add(candidate.strip())
                continue
        raise LiveOperationError(f"{label} contains an invalid node")
    return result


def _checked(
    runner: Runner,
    command: Sequence[str],
    *,
    label: str,
    timeout_seconds: int = POS_TIMEOUT_SECONDS,
    allow_empty: bool = False,
) -> str:
    result = runner(command, timeout_seconds)
    if result.returncode != 0:
        raise LiveOperationError(f"{label} failed")
    text = result.stdout.strip()
    if not text and not allow_empty:
        raise LiveOperationError(f"{label} returned no output")
    return text


def _active_desired(controller: ApplicationController):
    record = controller.authority.active_experiment
    if record is None:
        raise LiveOperationError("workspace has no active experiment")
    return load_desired_state(controller.root, record.experiment_id)


def _current_allocation_id(controller: ApplicationController) -> str | None:
    record = controller.authority.active_experiment
    if record is None:
        return None
    path = observed_state_path(controller.root, record.experiment_id)
    if not path.is_file():
        return None
    observed = load_observed_state(controller.root, record.experiment_id)
    item = observed.observation("allocation")
    if item is None or item.ownership != "synthran":
        return None
    return item.resource_id


def _verify_control_context(
    controller: ApplicationController,
    *,
    runner: Runner,
) -> None:
    authority = controller.authority
    if authority.slices_experiment is None:
        raise LiveOperationError("active experiment has no provider experiment binding")
    try:
        verify_slices_controller(
            lock=load_lock(controller.root / "dependencies.lock.yml"),
            project=authority.slices_project,
            experiment=authority.slices_experiment,
            runner=runner,
            environment=controller.environment,
            timeout_seconds=min(POS_TIMEOUT_SECONDS, 300),
        )
    except SlicesControllerError as exc:
        raise LiveOperationError(str(exc)) from exc


def discover_slices_inventory(
    *,
    controller: ApplicationController,
    runner: Runner = subprocess_runner,
    now: datetime | None = None,
) -> ResourceInventory:
    """Build one complete SLICES compute snapshot from the current POS allocation table."""

    current = (now or utc_now()).astimezone(timezone.utc)
    owner = controller.authority.profile.slices_username
    if owner is None:
        raise LiveOperationError("workspace profile has no SLICES username")
    records = _json_array(
        _checked(
            runner,
            ("pos", "allocations", "list", "--json"),
            label="POS allocation inventory",
        ),
        "POS allocation inventory",
    )
    known_claim = _current_allocation_id(controller)
    by_node: dict[str, tuple[str, str]] = {}
    supported = set(SUPPORTED_NODES)
    for record in records:
        record_nodes = _nodes(record.get("nodes"), "POS allocation")
        relevant = supported.intersection(record_nodes)
        if not relevant:
            continue
        allocation_id = _identifier(record, "allocation ID")
        allocation_owner = _owner(record, "allocation owner")
        for node in relevant:
            if node in by_node:
                raise LiveOperationError("POS allocation inventory is ambiguous for a supported node")
            by_node[node] = (allocation_id, allocation_owner)

    states: list[ResourceState] = []
    for node in sorted(supported):
        allocation = by_node.get(node)
        if allocation is None:
            states.append(ResourceState(node, "available", "unowned"))
            continue
        allocation_id, allocation_owner = allocation
        if allocation_owner != owner:
            ownership = "other"
        elif known_claim is not None and allocation_id == known_claim:
            ownership = "synthran"
        else:
            ownership = "operator"
        states.append(ResourceState(node, "allocated", ownership))

    return ResourceInventory(
        descriptors=reviewed_resource_descriptors(),
        snapshots=(
            ProviderResourceSnapshot(
                provider="slices",
                observed_at_utc=format_utc(current),
                fresh_until_utc=format_utc(current + RESOURCE_FRESHNESS),
                complete=True,
                resources=tuple(states),
            ),
        ),
    )


def _selected_nodes(
    controller: ApplicationController,
    inventory: ResourceInventory,
    now: datetime,
) -> tuple[str, str]:
    desired = _active_desired(controller)
    if desired.radio.mode != "virtual" or desired.radio.backend != "rfsim":
        raise LiveOperationError(
            "live workbench execution currently supports only the virtual RFSIM path"
        )
    decision = controller.resource_decision(inventory, now=now)
    core = decision.selection.for_role("core")
    ran = decision.selection.for_role("ran")
    if len(core) != 1 or len(ran) != 1:
        raise LiveOperationError(
            "virtual execution requires exactly one core node and one RAN node"
        )
    return core[0].resource_id, ran[0].resource_id


def _parse_provider_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise LiveOperationError(f"{label} is missing")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise LiveOperationError(f"{label} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=POS_TIMEZONE)
    return parsed.astimezone(timezone.utc)


def _active_reservation(
    *,
    runner: Runner,
    owner: str,
    nodes: set[str],
    now: datetime,
) -> tuple[str, Mapping[str, object]] | None:
    records = _json_array(
        _checked(
            runner,
            ("pos", "calendar", "list", "--filter", f"owner={owner}", "--json"),
            label="POS reservation inventory",
        ),
        "POS reservation inventory",
    )
    matches: list[tuple[str, Mapping[str, object]]] = []
    for record in records:
        record_nodes = _nodes(record.get("nodes"), "POS reservation")
        if not nodes.issubset(record_nodes):
            continue
        start = _parse_provider_time(record.get("start_date"), "reservation start")
        end = _parse_provider_time(record.get("end_date"), "reservation end")
        if start <= now < end:
            matches.append((_identifier(record, "reservation ID"), record))
    if len(matches) > 1:
        raise LiveOperationError(
            "multiple current reservations cover the selected node pair"
        )
    return matches[0] if matches else None


def _touching_allocations(
    *,
    runner: Runner,
    nodes: set[str],
) -> tuple[tuple[str, str, set[str]], ...]:
    records = _json_array(
        _checked(
            runner,
            ("pos", "allocations", "list", "--json"),
            label="POS allocation inventory",
        ),
        "POS allocation inventory",
    )
    touched: list[tuple[str, str, set[str]]] = []
    for record in records:
        record_nodes = _nodes(record.get("nodes"), "POS allocation")
        if nodes.intersection(record_nodes):
            touched.append(
                (
                    _identifier(record, "allocation ID"),
                    _owner(record, "allocation owner"),
                    record_nodes,
                )
            )
    return tuple(touched)


def _observation(
    dimension: str,
    state: str,
    *,
    now: datetime,
    ownership: str,
    resource_id: str | None = None,
    detail: str = "",
    facts: Mapping[str, object] | None = None,
    freshness: timedelta = RUNTIME_FRESHNESS,
) -> Observation:
    return Observation(
        dimension=dimension,
        state=state,
        source="provider",
        observed_at_utc=format_utc(now),
        fresh_until_utc=format_utc(now + freshness),
        ownership=ownership,
        resource_id=resource_id,
        detail=detail,
        facts=facts or {},
    )


def _merge_observations(
    controller: ApplicationController,
    updates: Mapping[str, Observation],
    *,
    now: datetime,
) -> None:
    record = controller.authority.active_experiment
    if record is None:
        raise LiveOperationError("workspace has no active experiment")
    path = observed_state_path(controller.root, record.experiment_id)
    grouped: dict[str, list[Observation]] = {}
    if path.is_file():
        observed = load_observed_state(controller.root, record.experiment_id)
        grouped = {item.dimension: [item] for item in observed.observations}
    for dimension, item in updates.items():
        grouped[dimension] = [item]
    controller.record_observations(grouped, now=now)


def refresh_slices_control_state(
    *,
    start: Path | None,
    environment: Mapping[str, str],
    runner: Runner = subprocess_runner,
    now: datetime | None = None,
) -> ResourceInventory:
    """Refresh provider authority, reservation, and allocation facts without mutation."""

    current = (now or utc_now()).astimezone(timezone.utc)
    controller = ApplicationController(start=start, environment=environment)
    authority = controller.authority
    record = authority.active_experiment
    if record is None or record.slices_experiment is None:
        raise LiveOperationError("active experiment has no provider experiment binding")
    owner = authority.profile.slices_username
    if owner is None:
        raise LiveOperationError("workspace profile has no SLICES username")

    _verify_control_context(controller, runner=runner)
    inventory = discover_slices_inventory(controller=controller, runner=runner, now=current)
    core_node, ran_node = _selected_nodes(controller, inventory, current)
    selected = {core_node, ran_node}

    previous_reservation: str | None = None
    previous_allocation: str | None = None
    observed_path = observed_state_path(controller.root, record.experiment_id)
    if observed_path.is_file():
        previous = load_observed_state(controller.root, record.experiment_id)
        reservation_item = previous.observation("reservation")
        allocation_item = previous.observation("allocation")
        if reservation_item is not None and reservation_item.ownership == "synthran":
            previous_reservation = reservation_item.resource_id
        if allocation_item is not None and allocation_item.ownership == "synthran":
            previous_allocation = allocation_item.resource_id

    reservation = _active_reservation(
        runner=runner,
        owner=owner,
        nodes=selected,
        now=current,
    )
    if reservation is None:
        reservation_observation = _observation(
            "reservation",
            "absent",
            now=current,
            ownership="unowned",
            detail="no current reservation covers the selected nodes",
        )
    else:
        reservation_id, _ = reservation
        reservation_observation = _observation(
            "reservation",
            "ready",
            now=current,
            ownership=(
                "synthran" if reservation_id == previous_reservation else "operator"
            ),
            resource_id=reservation_id,
            detail="current POS reservation covers the selected nodes",
            facts={"core_node": core_node, "ran_node": ran_node},
        )

    touched = _touching_allocations(runner=runner, nodes=selected)
    if not touched:
        allocation_observation = _observation(
            "allocation",
            "absent",
            now=current,
            ownership="unowned",
            detail="selected nodes are not allocated",
        )
    elif len(touched) != 1:
        allocation_observation = _observation(
            "allocation",
            "blocked",
            now=current,
            ownership="unknown",
            detail="selected nodes touch multiple allocations",
        )
    else:
        allocation_id, allocation_owner, allocated_nodes = touched[0]
        facts = {"core_node": core_node, "ran_node": ran_node}
        if allocation_owner != owner:
            allocation_observation = _observation(
                "allocation",
                "blocked",
                now=current,
                ownership="other",
                resource_id=allocation_id,
                detail="selected nodes are allocated to another operator",
                facts=facts,
            )
        elif allocation_id != previous_allocation:
            allocation_observation = _observation(
                "allocation",
                "blocked",
                now=current,
                ownership="operator",
                resource_id=allocation_id,
                detail="selected nodes are allocated outside SynthRAN ownership",
                facts=facts,
            )
        else:
            complete = selected.issubset(allocated_nodes)
            allocation_observation = _observation(
                "allocation",
                "ready" if complete else "degraded",
                now=current,
                ownership="synthran",
                resource_id=allocation_id,
                detail=(
                    "current POS allocation matches SynthRAN ownership"
                    if complete
                    else "SynthRAN-owned allocation is incomplete"
                ),
                facts=facts,
            )

    _merge_observations(
        controller,
        {
            "controller": _observation(
                "controller",
                "ready",
                now=current,
                ownership="operator",
                detail="current SLICES controller was verified",
            ),
            "project_access": _observation(
                "project_access",
                "ready",
                now=current,
                ownership="operator",
                detail="current SLICES project was verified",
            ),
            "provider_experiment": _observation(
                "provider_experiment",
                "ready",
                now=current,
                ownership="operator",
                detail="bound provider experiment was verified",
            ),
            "reservation": reservation_observation,
            "allocation": allocation_observation,
        },
        now=current,
    )
    return inventory


def _require_current_observation(
    controller: ApplicationController,
    dimension: str,
    *,
    now: datetime,
    ownership: str | None = None,
    resource_id_required: bool = True,
) -> Observation:
    record = controller.authority.active_experiment
    if record is None:
        raise LiveOperationError("workspace has no active experiment")
    observed = load_observed_state(controller.root, record.experiment_id)
    item = observed.observation(dimension)
    if item is None or not item.is_fresh(now):
        raise LiveOperationError(f"current {dimension} evidence is unavailable")
    if ownership is not None and item.ownership != ownership:
        raise LiveOperationError(f"current {dimension} is not SynthRAN-owned")
    if resource_id_required and item.resource_id is None:
        raise LiveOperationError(f"current {dimension} has no exact resource ID")
    return item


def _record_network_absent(
    controller: ApplicationController,
    *,
    now: datetime,
) -> None:
    _merge_observations(
        controller,
        {
            dimension: _observation(
                dimension,
                "absent",
                now=now,
                ownership="unowned",
                detail="no current run-owned network state is recorded",
            )
            for dimension in (*NETWORK_DIMENSIONS, "path")
        },
        now=now,
    )


def _record_network_pending(
    controller: ApplicationController,
    *,
    run_id: str,
    preparation_id: str,
    now: datetime,
) -> None:
    updates = {
        dimension: _observation(
            dimension,
            "pending",
            now=now,
            ownership="synthran",
            resource_id=run_id,
            detail="run-owned deployment requires current path verification",
            facts={"preparation_run": preparation_id},
        )
        for dimension in NETWORK_DIMENSIONS
    }
    updates["path"] = _observation(
        "path",
        "absent",
        now=now,
        ownership="unowned",
        detail="end-to-end path has not been proven for the current deployment",
    )
    _merge_observations(controller, updates, now=now)


def _record_network_ready(
    controller: ApplicationController,
    *,
    run_id: str,
    preparation_id: str,
    now: datetime,
) -> None:
    updates = {
        dimension: _observation(
            dimension,
            "ready",
            now=now,
            ownership="synthran",
            resource_id=run_id,
            detail="current run-owned virtual network component is verified",
            facts={"preparation_run": preparation_id},
        )
        for dimension in NETWORK_DIMENSIONS
    }
    updates["path"] = _observation(
        "path",
        "ready",
        now=now,
        ownership="synthran",
        resource_id=run_id,
        detail="current end-to-end path is proven",
        facts={"preparation_run": preparation_id},
    )
    _merge_observations(controller, updates, now=now)


@contextmanager
def _known_hosts(path: Path):
    previous = os.environ.get("SYNTHRAN_KNOWN_HOSTS")
    os.environ["SYNTHRAN_KNOWN_HOSTS"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SYNTHRAN_KNOWN_HOSTS", None)
        else:
            os.environ["SYNTHRAN_KNOWN_HOSTS"] = previous


def _finish_failure(
    controller: ApplicationController,
    operation_id: str,
    stage: str,
    *,
    now: datetime,
) -> None:
    try:
        controller.operations.stage_failed(
            operation_id,
            stage,
            "provider-action-failed",
            now=now,
        )
    finally:
        controller.finish_operation(operation_id, success=False, now=now)


def _verify_selected_reservation(
    controller: ApplicationController,
    runner: Runner,
    *,
    now: datetime,
    core_node: str,
    ran_node: str,
) -> Observation:
    reservation = _require_current_observation(
        controller,
        "reservation",
        now=now,
    )
    owner = controller.authority.profile.slices_username
    if owner is None:
        raise LiveOperationError("workspace profile has no SLICES username")
    verify_reservation(
        runner=runner,
        reservation_id=str(reservation.resource_id),
        owner=owner,
        nodes={core_node, ran_node},
        now=now,
        timeout_seconds=POS_TIMEOUT_SECONDS,
    )
    return reservation


def _allocation_id_after(
    runner: Runner,
    *,
    owner: str,
    core_node: str,
    ran_node: str,
) -> str:
    identifiers: set[str] = set()
    for node in (core_node, ran_node):
        record = _json_object(
            _checked(
                runner,
                ("pos", "allocations", "show", node),
                label=f"POS allocation query for {node}",
            ),
            f"POS allocation query for {node}",
        )
        if _owner(record, "allocation owner") != owner:
            raise LiveOperationError(
                "selected allocation is not owned by the expected operator"
            )
        identifiers.add(_identifier(record, "allocation ID"))
    if len(identifiers) != 1:
        raise LiveOperationError("selected nodes are not in one shared allocation")
    return next(iter(identifiers))


def _execute_reserve(
    controller: ApplicationController,
    operation_id: str,
    inventory: ResourceInventory,
    runner: Runner,
    *,
    now: datetime,
) -> None:
    authority = controller.authority
    owner = authority.profile.slices_username
    if owner is None:
        raise LiveOperationError("workspace profile has no SLICES username")
    core_node, ran_node = _selected_nodes(controller, inventory, now)
    if _active_reservation(
        runner=runner,
        owner=owner,
        nodes={core_node, ran_node},
        now=now,
    ) is not None:
        raise LiveOperationError(
            "a current reservation already covers the selected nodes; refresh and replan"
        )

    controller.authorize_operation(operation_id, inventory=inventory, now=now)
    controller.operations.stage_started(operation_id, "reservation", now=now)
    try:
        output = _checked(
            runner,
            (
                "pos",
                "calendar",
                "create",
                "-d",
                str(authority.workspace.reservation_minutes),
                "-s",
                "now",
                core_node,
                ran_node,
            ),
            label="POS reservation creation",
        )
        reservation_id = output.splitlines()[-1].strip()
        if RESERVATION_ID_RE.fullmatch(reservation_id) is None:
            raise LiveOperationError(
                "POS reservation creation did not return a numeric reservation ID"
            )
        verify_reservation(
            runner=runner,
            reservation_id=reservation_id,
            owner=owner,
            nodes={core_node, ran_node},
            now=now,
            timeout_seconds=POS_TIMEOUT_SECONDS,
        )
        _merge_observations(
            controller,
            {
                "reservation": _observation(
                    "reservation",
                    "ready",
                    now=now,
                    ownership="synthran",
                    resource_id=reservation_id,
                    detail="SynthRAN-created POS reservation is current",
                    facts={"core_node": core_node, "ran_node": ran_node},
                ),
                "allocation": _observation(
                    "allocation", "absent", now=now, ownership="unowned"
                ),
                "preparation": _observation(
                    "preparation", "absent", now=now, ownership="unowned"
                ),
            },
            now=now,
        )
        _record_network_absent(controller, now=now)
        controller.operations.state_changed(
            operation_id, "reservation", "ready", now=now
        )
        controller.operations.stage_completed(operation_id, "reservation", now=now)
        controller.finish_operation(operation_id, success=True, now=now)
    except Exception:
        _finish_failure(controller, operation_id, "reservation", now=now)
        raise


def _execute_allocate(
    controller: ApplicationController,
    operation_id: str,
    inventory: ResourceInventory,
    runner: Runner,
    *,
    now: datetime,
) -> None:
    owner = controller.authority.profile.slices_username
    if owner is None:
        raise LiveOperationError("workspace profile has no SLICES username")
    core_node, ran_node = _selected_nodes(controller, inventory, now)
    _verify_selected_reservation(
        controller,
        runner,
        now=now,
        core_node=core_node,
        ran_node=ran_node,
    )
    decision = controller.resource_decision(inventory, now=now)
    selected = {core_node, ran_node}
    if any(
        item.ownership != "unowned"
        for item in decision.states
        if item.resource_id in selected
    ):
        raise LiveOperationError(
            "Allocate requires the selected nodes to be currently unallocated"
        )

    controller.authorize_operation(operation_id, inventory=inventory, now=now)
    controller.operations.stage_started(operation_id, "allocation", now=now)
    try:
        _checked(
            runner,
            ("pos", "allocations", "allocate", core_node, ran_node),
            label="POS allocation",
            allow_empty=True,
        )
        allocation_id = _allocation_id_after(
            runner,
            owner=owner,
            core_node=core_node,
            ran_node=ran_node,
        )
        verify_allocations(
            runner=runner,
            allocation_id=allocation_id,
            owner=owner,
            nodes=selected,
            timeout_seconds=POS_TIMEOUT_SECONDS,
        )
        _merge_observations(
            controller,
            {
                "allocation": _observation(
                    "allocation",
                    "ready",
                    now=now,
                    ownership="synthran",
                    resource_id=allocation_id,
                    detail="one SynthRAN-owned allocation covers the selected nodes",
                    facts={"core_node": core_node, "ran_node": ran_node},
                ),
                "preparation": _observation(
                    "preparation", "absent", now=now, ownership="unowned"
                ),
            },
            now=now,
        )
        _record_network_absent(controller, now=now)
        controller.operations.state_changed(
            operation_id, "allocation", "ready", now=now
        )
        controller.operations.stage_completed(operation_id, "allocation", now=now)
        controller.finish_operation(operation_id, success=True, now=now)
    except Exception:
        _finish_failure(controller, operation_id, "allocation", now=now)
        raise


def _reuse_only_preparation_runner(command, cwd, environment, timeout_seconds):
    command_tuple = tuple(str(part) for part in command)
    if command_tuple[:3] == ("pos", "allocations", "allocate"):
        raise RuntimeError("Prepare cannot create a replacement allocation")
    if command_tuple[:3] == ("pos", "calendar", "create"):
        raise RuntimeError("Prepare cannot create a replacement reservation")
    return run_command(command, cwd, environment, timeout_seconds)


def _execute_prepare(
    controller: ApplicationController,
    operation_id: str,
    inventory: ResourceInventory,
    runner: Runner,
    *,
    now: datetime,
) -> None:
    authority = controller.authority
    if authority.slices_experiment is None:
        raise LiveOperationError("active experiment has no provider experiment binding")
    owner = authority.profile.slices_username
    if owner is None:
        raise LiveOperationError("workspace profile has no SLICES username")
    core_node, ran_node = _selected_nodes(controller, inventory, now)
    reservation = _verify_selected_reservation(
        controller,
        runner,
        now=now,
        core_node=core_node,
        ran_node=ran_node,
    )
    allocation = _require_current_observation(
        controller,
        "allocation",
        now=now,
        ownership="synthran",
    )
    verify_allocations(
        runner=runner,
        allocation_id=str(allocation.resource_id),
        owner=owner,
        nodes={core_node, ran_node},
        timeout_seconds=POS_TIMEOUT_SECONDS,
    )

    controller.authorize_operation(operation_id, inventory=inventory, now=now)
    controller.operations.stage_started(operation_id, "preparation", now=now)
    try:
        lock = load_lock(controller.root / "dependencies.lock.yml")
        result = execute_resource_preparation(
            plan=build_resource_preparation_plan(
                lock=lock,
                core_node=core_node,
                ran_node=ran_node,
                duration_minutes=authority.workspace.reservation_minutes,
                run_id=operation_id,
                reservation_id=str(reservation.resource_id),
            ),
            lock=lock,
            dependency_root=controller.root / ".deps",
            owner=owner,
            slices_project=authority.slices_project,
            slices_experiment=authority.slices_experiment,
            reservation_id=str(reservation.resource_id),
            run_root=controller.root / ".synthran" / "preparations",
            repository_root=controller.root,
            runner=_reuse_only_preparation_runner,
            now=now,
        )
        _merge_observations(
            controller,
            {
                "preparation": _observation(
                    "preparation",
                    "ready",
                    now=now,
                    ownership="synthran",
                    resource_id=result.run_id,
                    detail="selected nodes passed the guarded preparation path",
                    facts={"core_node": core_node, "ran_node": ran_node},
                )
            },
            now=now,
        )
        _record_network_absent(controller, now=now)
        controller.operations.state_changed(
            operation_id, "preparation", "ready", now=now
        )
        controller.operations.stage_completed(operation_id, "preparation", now=now)
        controller.finish_operation(operation_id, success=True, now=now)
    except Exception:
        _finish_failure(controller, operation_id, "preparation", now=now)
        raise


def _preparation_paths(
    controller: ApplicationController,
    *,
    now: datetime,
) -> tuple[Observation, Path, Path]:
    preparation = _require_current_observation(
        controller,
        "preparation",
        now=now,
        ownership="synthran",
    )
    run_directory = (
        controller.root
        / ".synthran"
        / "preparations"
        / str(preparation.resource_id)
    )
    inventory_path = run_directory / "hosts.ini"
    known_hosts = run_directory / "known_hosts"
    if not inventory_path.is_file() or not known_hosts.is_file():
        raise LiveOperationError("current preparation artifacts are incomplete")
    return preparation, inventory_path, known_hosts


def _execute_up(
    controller: ApplicationController,
    operation_id: str,
    inventory: ResourceInventory,
    runner: Runner,
    *,
    now: datetime,
) -> None:
    authority = controller.authority
    if authority.slices_experiment is None:
        raise LiveOperationError("active experiment has no provider experiment binding")
    owner = authority.profile.slices_username
    if owner is None:
        raise LiveOperationError("workspace profile has no SLICES username")
    core_node, ran_node = _selected_nodes(controller, inventory, now)
    reservation = _verify_selected_reservation(
        controller,
        runner,
        now=now,
        core_node=core_node,
        ran_node=ran_node,
    )
    allocation = _require_current_observation(
        controller,
        "allocation",
        now=now,
        ownership="synthran",
    )
    verify_allocations(
        runner=runner,
        allocation_id=str(allocation.resource_id),
        owner=owner,
        nodes={core_node, ran_node},
        timeout_seconds=POS_TIMEOUT_SECONDS,
    )
    preparation, inventory_path, known_hosts = _preparation_paths(
        controller, now=now
    )
    network_inventory = load_inventory(inventory_path)
    if {
        network_inventory.core_node.name,
        network_inventory.ran_node.name,
    } != {core_node, ran_node}:
        raise LiveOperationError(
            "prepared inventory no longer matches the selected resources"
        )

    controller.authorize_operation(operation_id, inventory=inventory, now=now)
    controller.operations.stage_started(operation_id, "network", now=now)
    try:
        lock = load_lock(controller.root / "dependencies.lock.yml")
        evidence_path = (
            controller.root
            / ".synthran"
            / "preparations"
            / str(preparation.resource_id)
            / "live-preflight.json"
        )
        with _known_hosts(known_hosts):
            preflight = run_live_preflight(
                inventory=network_inventory,
                owner=owner,
                reservation_id=str(reservation.resource_id),
                allocation_id=str(allocation.resource_id),
                lock=lock,
                slices_project=authority.slices_project,
                slices_experiment=authority.slices_experiment,
            )
            if not preflight.ready:
                raise LiveOperationError(
                    "fresh live preflight did not authorize network deployment"
                )
            save_live_evidence(preflight, evidence_path)
            execute_network_deployment(
                plan=build_network_plan(
                    lock=lock,
                    inventory=network_inventory,
                    profile="default",
                ),
                lock=lock,
                dependency_root=controller.root / ".deps",
                live_evidence_path=evidence_path,
                owner=owner,
                reservation_id=str(reservation.resource_id),
                allocation_id=str(allocation.resource_id),
                slices_project=authority.slices_project,
                slices_experiment=authority.slices_experiment,
                run_id=operation_id,
                run_root=controller.root / ".synthran" / "runs",
                repository_root=controller.root,
            )
        _record_network_pending(
            controller,
            run_id=operation_id,
            preparation_id=str(preparation.resource_id),
            now=now,
        )
        controller.operations.stage_completed(operation_id, "network", now=now)
        controller.finish_operation(operation_id, success=True, now=now)
    except Exception:
        _finish_failure(controller, operation_id, "network", now=now)
        raise


def _current_network_run(
    controller: ApplicationController,
    *,
    now: datetime,
    required: bool = True,
) -> str | None:
    record = controller.authority.active_experiment
    if record is None:
        raise LiveOperationError("workspace has no active experiment")
    observed = load_observed_state(controller.root, record.experiment_id)
    identifiers = {
        item.resource_id
        for dimension in NETWORK_DIMENSIONS
        if (item := observed.observation(dimension)) is not None
        and item.is_fresh(now)
        and item.ownership == "synthran"
        and item.resource_id is not None
        and item.state != "absent"
    }
    if not identifiers:
        if required:
            raise LiveOperationError("no current run-owned network is recorded")
        return None
    if len(identifiers) != 1:
        raise LiveOperationError(
            "current network components do not identify one exact run"
        )
    return next(iter(identifiers))


def _execute_verify(
    controller: ApplicationController,
    operation_id: str,
    *,
    now: datetime,
) -> None:
    preparation, inventory_path, known_hosts = _preparation_paths(
        controller, now=now
    )
    network_run = _current_network_run(controller, now=now)
    assert network_run is not None
    network_inventory = load_inventory(inventory_path)
    controller.authorize_operation(operation_id, now=now)
    controller.operations.stage_started(operation_id, "verification", now=now)
    try:
        lock = load_lock(controller.root / "dependencies.lock.yml")
        with _known_hosts(known_hosts):
            report = verify_network_path(
                inventory=network_inventory,
                lock=lock,
                run_id=network_run,
                now=now,
            )
        save_network_evidence(
            report,
            controller.root
            / ".synthran"
            / "runs"
            / network_run
            / "network-evidence.json",
            controller.root
            / ".synthran"
            / "runs"
            / network_run
            / "manifest.json",
        )
        if not report.ready:
            raise LiveOperationError("end-to-end path verification failed")
        _record_network_ready(
            controller,
            run_id=network_run,
            preparation_id=str(preparation.resource_id),
            now=now,
        )
        controller.operations.state_changed(
            operation_id, "path", "ready", now=now
        )
        controller.operations.stage_completed(
            operation_id, "verification", now=now
        )
        controller.finish_operation(operation_id, success=True, now=now)
    except Exception:
        _finish_failure(controller, operation_id, "verification", now=now)
        raise


def _execute_recover_allocation(
    controller: ApplicationController,
    operation_id: str,
    inventory: ResourceInventory,
    runner: Runner,
    *,
    now: datetime,
) -> None:
    owner = controller.authority.profile.slices_username
    if owner is None:
        raise LiveOperationError("workspace profile has no SLICES username")
    core_node, ran_node = _selected_nodes(controller, inventory, now)
    reservation = _verify_selected_reservation(
        controller,
        runner,
        now=now,
        core_node=core_node,
        ran_node=ran_node,
    )
    allocation = _require_current_observation(
        controller,
        "allocation",
        now=now,
        ownership="synthran",
    )
    selected = {core_node, ran_node}
    touched = _touching_allocations(runner=runner, nodes=selected)
    if len(touched) != 1:
        raise LiveOperationError(
            "allocation recovery requires exactly one current partial allocation"
        )
    allocation_id, allocation_owner, allocated_nodes = touched[0]
    if allocation_id != allocation.resource_id or allocation_owner != owner:
        raise LiveOperationError("allocation recovery encountered ownership drift")
    owned_selected = tuple(sorted(selected.intersection(allocated_nodes)))
    if not owned_selected or set(owned_selected) == selected:
        raise LiveOperationError(
            "allocation recovery requires an incomplete SynthRAN-owned allocation"
        )

    controller.authorize_operation(operation_id, inventory=inventory, now=now)
    controller.operations.stage_started(
        operation_id, "allocation-recovery", now=now
    )
    try:
        for node in owned_selected:
            _checked(
                runner,
                ("pos", "allocations", "free", "-k", node),
                label=f"POS allocation release for {node}",
                allow_empty=True,
            )
        _checked(
            runner,
            ("pos", "allocations", "allocate", core_node, ran_node),
            label="POS allocation recovery",
            allow_empty=True,
        )
        restored_id = _allocation_id_after(
            runner,
            owner=owner,
            core_node=core_node,
            ran_node=ran_node,
        )
        verify_allocations(
            runner=runner,
            allocation_id=restored_id,
            owner=owner,
            nodes=selected,
            timeout_seconds=POS_TIMEOUT_SECONDS,
        )
        verify_reservation(
            runner=runner,
            reservation_id=str(reservation.resource_id),
            owner=owner,
            nodes=selected,
            now=now,
            timeout_seconds=POS_TIMEOUT_SECONDS,
        )
        _merge_observations(
            controller,
            {
                "allocation": _observation(
                    "allocation",
                    "ready",
                    now=now,
                    ownership="synthran",
                    resource_id=restored_id,
                    detail="allocation recovery restored one exact owned pair",
                    facts={"core_node": core_node, "ran_node": ran_node},
                ),
                "preparation": _observation(
                    "preparation", "absent", now=now, ownership="unowned"
                ),
            },
            now=now,
        )
        _record_network_absent(controller, now=now)
        controller.operations.stage_completed(
            operation_id, "allocation-recovery", now=now
        )
        controller.finish_operation(operation_id, success=True, now=now)
    except Exception:
        _finish_failure(
            controller, operation_id, "allocation-recovery", now=now
        )
        raise


def _delete_run_owned_namespace(
    *,
    runner: Runner,
    network_inventory: NetworkInventory,
    run_id: str,
) -> None:
    query = runner(
        ssh_command(
            network_inventory.core_node,
            "sh",
            "-c",
            "KUBECONFIG=/etc/kubernetes/admin.conf kubectl get namespace open5gs -o json --ignore-not-found",
        ),
        POS_TIMEOUT_SECONDS,
    )
    if query.returncode != 0:
        raise LiveOperationError("Open5GS namespace ownership query failed")
    if not query.stdout.strip():
        return
    namespace = _json_object(query.stdout, "Open5GS namespace ownership query")
    metadata = namespace.get("metadata")
    labels = metadata.get("labels") if isinstance(metadata, dict) else None
    if not isinstance(labels, dict) or labels.get("synthran.run/id") != run_id:
        raise LiveOperationError(
            "Open5GS namespace is not owned by the approved network run"
        )
    result = runner(
        ssh_command(
            network_inventory.core_node,
            "sh",
            "-c",
            "KUBECONFIG=/etc/kubernetes/admin.conf kubectl delete namespace open5gs --wait=true --timeout=180s",
        ),
        210,
    )
    if result.returncode != 0:
        raise LiveOperationError("run-owned Open5GS namespace deletion failed")


def _execute_down(
    controller: ApplicationController,
    operation_id: str,
    runner: Runner,
    *,
    now: datetime,
) -> None:
    owner = controller.authority.profile.slices_username
    if owner is None:
        raise LiveOperationError("workspace profile has no SLICES username")
    allocation = _require_current_observation(
        controller,
        "allocation",
        now=now,
        ownership="synthran",
    )
    record = controller.authority.active_experiment
    if record is None:
        raise LiveOperationError("workspace has no active experiment")
    observed = load_observed_state(controller.root, record.experiment_id)
    preparation = observed.observation("preparation")
    network_run = _current_network_run(controller, now=now, required=False)

    network_inventory: NetworkInventory | None = None
    known_hosts: Path | None = None
    if preparation is not None and preparation.is_fresh(now) and preparation.state != "absent":
        if preparation.ownership != "synthran" or preparation.resource_id is None:
            raise LiveOperationError("current preparation is not safely owned")
        run_directory = (
            controller.root
            / ".synthran"
            / "preparations"
            / preparation.resource_id
        )
        inventory_path = run_directory / "hosts.ini"
        known_hosts = run_directory / "known_hosts"
        if not inventory_path.is_file() or not known_hosts.is_file():
            raise LiveOperationError("current preparation artifacts are incomplete")
        network_inventory = load_inventory(inventory_path)
    if network_run is not None and (network_inventory is None or known_hosts is None):
        raise LiveOperationError(
            "run-owned network exists without the preparation authority needed for teardown"
        )

    controller.authorize_operation(operation_id, now=now)
    controller.operations.stage_started(operation_id, "teardown", now=now)
    try:
        if network_run is not None:
            assert network_inventory is not None and known_hosts is not None
            with _known_hosts(known_hosts):
                _delete_run_owned_namespace(
                    runner=runner,
                    network_inventory=network_inventory,
                    run_id=network_run,
                )

        selected_nodes = {
            str(allocation.facts.get("core_node", "")),
            str(allocation.facts.get("ran_node", "")),
        }
        if "" in selected_nodes or len(selected_nodes) != 2:
            raise LiveOperationError(
                "current allocation does not identify the exact selected node pair"
            )
        verify_allocations(
            runner=runner,
            allocation_id=str(allocation.resource_id),
            owner=owner,
            nodes=selected_nodes,
            timeout_seconds=POS_TIMEOUT_SECONDS,
        )
        for node in sorted(selected_nodes):
            _checked(
                runner,
                ("pos", "allocations", "free", "-k", node),
                label=f"POS allocation release for {node}",
                allow_empty=True,
            )

        updates = {
            "allocation": _observation(
                "allocation", "absent", now=now, ownership="unowned"
            ),
            "preparation": _observation(
                "preparation", "absent", now=now, ownership="unowned"
            ),
        }
        _merge_observations(controller, updates, now=now)
        _record_network_absent(controller, now=now)
        controller.operations.stage_completed(operation_id, "teardown", now=now)
        controller.finish_operation(operation_id, success=True, now=now)
    except Exception:
        _finish_failure(controller, operation_id, "teardown", now=now)
        raise


def execute_live_operation(
    *,
    start: Path | None,
    environment: Mapping[str, str],
    operation_id: str,
    runner: Runner = subprocess_runner,
    now: datetime | None = None,
) -> None:
    """Execute one approved action through reviewed provider/domain boundaries."""

    operation_id = validate_operation_id(operation_id)
    current = (now or utc_now()).astimezone(timezone.utc)
    controller = ApplicationController(start=start, environment=environment)
    plan = load_plan(controller.root, operation_id)
    state = load_state(controller.root, operation_id)
    if plan.kind not in LIVE_OPERATION_KINDS:
        raise LiveOperationError("operation kind has no live workbench executor")
    expected = "approved" if plan.approval_required else "planned"
    if state.status != expected:
        raise LiveOperationError("operation is not ready for live execution")

    _verify_control_context(controller, runner=runner)
    inventory: ResourceInventory | None = None
    if plan.kind in {
        "reserve",
        "allocate",
        "prepare",
        "up",
        "recover-allocation",
    }:
        inventory = discover_slices_inventory(
            controller=controller,
            runner=runner,
            now=current,
        )

    if plan.kind == "reserve":
        assert inventory is not None
        _execute_reserve(controller, operation_id, inventory, runner, now=current)
    elif plan.kind == "allocate":
        assert inventory is not None
        _execute_allocate(controller, operation_id, inventory, runner, now=current)
    elif plan.kind == "prepare":
        assert inventory is not None
        _execute_prepare(
            controller, operation_id, inventory, runner, now=current
        )
    elif plan.kind == "up":
        assert inventory is not None
        _execute_up(controller, operation_id, inventory, runner, now=current)
    elif plan.kind == "verify-path":
        _execute_verify(controller, operation_id, now=current)
    elif plan.kind == "recover-allocation":
        assert inventory is not None
        _execute_recover_allocation(
            controller, operation_id, inventory, runner, now=current
        )
    else:
        _execute_down(controller, operation_id, runner, now=current)
