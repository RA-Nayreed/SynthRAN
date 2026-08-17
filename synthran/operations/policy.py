"""Pure operation planning, integrity binding, and approval policy."""

from __future__ import annotations

from datetime import datetime, timezone

from synthran.operations.journal import digest_json
from synthran.operations.model import ApprovalGrant, OperationPlan
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import WorkspaceError, format_utc, utc_now
from synthran.workspace.observed import ObservedState
from synthran.workspace.reconciliation import ReconciliationReport, ReconciliationStep


def reconciliation_to_dict(report: ReconciliationReport) -> dict[str, object]:
    return {
        "lifecycle": report.lifecycle,
        "steps": [
            {
                "name": step.name,
                "risk": step.risk,
                "reason": step.reason,
                "mutates": step.mutates,
            }
            for step in report.steps
        ],
        "blocks": list(report.blocks),
    }


def _select_step(
    report: ReconciliationReport,
    step_name: str | None,
) -> ReconciliationStep:
    if report.blocks:
        raise WorkspaceError("blocked reconciliation cannot create an executable operation")
    if not report.steps:
        raise WorkspaceError("reconciliation has no pending operation")
    if step_name is None:
        if len(report.steps) != 1:
            raise WorkspaceError("reconciliation has multiple read-only steps; choose one")
        return report.steps[0]
    matches = [step for step in report.steps if step.name == step_name]
    if len(matches) != 1:
        raise WorkspaceError("requested operation is not present in current reconciliation")
    return matches[0]


def build_operation_plan(
    *,
    operation_id: str,
    desired: ExperimentDesiredState,
    observed: ObservedState,
    reconciliation: ReconciliationReport,
    step_name: str | None = None,
    now: datetime | None = None,
) -> OperationPlan:
    """Bind one reconciliation step to exact desired, observed, and policy inputs."""

    step = _select_step(reconciliation, step_name)
    current = (now or utc_now()).astimezone(timezone.utc)
    desired_sha256 = digest_json(desired.to_dict())
    observed_sha256 = digest_json(observed.to_dict())
    reconciliation_sha256 = digest_json(reconciliation_to_dict(reconciliation))
    unsigned = {
        "schema": "synthran/operation-plan/v1alpha1",
        "operation_id": operation_id,
        "experiment_id": observed.experiment_id,
        "kind": step.name,
        "risk": step.risk,
        "mutates": step.mutates,
        "reason": step.reason,
        "desired_sha256": desired_sha256,
        "observed_sha256": observed_sha256,
        "reconciliation_sha256": reconciliation_sha256,
        "created_at_utc": format_utc(current),
    }
    return OperationPlan(
        operation_id=operation_id,
        experiment_id=observed.experiment_id,
        kind=step.name,
        risk=step.risk,
        mutates=step.mutates,
        reason=step.reason,
        desired_sha256=desired_sha256,
        observed_sha256=observed_sha256,
        reconciliation_sha256=reconciliation_sha256,
        plan_sha256=digest_json(unsigned),
        created_at_utc=format_utc(current),
    )


def verify_plan_inputs(
    plan: OperationPlan,
    *,
    desired: ExperimentDesiredState,
    observed: ObservedState,
    reconciliation: ReconciliationReport,
) -> None:
    """Reject execution whenever any planned input changed after review."""

    if observed.experiment_id != plan.experiment_id:
        raise WorkspaceError("current observed state belongs to another experiment")
    if digest_json(desired.to_dict()) != plan.desired_sha256:
        raise WorkspaceError("desired state changed after the operation was planned")
    if digest_json(observed.to_dict()) != plan.observed_sha256:
        raise WorkspaceError("observed state changed after the operation was planned")
    if digest_json(reconciliation_to_dict(reconciliation)) != plan.reconciliation_sha256:
        raise WorkspaceError("reconciliation changed after the operation was planned")
    if reconciliation.blocks:
        raise WorkspaceError("current reconciliation is blocked")
    matches = [step for step in reconciliation.steps if step.name == plan.kind]
    if len(matches) != 1:
        raise WorkspaceError("planned operation is no longer the current reconciliation action")
    step = matches[0]
    if (
        step.risk != plan.risk
        or step.mutates != plan.mutates
        or step.reason != plan.reason
    ):
        raise WorkspaceError("planned operation policy changed after review")


def required_approval_mode(plan: OperationPlan) -> str | None:
    if plan.risk in {"R0", "R1"}:
        return None
    if plan.risk == "R2":
        return "standard"
    return "destructive"


def verify_approval(plan: OperationPlan, approval: ApprovalGrant | None) -> None:
    required = required_approval_mode(plan)
    if required is None:
        if approval is not None:
            raise WorkspaceError("read-only operation must not use mutation approval")
        return
    if approval is None:
        raise WorkspaceError("operation requires explicit approval")
    if (
        approval.operation_id != plan.operation_id
        or approval.plan_sha256 != plan.plan_sha256
        or approval.risk != plan.risk
    ):
        raise WorkspaceError("approval does not match the immutable operation plan")
    if required == "destructive" and approval.mode != "destructive":
        raise WorkspaceError("destructive operation requires destructive approval")
