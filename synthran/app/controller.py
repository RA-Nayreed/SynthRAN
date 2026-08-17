"""Shared application controller for terminal and scripted interfaces."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Mapping

from synthran.app.model import ApplicationSnapshot, DimensionView
from synthran.app.workflows import plan_workflow
from synthran.operations import (
    ApprovalGrant,
    ExecutionPermit,
    OperationController,
    OperationEvent,
    OperationPlan,
    OperationState,
    load_operation_events,
    load_plan,
    select_reconciliation_step,
)
from synthran.resources import (
    ResourceDecision,
    ResourceInventory,
    ResourceProviderAdapter,
    ResourceTransactionResult,
    build_resource_decision,
    execute_resource_transaction,
    validate_resource_adapters,
)
from synthran.workspace.context import WorkspaceAuthorityContext, resolve_workspace_authority
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.desired_store import load_desired_state
from synthran.workspace.experiment_service import create_desired_experiment
from synthran.workspace.model import ExperimentRecord, WorkspaceError, utc_now
from synthran.workspace.observed import Observation, ObservedState, reconcile_observation_sets
from synthran.workspace.observed_store import load_observed_state, observed_state_path, save_observed_state
from synthran.workspace.reconciliation import derive_lifecycle, plan_reconciliation
from synthran.workspace.registry import WorkspaceRegistry


RESOURCE_BOUND_MUTATIONS = frozenset({"reserve", "allocate", "prepare", "up"})
RESOURCE_DECISION_INPUT = "resource_decision"


class ApplicationController:
    """Coordinate durable state and operation policy without duplicating provider logic."""

    def __init__(
        self,
        *,
        start: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.environment = dict(environment) if environment is not None else dict(os.environ)
        self.authority = resolve_workspace_authority(
            start=start,
            environment=self.environment,
        )
        self.root = self.authority.root
        self.registry = WorkspaceRegistry(self.root)
        self.operations = OperationController(self.root)

    def reload_authority(self) -> WorkspaceAuthorityContext:
        self.authority = resolve_workspace_authority(
            start=self.root,
            environment=self.environment,
        )
        return self.authority

    def create_experiment(
        self,
        *,
        desired: ExperimentDesiredState,
        label: str | None = None,
        slices_experiment: str | None = None,
        activate: bool = True,
        now: datetime | None = None,
    ) -> ExperimentRecord:
        """Create a detailed experiment using the initialized workspace identity."""

        current = (now or utc_now()).astimezone(timezone.utc)
        record = create_desired_experiment(
            self.registry,
            profile=self.authority.profile.name,
            project=self.authority.workspace.project,
            desired=desired,
            label=label,
            slices_experiment=slices_experiment,
            activate=activate,
            now=current,
        )
        if activate:
            self.reload_authority()
        return record

    def _active_record(self) -> ExperimentRecord | None:
        self.reload_authority()
        return self.authority.active_experiment

    def _active_desired(self) -> tuple[ExperimentRecord, ExperimentDesiredState]:
        record = self._active_record()
        if record is None:
            raise WorkspaceError("workspace has no active experiment")
        desired = load_desired_state(self.root, record.experiment_id)
        return record, desired

    def _active_observed(
        self,
        *,
        now: datetime,
        allow_empty: bool,
    ) -> ObservedState:
        record = self._active_record()
        if record is None:
            raise WorkspaceError("workspace has no active experiment")
        path = observed_state_path(self.root, record.experiment_id)
        if path.is_file():
            return load_observed_state(self.root, record.experiment_id)
        if not allow_empty:
            raise WorkspaceError("active experiment has no observed-state snapshot")
        return ObservedState(
            experiment_id=record.experiment_id,
            collected_at_utc=now.isoformat().replace("+00:00", "Z"),
            observations=(),
        )

    def record_observations(
        self,
        observations: Mapping[str, tuple[Observation, ...] | list[Observation]],
        *,
        now: datetime | None = None,
    ) -> ObservedState:
        """Truth-rank provider-specific observations and persist only the reconciled cache."""

        current = (now or utc_now()).astimezone(timezone.utc)
        record, _ = self._active_desired()
        state = reconcile_observation_sets(
            experiment_id=record.experiment_id,
            observations=observations,
            now=current,
        )
        save_observed_state(self.root, state)
        return state

    def resource_decision(
        self,
        inventory: ResourceInventory,
        *,
        now: datetime | None = None,
    ) -> ResourceDecision:
        """Select exact resources from fresh provider inventory without mutation."""

        current = (now or utc_now()).astimezone(timezone.utc)
        _, desired = self._active_desired()
        return build_resource_decision(desired, inventory, now=current)

    def snapshot(self, *, now: datetime | None = None) -> ApplicationSnapshot:
        """Return a local status projection; this method performs no provider mutation."""

        current = (now or utc_now()).astimezone(timezone.utc)
        self.reload_authority()
        record = self.authority.active_experiment
        if record is None:
            return ApplicationSnapshot(
                workspace_root=str(self.root),
                profile=self.authority.profile.name,
                project=self.authority.workspace.project,
                experiment_id=None,
                provider_experiment=None,
                intent=None,
                radio_mode=None,
                lifecycle="EMPTY",
            )

        desired = load_desired_state(self.root, record.experiment_id)
        observed = self._active_observed(now=current, allow_empty=True)
        reconciliation = plan_reconciliation(
            desired,
            observed,
            provider_experiment_required=record.slices_experiment is not None,
            now=current,
        )
        lifecycle = derive_lifecycle(desired, observed, now=current)
        if reconciliation.blocks:
            lifecycle = "BLOCKED"

        dimensions = tuple(
            DimensionView(
                name=item.dimension,
                state=item.state,
                fresh=item.is_fresh(current),
                source=item.source,
                ownership=item.ownership,
                detail=item.detail,
            )
            for item in observed.observations
        )
        return ApplicationSnapshot(
            workspace_root=str(self.root),
            profile=self.authority.profile.name,
            project=self.authority.workspace.project,
            experiment_id=record.experiment_id,
            provider_experiment=record.slices_experiment,
            intent=desired.intent,
            radio_mode=desired.radio.mode,
            lifecycle=lifecycle,
            observations=dimensions,
            next_steps=tuple(step.name for step in reconciliation.steps),
            blocks=reconciliation.blocks,
        )

    def begin_operation(
        self,
        *,
        step_name: str | None = None,
        inventory: ResourceInventory | None = None,
        now: datetime | None = None,
    ) -> OperationPlan:
        """Create the next operation and bind exact resources for placement mutations."""

        current = (now or utc_now()).astimezone(timezone.utc)
        record, desired = self._active_desired()
        if record.slices_experiment is None:
            raise WorkspaceError(
                "active experiment has no provider experiment binding; bind one before live control"
            )
        observed = self._active_observed(now=current, allow_empty=False)
        reconciliation = plan_reconciliation(desired, observed, now=current)
        step = select_reconciliation_step(reconciliation, step_name)

        targets: tuple[str, ...] = ()
        bound_inputs: Mapping[str, Mapping[str, object]] | None = None
        if step.name in RESOURCE_BOUND_MUTATIONS:
            if inventory is None:
                raise WorkspaceError(
                    f"operation {step.name} requires fresh complete resource inventory"
                )
            decision = build_resource_decision(desired, inventory, now=current)
            targets = decision.targets
            bound_inputs = {RESOURCE_DECISION_INPUT: decision.to_dict()}

        return self.operations.begin(
            desired=desired,
            observed=observed,
            step_name=step.name,
            targets=targets,
            bound_inputs=bound_inputs,
            now=current,
        )

    def begin_workflow_operation(
        self,
        workflow: str,
        *,
        now: datetime | None = None,
    ) -> OperationPlan:
        """Plan one non-reconciliation application workflow through the same operation engine."""

        current = (now or utc_now()).astimezone(timezone.utc)
        record, desired = self._active_desired()
        if record.slices_experiment is None:
            raise WorkspaceError(
                "active experiment has no provider experiment binding; bind one before live control"
            )
        observed = self._active_observed(now=current, allow_empty=False)
        policy = plan_workflow(desired, observed, workflow, now=current)
        return self.operations.begin(
            desired=desired,
            observed=observed,
            step_name=workflow,
            policy_report=policy,
            now=current,
        )

    def approve_operation(
        self,
        operation_id: str,
        *,
        destructive: bool = False,
        now: datetime | None = None,
    ) -> ApprovalGrant:
        return self.operations.approve(
            operation_id,
            mode="destructive" if destructive else "standard",
            now=now,
        )

    def authorize_operation(
        self,
        operation_id: str,
        *,
        inventory: ResourceInventory | None = None,
        now: datetime | None = None,
    ) -> ExecutionPermit:
        """Authorize against current persisted state and any operation-bound resource decision."""

        current = (now or utc_now()).astimezone(timezone.utc)
        record, desired = self._active_desired()
        observed = self._active_observed(now=current, allow_empty=False)
        if observed.experiment_id != record.experiment_id:
            raise WorkspaceError("active observed state belongs to another experiment")

        plan = load_plan(self.root, operation_id)
        bound_inputs: Mapping[str, Mapping[str, object]] | None = None
        if RESOURCE_DECISION_INPUT in plan.input_sha256:
            if inventory is None:
                raise WorkspaceError(
                    "operation authorization requires fresh complete resource inventory"
                )
            decision = build_resource_decision(desired, inventory, now=current)
            if decision.targets != plan.targets:
                raise WorkspaceError(
                    "resource placement changed after approval; create a new operation"
                )
            bound_inputs = {RESOURCE_DECISION_INPUT: decision.to_dict()}

        return self.operations.authorize(
            operation_id,
            desired=desired,
            observed=observed,
            bound_inputs=bound_inputs,
            now=current,
        )

    def execute_resource_operation(
        self,
        operation_id: str,
        *,
        inventory: ResourceInventory,
        adapters: Mapping[str, ResourceProviderAdapter],
        now: datetime | None = None,
    ) -> ResourceTransactionResult:
        """Authorize and execute one resource-bound operation through exact provider adapters."""

        current = (now or utc_now()).astimezone(timezone.utc)
        plan = load_plan(self.root, operation_id)
        if RESOURCE_DECISION_INPUT not in plan.input_sha256:
            raise WorkspaceError("operation is not bound to a resource decision")
        decision = self.resource_decision(inventory, now=current)
        if decision.targets != plan.targets:
            raise WorkspaceError(
                "resource placement changed after approval; create a new operation"
            )
        validate_resource_adapters(decision, adapters)
        permit = self.authorize_operation(
            operation_id,
            inventory=inventory,
            now=current,
        )

        try:
            result = execute_resource_transaction(
                permit=permit,
                decision=decision,
                adapters=adapters,
            )
        except Exception:
            self.interrupt_operation(operation_id, now=current)
            raise

        if result.status == "ready":
            self.finish_operation(operation_id, success=True, now=current)
        elif result.status == "rolled-back":
            self.finish_operation(
                operation_id,
                success=False,
                recovered=True,
                now=current,
            )
        else:
            self.finish_operation(operation_id, success=False, now=current)
        return result

    def operation_events(self, operation_id: str) -> tuple[OperationEvent, ...]:
        """Return the validated operation event stream for terminal rendering."""

        return load_operation_events(self.root, operation_id)

    def finish_operation(
        self,
        operation_id: str,
        *,
        success: bool,
        recovered: bool = False,
        now: datetime | None = None,
    ) -> OperationState:
        return self.operations.finish(
            operation_id,
            success=success,
            recovered=recovered,
            now=now,
        )

    def interrupt_operation(
        self,
        operation_id: str,
        *,
        now: datetime | None = None,
    ) -> OperationState:
        return self.operations.interrupt(operation_id, now=now)
