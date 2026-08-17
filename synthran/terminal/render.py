"""Pure inline rendering for application snapshots and structured operation events."""

from __future__ import annotations

from synthran.app.model import ApplicationSnapshot, DimensionView
from synthran.operations.model import OperationEvent
from synthran.terminal.commands import TerminalCommandError


RESOURCE_DIMENSIONS = frozenset(
    {
        "controller",
        "project_access",
        "provider_experiment",
        "reservation",
        "allocation",
        "preparation",
        "r2lab_lease",
    }
)
NETWORK_DIMENSIONS = frozenset(
    {
        "kubernetes",
        "core",
        "ran",
        "ue",
        "pdu",
        "upf",
        "radio",
        "iot",
        "path",
        "experiment",
        "dataset",
    }
)


def _value(value: str | None) -> str:
    return value if value else "—"


def render_status(snapshot: ApplicationSnapshot) -> tuple[str, ...]:
    """Render a compact session-first status block without a persistent dashboard."""

    lines = [
        f"Lifecycle: {snapshot.lifecycle}",
        f"Workspace: {snapshot.workspace_root}",
        f"Profile: {snapshot.profile}",
        f"Project: {snapshot.project}",
        f"Experiment: {_value(snapshot.experiment_id)}",
        f"Provider experiment: {_value(snapshot.provider_experiment)}",
        f"Intent: {_value(snapshot.intent)}",
        f"Radio: {_value(snapshot.radio_mode)}",
    ]
    if snapshot.blocks:
        lines.append("Blocked:")
        lines.extend(f"  - {item}" for item in snapshot.blocks)
    elif snapshot.next_steps:
        lines.append("Next: " + ", ".join(snapshot.next_steps))
    return tuple(lines)


def _render_dimension(item: DimensionView) -> str:
    freshness = "fresh" if item.fresh else "stale"
    source = item.source or "—"
    ownership = item.ownership or "—"
    detail = f" — {item.detail}" if item.detail else ""
    return (
        f"{item.name}: {item.state} [{freshness}; source={source}; owner={ownership}]"
        f"{detail}"
    )


def render_inspect(
    snapshot: ApplicationSnapshot,
    topic: str,
) -> tuple[str, ...]:
    """Render the selected observation subset from the reconciled application snapshot."""

    if topic == "resources":
        allowed = RESOURCE_DIMENSIONS
        heading = "Resources"
    elif topic == "network":
        allowed = NETWORK_DIMENSIONS
        heading = "Network"
    else:
        raise TerminalCommandError("inspect topic is unsupported")
    selected = tuple(
        item for item in snapshot.observations if item.name in allowed
    )
    lines = [f"{heading}:"]
    if not selected:
        lines.append("  no observations")
    else:
        lines.extend(f"  {_render_dimension(item)}" for item in selected)
    if snapshot.blocks:
        lines.append("Blocked:")
        lines.extend(f"  - {item}" for item in snapshot.blocks)
    return tuple(lines)


def render_operation_event(event: OperationEvent) -> tuple[str, ...]:
    """Render only structured event attributes; raw provider output is not accepted here."""

    attributes = event.attributes
    if event.event_type == "operation.started":
        return (f"Operation {event.operation_id} started: {attributes.get('kind', '—')}",)
    if event.event_type == "plan.created":
        return (f"Operation {event.operation_id}: plan ready",)
    if event.event_type == "approval.requested":
        return (
            f"Operation {event.operation_id}: approval required ({attributes.get('mode', 'standard')})",
        )
    if event.event_type == "approval.granted":
        return (
            f"Operation {event.operation_id}: approval granted ({attributes.get('mode', 'standard')})",
        )
    if event.event_type == "operation.authorized":
        return (f"Operation {event.operation_id}: authorized",)
    if event.event_type == "stage.started":
        return (f"[{attributes.get('stage', 'stage')}] running",)
    if event.event_type == "stage.progress":
        return (
            f"[{attributes.get('stage', 'stage')}] {attributes.get('current', '0')}/{attributes.get('total', '0')}",
        )
    if event.event_type == "stage.completed":
        return (f"[{attributes.get('stage', 'stage')}] ready",)
    if event.event_type == "stage.failed":
        return (
            f"[{attributes.get('stage', 'stage')}] {attributes.get('code', 'failed')}",
        )
    if event.event_type == "state.changed":
        return (
            f"[{attributes.get('dimension', 'state')}] {attributes.get('state', 'unknown')}",
        )
    if event.event_type == "operation.completed":
        return (f"Operation {event.operation_id}: completed",)
    if event.event_type == "operation.failed":
        rollback = attributes.get("rollback")
        return (
            f"Operation {event.operation_id}: failed"
            + (f" (rollback={rollback})" if rollback else ""),
        )
    if event.event_type == "operation.interrupted":
        return (f"Operation {event.operation_id}: interrupted",)
    if event.event_type == "recovery.required":
        return (f"Operation {event.operation_id}: recovery required",)
    return (f"Operation {event.operation_id}: {event.event_type}",)
