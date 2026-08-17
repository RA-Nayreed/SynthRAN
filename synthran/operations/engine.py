"""Persistent operation controller with approval, drift, and concurrency gates."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from synthran.operations.journal import (
    acquire_mutation_claim,
    append_event,
    load_approval,
    load_plan,
    load_state,
    next_event_sequence,
    release_mutation_claim,
    require_mutation_claim,
    save_approval,
    save_plan,
    save_state,
)
from synthran.operations.model import (
    ApprovalGrant,
    ExecutionPermit,
    OperationEvent,
    OperationPlan,
    OperationState,
)
from synthran.operations.policy import (
    build_operation_plan,
    required_approval_mode,
    select_reconciliation_step,
    verify_approval,
    verify_plan_inputs,
)
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import WorkspaceError, format_utc, utc_now
from synthran.workspace.observed import ObservedState
from synthran.workspace.reconciliation import plan_reconciliation
from synthran.workspace.registry import WorkspaceRegistry


class OperationController:
    """Create and authorize one-step operations without bypassing live provider gates."""

    def __init__(self, workspace_root: Path):
        self.root = workspace_root.resolve()
        self.registry = WorkspaceRegistry(self.root)

    def _event(
        self,
        plan: OperationPlan,
        event_type: str,
        *,
        now: datetime,
        attributes: dict[str, str] | None = None,
    ) -> None:
        append_event(
            self.root,
            OperationEvent(
                operation_id=plan.operation_id,
                sequence=next_event_sequence(self.root, plan.operation_id),
                event_type=event_type,
                occurred_at_utc=format_utc(now),
                risk=plan.risk,
                mutates=plan.mutates,
                plan_sha256=plan.plan_sha256,
                attributes=attributes or {},
            ),
        )

    def begin(
        self,
        *,
        desired: ExperimentDesiredState,
        observed: ObservedState,
        step_name: str | None = None,
        targets: tuple[str, ...] = (),
        bound_inputs: Mapping[str, Mapping[str, object]] | None = None,
        now: datetime | None = None,
    ) -> OperationPlan:
        """Create one immutable operation from the current reconciliation result."""

        current = (now or utc_now()).astimezone(timezone.utc)
        reconciliation = plan_reconciliation(desired, observed, now=current)
        step = select_reconciliation_step(reconciliation, step_name)
        operation_id = self.registry.issue_operation_id(
            kind=step.name,
            experiment_id=observed.experiment_id,
            now=current,
        )
        plan = build_operation_plan(
            operation_id=operation_id,
            desired=desired,
            observed=observed,
            reconciliation=reconciliation,
            step_name=step.name,
            targets=targets,
            bound_inputs=bound_inputs,
            now=current,
        )
        save_plan(self.root, plan)
        status = "awaiting-approval" if plan.approval_required else "planned"
        save_state(
            self.root,
            OperationState(
                operation_id=operation_id,
                status=status,
                risk=plan.risk,
                mutates=plan.mutates,
                plan_sha256=plan.plan_sha256,
                updated_at_utc=format_utc(current),
            ),
        )
        self._event(
            plan,
            "operation.started",
            now=current,
            attributes={"kind": plan.kind},
        )
        self._event(plan, "plan.created", now=current)
        if plan.approval_required:
            self._event(
                plan,
                "approval.requested",
                now=current,
                attributes={
                    "mode": required_approval_mode(plan) or "standard",
                },
            )
        return plan

    def approve(
        self,
        operation_id: str,
        *,
        mode: str = "standard",
        now: datetime | None = None,
    ) -> ApprovalGrant:
        """Persist explicit approval bound to one immutable operation plan."""

        current = (now or utc_now()).astimezone(timezone.utc)
        plan = load_plan(self.root, operation_id)
        state = load_state(self.root, operation_id)
        if not plan.approval_required:
            raise WorkspaceError("read-only operation does not require approval")
        if state.status != "awaiting-approval":
            raise WorkspaceError("operation is not awaiting approval")
        approval = ApprovalGrant(
            operation_id=operation_id,
            plan_sha256=plan.plan_sha256,
            risk=plan.risk,
            mode=mode,
            approved_at_utc=format_utc(current),
        )
        save_approval(self.root, approval)
        save_state(
            self.root,
            OperationState(
                operation_id=operation_id,
                status="approved",
                risk=plan.risk,
                mutates=plan.mutates,
                plan_sha256=plan.plan_sha256,
                updated_at_utc=format_utc(current),
            ),
        )
        self._event(
            plan,
            "approval.granted",
            now=current,
            attributes={"mode": approval.mode},
        )
        return approval

    def authorize(
        self,
        operation_id: str,
        *,
        desired: ExperimentDesiredState,
        observed: ObservedState,
        bound_inputs: Mapping[str, Mapping[str, object]] | None = None,
        now: datetime | None = None,
    ) -> ExecutionPermit:
        """Reconcile again, reject drift, and acquire exclusive mutation authority."""

        current = (now or utc_now()).astimezone(timezone.utc)
        plan = load_plan(self.root, operation_id)
        state = load_state(self.root, operation_id)
        expected_status = "approved" if plan.approval_required else "planned"
        if state.status != expected_status:
            raise WorkspaceError("operation is not ready for authorization")
        reconciliation = plan_reconciliation(desired, observed, now=current)
        verify_plan_inputs(
            plan,
            desired=desired,
            observed=observed,
            reconciliation=reconciliation,
            bound_inputs=bound_inputs,
        )
        approval = load_approval(self.root, operation_id)
        verify_approval(plan, approval)

        claim_held = False
        if plan.mutates:
            acquire_mutation_claim(self.root, plan, format_utc(current))
            claim_held = True
        save_state(
            self.root,
            OperationState(
                operation_id=operation_id,
                status="running",
                risk=plan.risk,
                mutates=plan.mutates,
                plan_sha256=plan.plan_sha256,
                updated_at_utc=format_utc(current),
                claim_held=claim_held,
            ),
        )
        self._event(plan, "operation.authorized", now=current)
        return ExecutionPermit(
            operation_id=operation_id,
            experiment_id=plan.experiment_id,
            kind=plan.kind,
            risk=plan.risk,
            mutates=plan.mutates,
            plan_sha256=plan.plan_sha256,
            issued_at_utc=format_utc(current),
            targets=plan.targets,
        )

    def finish(
        self,
        operation_id: str,
        *,
        success: bool,
        now: datetime | None = None,
    ) -> OperationState:
        """Close a running operation; failed mutations retain their exclusive claim."""

        current = (now or utc_now()).astimezone(timezone.utc)
        plan = load_plan(self.root, operation_id)
        state = load_state(self.root, operation_id)
        if state.status != "running":
            raise WorkspaceError("only a running operation can be finished")
        if plan.mutates:
            require_mutation_claim(self.root, plan)

        if success:
            if plan.mutates:
                release_mutation_claim(self.root, plan)
            result = OperationState(
                operation_id=operation_id,
                status="completed",
                risk=plan.risk,
                mutates=plan.mutates,
                plan_sha256=plan.plan_sha256,
                updated_at_utc=format_utc(current),
                claim_held=False,
            )
            save_state(self.root, result)
            self._event(plan, "operation.completed", now=current)
            return result

        status = "recovery-required" if plan.mutates else "failed"
        result = OperationState(
            operation_id=operation_id,
            status=status,
            risk=plan.risk,
            mutates=plan.mutates,
            plan_sha256=plan.plan_sha256,
            updated_at_utc=format_utc(current),
            claim_held=plan.mutates,
        )
        save_state(self.root, result)
        self._event(plan, "operation.failed", now=current)
        if plan.mutates:
            self._event(plan, "recovery.required", now=current)
        return result

    def interrupt(
        self,
        operation_id: str,
        *,
        now: datetime | None = None,
    ) -> OperationState:
        """Record interruption without releasing a claim that may cover partial mutation."""

        current = (now or utc_now()).astimezone(timezone.utc)
        plan = load_plan(self.root, operation_id)
        state = load_state(self.root, operation_id)
        if state.status in {"completed", "failed", "recovery-required"}:
            raise WorkspaceError("operation is already terminal")

        claim_held = state.claim_held
        if claim_held:
            require_mutation_claim(self.root, plan)
        status = "recovery-required" if claim_held else "failed"
        result = OperationState(
            operation_id=operation_id,
            status=status,
            risk=plan.risk,
            mutates=plan.mutates,
            plan_sha256=plan.plan_sha256,
            updated_at_utc=format_utc(current),
            claim_held=claim_held,
        )
        save_state(self.root, result)
        self._event(plan, "operation.interrupted", now=current)
        if claim_held:
            self._event(plan, "recovery.required", now=current)
        return result
