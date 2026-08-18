"""Conservative read-only inventory for reviewed SynthRAN resources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Mapping

from synthran.resources.catalog import reviewed_resource_catalog
from synthran.resources.model import ProviderResourceSnapshot, ResourceInventory, ResourceState
from synthran.workspace.access import ProbeResult, Runner, ensure_slices_project_access, subprocess_runner
from synthran.workspace.context import resolve_workspace_authority
from synthran.workspace.model import WorkspaceError, format_utc, utc_now


INVENTORY_FRESHNESS_SECONDS = 60
RESOURCE_READ_TIMEOUT_SECONDS = 60


def _allocation_records(text: str) -> tuple[Mapping[str, object], ...]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkspaceError("POS allocation inventory did not return JSON") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise WorkspaceError("POS allocation inventory must return an array of objects")
    return tuple(value)


def _allocation_nodes(record: Mapping[str, object]) -> tuple[str, ...]:
    value = record.get("nodes")
    if not isinstance(value, list):
        raise WorkspaceError("POS allocation inventory record has no node array")
    nodes: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            nodes.append(item.strip())
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
                nodes.append(candidate.strip())
                continue
        raise WorkspaceError("POS allocation inventory contains an invalid node")
    return tuple(nodes)


def _allocation_owner(record: Mapping[str, object]) -> str:
    value = record.get("owner")
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceError("POS allocation inventory record has no owner")
    return value.strip()


def _slices_snapshot(
    *,
    username: str,
    runner: Runner,
    now: datetime,
    timeout_seconds: int,
) -> ProviderResourceSnapshot:
    result: ProbeResult = runner(("pos", "allocations", "list", "--json"), timeout_seconds)
    if result.returncode != 0:
        raise WorkspaceError("POS allocation inventory could not be read")

    catalog = reviewed_resource_catalog()
    slices_ids = {
        item.resource_id
        for item in catalog
        if item.provider == "slices"
    }
    states: dict[str, ResourceState] = {
        resource_id: ResourceState(resource_id, "unknown", "unknown")
        for resource_id in slices_ids
    }
    observed_nodes: set[str] = set()
    for record in _allocation_records(result.stdout):
        owner = _allocation_owner(record)
        ownership = "operator" if owner == username else "other"
        for node in _allocation_nodes(record):
            if node not in slices_ids:
                continue
            if node in observed_nodes:
                raise WorkspaceError(
                    "POS allocation inventory reports one reviewed node in multiple allocations"
                )
            observed_nodes.add(node)
            states[node] = ResourceState(node, "allocated", ownership)

    observed = now.astimezone(timezone.utc)
    return ProviderResourceSnapshot(
        provider="slices",
        observed_at_utc=format_utc(observed),
        fresh_until_utc=format_utc(
            observed + timedelta(seconds=INVENTORY_FRESHNESS_SECONDS)
        ),
        complete=False,
        resources=tuple(states[resource_id] for resource_id in sorted(states)),
    )


def read_resource_inventory(
    *,
    start=None,
    environment=None,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = RESOURCE_READ_TIMEOUT_SECONDS,
    now: datetime | None = None,
) -> ResourceInventory:
    """Read only facts that can be proven without claiming provider availability."""

    if timeout_seconds < 5 or timeout_seconds > 300:
        raise WorkspaceError("resource inventory timeout must be between 5 and 300 seconds")
    current = (now or utc_now()).astimezone(timezone.utc)
    authority = resolve_workspace_authority(start=start, environment=environment)
    username = authority.profile.slices_username
    if username is None:
        raise WorkspaceError("selected profile has no SLICES username")

    ensure_slices_project_access(
        workspace_root=authority.root,
        username=username,
        project=authority.slices_project,
        force=True,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    slices = _slices_snapshot(
        username=username,
        runner=runner,
        now=current,
        timeout_seconds=timeout_seconds,
    )
    return ResourceInventory(
        descriptors=reviewed_resource_catalog(),
        snapshots=(slices,),
    )


def resource_inventory_view(
    inventory: ResourceInventory,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Serialize reviewed capability and conservative live state without authority IDs."""

    current = (now or utc_now()).astimezone(timezone.utc)
    providers: list[dict[str, object]] = []
    for provider in ("slices", "r2lab", "virtual"):
        if provider == "virtual":
            providers.append(
                {
                    "provider": provider,
                    "fresh": True,
                    "complete": True,
                    "detail": "local virtual capability",
                }
            )
            continue
        snapshot = inventory.snapshot(provider)
        if snapshot is None:
            providers.append(
                {
                    "provider": provider,
                    "fresh": False,
                    "complete": False,
                    "detail": "resource-specific live state not observed",
                }
            )
            continue
        providers.append(
            {
                "provider": provider,
                "fresh": snapshot.is_fresh(current),
                "complete": snapshot.complete,
                "detail": "allocation ownership observed; reservation availability not established",
            }
        )

    resources: list[dict[str, object]] = []
    for descriptor in inventory.descriptors:
        state = inventory.state(descriptor.resource_id)
        resources.append(
            {
                "resource_id": descriptor.resource_id,
                "provider": descriptor.provider,
                "kind": descriptor.kind,
                "capabilities": sorted(descriptor.capabilities),
                "availability": state.availability if state is not None else "unknown",
                "ownership": state.ownership if state is not None else "unknown",
                "selectable": state.selectable if state is not None else False,
            }
        )
    return {"providers": providers, "resources": resources}
