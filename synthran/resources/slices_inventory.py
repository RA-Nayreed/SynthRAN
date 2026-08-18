"""Read-only SLICES compute inventory from POS reservation and allocation state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
import subprocess
from typing import Callable, Mapping, Sequence

from synthran.resources.catalog import SLICES_COMPUTE
from synthran.resources.model import ProviderResourceSnapshot, ResourceSelectionError, ResourceState
from synthran.workspace.model import format_utc, parse_utc, utc_now


DEFAULT_INVENTORY_TIMEOUT_SECONDS = 15
DEFAULT_INVENTORY_FRESHNESS = timedelta(seconds=30)
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class SlicesInventoryError(ResourceSelectionError):
    """Raised when current SLICES compute state cannot be established safely."""


@dataclass(frozen=True)
class InventoryCommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


Runner = Callable[[Sequence[str], int], InventoryCommandResult]


def subprocess_runner(command: Sequence[str], timeout_seconds: int) -> InventoryCommandResult:
    """Run one bounded POS read without a shell."""

    try:
        completed = subprocess.run(
            list(command),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise SlicesInventoryError("required POS command was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SlicesInventoryError("POS inventory query timed out") from exc
    return InventoryCommandResult(
        completed.returncode,
        completed.stdout or "",
        completed.stderr or "",
    )


def _safe_token(value: object, label: str) -> str:
    if not isinstance(value, str) or SAFE_TOKEN_RE.fullmatch(value) is None:
        raise SlicesInventoryError(f"{label} is malformed")
    return value


def _records(text: str, label: str) -> tuple[Mapping[str, object], ...]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SlicesInventoryError(f"{label} did not return JSON") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SlicesInventoryError(f"{label} must return an array of objects")
    return tuple(value)


def _nodes(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SlicesInventoryError(f"{label} has no node array")
    result: list[str] = []
    for item in value:
        candidate: object = item
        if isinstance(item, dict):
            candidate = next(
                (
                    item.get(key)
                    for key in ("id", "name", "node")
                    if isinstance(item.get(key), str)
                ),
                None,
            )
        result.append(_safe_token(candidate, f"{label} node"))
    if len(result) != len(set(result)):
        raise SlicesInventoryError(f"{label} contains duplicate nodes")
    return tuple(result)


def _owner(record: Mapping[str, object], label: str) -> str:
    return _safe_token(record.get("owner"), f"{label} owner")


def _checked_read(
    runner: Runner,
    command: Sequence[str],
    *,
    timeout_seconds: int,
    label: str,
) -> str:
    result = runner(command, timeout_seconds)
    if result.returncode != 0:
        raise SlicesInventoryError(f"{label} failed")
    if not result.stdout.strip():
        raise SlicesInventoryError(f"{label} returned no output")
    return result.stdout


def _reservation_window(record: Mapping[str, object]) -> tuple[datetime, datetime]:
    start_value = record.get("start_date")
    end_value = record.get("end_date")
    if not isinstance(start_value, str) or not isinstance(end_value, str):
        raise SlicesInventoryError("POS reservation time window is malformed")
    try:
        start = parse_utc(start_value, "POS reservation start")
        end = parse_utc(end_value, "POS reservation end")
    except Exception as exc:
        raise SlicesInventoryError("POS reservation time window is malformed") from exc
    if end <= start:
        raise SlicesInventoryError("POS reservation end must be after its start")
    return start, end


def read_slices_compute_snapshot(
    *,
    operator: str,
    runner: Runner = subprocess_runner,
    timeout_seconds: int = DEFAULT_INVENTORY_TIMEOUT_SECONDS,
    now: datetime | None = None,
) -> ProviderResourceSnapshot:
    """Return current reviewed SLICES compute state without changing provider resources."""

    operator = _safe_token(operator, "SLICES operator")
    if timeout_seconds <= 0 or timeout_seconds > 60:
        raise SlicesInventoryError("inventory timeout must be between 1 and 60 seconds")
    current = (now or utc_now()).astimezone(timezone.utc)
    reviewed_ids = {item.resource_id for item in SLICES_COMPUTE}

    reservation_text = _checked_read(
        runner,
        ("pos", "calendar", "list", "--json"),
        timeout_seconds=timeout_seconds,
        label="POS reservation inventory",
    )
    allocation_text = _checked_read(
        runner,
        ("pos", "allocations", "list", "--json"),
        timeout_seconds=timeout_seconds,
        label="POS allocation inventory",
    )

    active_reservations: dict[str, str] = {}
    freshness_events: list[datetime] = []
    for record in _records(reservation_text, "POS reservation inventory"):
        owner = _owner(record, "POS reservation")
        nodes = _nodes(record.get("nodes"), "POS reservation")
        start, end = _reservation_window(record)
        relevant = reviewed_ids.intersection(nodes)
        if not relevant:
            continue
        if start > current:
            freshness_events.append(start)
            continue
        if current >= end:
            continue
        freshness_events.append(end)
        for node in relevant:
            if node in active_reservations:
                raise SlicesInventoryError(
                    "reviewed SLICES node appears in overlapping active reservations"
                )
            active_reservations[node] = owner

    allocations: dict[str, str] = {}
    for record in _records(allocation_text, "POS allocation inventory"):
        owner = _owner(record, "POS allocation")
        nodes = _nodes(record.get("nodes"), "POS allocation")
        for node in reviewed_ids.intersection(nodes):
            if node in allocations:
                raise SlicesInventoryError(
                    "reviewed SLICES node appears in multiple allocations"
                )
            allocations[node] = owner

    states: list[ResourceState] = []
    for descriptor in SLICES_COMPUTE:
        node = descriptor.resource_id
        reservation_owner = active_reservations.get(node)
        allocation_owner = allocations.get(node)
        if (
            reservation_owner is not None
            and allocation_owner is not None
            and reservation_owner != allocation_owner
        ):
            raise SlicesInventoryError(
                "reviewed SLICES node has conflicting reservation and allocation ownership"
            )
        if allocation_owner is not None:
            ownership = "operator" if allocation_owner == operator else "other"
            states.append(ResourceState(node, "allocated", ownership))
        elif reservation_owner is not None:
            if reservation_owner == operator:
                states.append(ResourceState(node, "available", "operator"))
            else:
                states.append(ResourceState(node, "unavailable", "other"))
        else:
            states.append(ResourceState(node, "available", "unowned"))

    fresh_until = current + DEFAULT_INVENTORY_FRESHNESS
    future_events = [event for event in freshness_events if event > current]
    if future_events:
        fresh_until = min(fresh_until, min(future_events))
    if fresh_until <= current:
        raise SlicesInventoryError("SLICES inventory freshness boundary is invalid")

    return ProviderResourceSnapshot(
        provider="slices",
        observed_at_utc=format_utc(current),
        fresh_until_utc=format_utc(fresh_until),
        complete=True,
        resources=tuple(states),
    )
