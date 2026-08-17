"""Pure policy for experiment, evidence, log, and teardown operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import WorkspaceError, utc_now
from synthran.workspace.observed import Observation, ObservedState
from synthran.workspace.reconciliation import (
    ReconciliationReport,
    ReconciliationStep,
    derive_lifecycle,
)


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    risk: str
    mutates: bool
    reason: str


WORKFLOW_SPECS: dict[str, WorkflowSpec] = {
    "run-baseline": WorkflowSpec(
        "run-baseline",
        "R2",
        True,
        "start the accepted baseline experiment on the currently proven path",
    ),
    "run-congestion": WorkflowSpec(
        "run-congestion",
        "R2",
        True,
        "start the controlled congestion experiment on the currently proven path",
    ),
    "stop": WorkflowSpec(
        "stop",
        "R2",
        True,
        "stop the currently running controlled experiment without tearing down the base network",
    ),
    "collect": WorkflowSpec(
        "collect",
        "R1",
        False,
        "collect and validate current experiment evidence without provider mutation",
    ),
    "logs-network": WorkflowSpec(
        "logs-network",
        "R1",
        False,
        "read sanitized network logs without provider mutation",
    ),
    "logs-open5gs": WorkflowSpec(
        "logs-open5gs",
        "R1",
        False,
        "read sanitized Open5GS logs without provider mutation",
    ),
    "logs-ue": WorkflowSpec(
        "logs-ue",
        "R1",
        False,
        "read sanitized UE logs without provider mutation",
    ),
    "down": WorkflowSpec(
        "down",
        "R3",
        True,
        "tear down only explicitly owned experiment resources after destructive approval",
    ),
}


def workflow_spec(name: str) -> WorkflowSpec:
    try:
        return WORKFLOW_SPECS[name]
    except KeyError as exc:
        raise WorkspaceError(f"unsupported application workflow: {name}") from exc


def _current(observed: ObservedState, dimension: str, now: datetime) -> Observation | None:
    item = observed.get(dimension)
    if item is None or not item.is_fresh(now):
        return None
    return item


def _ready(observed: ObservedState, dimension: str, now: datetime) -> bool:
    item = _current(observed, dimension, now)
    return item is not None and item.state == "ready"


def _experiment_running(observed: ObservedState, now: datetime) -> bool:
    item = _current(observed, "experiment", now)
    return (
        item is not None
        and item.state == "ready"
        and item.facts.get("running") is True
    )


def _block(lifecycle: str, reason: str) -> ReconciliationReport:
    return ReconciliationReport(lifecycle, blocks=(reason,))


def _step(lifecycle: str, spec: WorkflowSpec) -> ReconciliationReport:
    return ReconciliationReport(
        lifecycle,
        steps=(
            ReconciliationStep(
                name=spec.name,
                risk=spec.risk,
                reason=spec.reason,
                mutates=spec.mutates,
            ),
        ),
    )


def _teardown_ownership_block(observed: ObservedState, now: datetime) -> str | None:
    """Require current, non-foreign ownership facts before even planning teardown."""

    for dimension in (
        "reservation",
        "allocation",
        "preparation",
        "kubernetes",
        "core",
        "ran",
        "ue",
        "pdu",
        "upf",
        "radio",
    ):
        item = observed.get(dimension)
        if item is None or item.state == "absent":
            continue
        if not item.is_fresh(now):
            return f"current {dimension} ownership is stale"
        if item.ownership in {"unknown", "other"}:
            return f"current {dimension} ownership does not permit teardown"
    return None


def plan_workflow(
    desired: ExperimentDesiredState,
    observed: ObservedState,
    workflow: str,
    *,
    now: datetime | None = None,
) -> ReconciliationReport:
    """Return one immutable application-workflow policy decision from current state."""

    current = (now or utc_now()).astimezone(timezone.utc)
    spec = workflow_spec(workflow)
    lifecycle = derive_lifecycle(desired, observed, now=current)

    if workflow in {"run-baseline", "run-congestion"}:
        if lifecycle != "PATH_PROVEN" or not _ready(observed, "path", current):
            return _block(lifecycle, "experiment start requires a current path-proven network")
        if _experiment_running(observed, current):
            return _block(lifecycle, "another experiment is already running")
        return _step(lifecycle, spec)

    if workflow == "stop":
        if lifecycle != "EXPERIMENT_RUNNING" or not _experiment_running(observed, current):
            return _block(lifecycle, "stop requires a currently running experiment")
        return _step(lifecycle, spec)

    if workflow == "collect":
        if lifecycle not in {"PATH_PROVEN", "EXPERIMENT_RUNNING"}:
            return _block(lifecycle, "evidence collection requires a current proven experiment path")
        if not _ready(observed, "path", current):
            return _block(lifecycle, "evidence collection requires current path evidence")
        return _step(lifecycle, spec)

    if workflow == "logs-network":
        if lifecycle in {"CONFIGURED", "RESERVED", "ALLOCATED"}:
            return _block(lifecycle, "network logs are unavailable before resource preparation")
        return _step(lifecycle, spec)

    if workflow == "logs-open5gs":
        core = _current(observed, "core", current)
        if core is None or core.state == "absent":
            return _block(lifecycle, "Open5GS logs require a current core runtime")
        return _step(lifecycle, spec)

    if workflow == "logs-ue":
        ue = _current(observed, "ue", current)
        if ue is None or ue.state == "absent":
            return _block(lifecycle, "UE logs require a current UE runtime")
        return _step(lifecycle, spec)

    if workflow == "down":
        if lifecycle == "EXPERIMENT_RUNNING":
            return _block(lifecycle, "stop the active experiment before teardown")
        if lifecycle == "CONFIGURED":
            return _block(lifecycle, "no live experiment resources are currently known for teardown")
        ownership_block = _teardown_ownership_block(observed, current)
        if ownership_block is not None:
            return _block(lifecycle, ownership_block)
        return _step(lifecycle, spec)

    raise AssertionError("unreachable application workflow")
