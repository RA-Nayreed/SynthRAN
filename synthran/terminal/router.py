"""Route terminal dispatch requests through the shared application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from synthran.app.controller import ApplicationController, RESOURCE_BOUND_MUTATIONS
from synthran.operations.model import OperationPlan
from synthran.resources.model import ResourceInventory
from synthran.terminal.commands import CommandRequest, TerminalCommandError
from synthran.workspace.model import WorkspaceError


DISPATCH_COMMANDS = frozenset(
    {
        "/reserve",
        "/up",
        "/verify",
        "/recover",
        "/down",
        "/run",
        "/stop",
        "/collect",
        "/logs",
        "/config",
    }
)


@dataclass(frozen=True)
class DispatchResult:
    """Safe terminal-facing result from one routed application request."""

    lines: tuple[str, ...]
    operation_id: str | None = None
    error: bool = False

    def __post_init__(self) -> None:
        if not self.lines:
            raise TerminalCommandError("dispatch result must contain at least one line")
        if any(
            not isinstance(line, str)
            or not line
            or len(line) > 1024
            or any(character in "\r\n\x00" for character in line)
            for line in self.lines
        ):
            raise TerminalCommandError("dispatch result contains an unsafe terminal line")


class InventorySource(Protocol):
    def __call__(self) -> ResourceInventory: ...


class TerminalCommandRouter:
    """Map strict terminal commands to application workflows without provider shortcuts."""

    def __init__(
        self,
        application: ApplicationController,
        *,
        inventory_source: InventorySource | None = None,
    ) -> None:
        self.application = application
        self.inventory_source = inventory_source

    def _error(self, message: str) -> DispatchResult:
        return DispatchResult((message,), error=True)

    def _inventory_for(self, step_name: str) -> ResourceInventory | None:
        if step_name not in RESOURCE_BOUND_MUTATIONS:
            return None
        if self.inventory_source is None:
            raise WorkspaceError(
                "fresh provider inventory is required for this operation, but no terminal inventory adapter is configured"
            )
        return self.inventory_source()

    @staticmethod
    def _plan_lines(plan: OperationPlan) -> tuple[str, ...]:
        approval = (
            "destructive"
            if plan.risk == "R3"
            else "standard"
            if plan.approval_required
            else "none"
        )
        return (
            f"Operation {plan.operation_id}: {plan.kind} [{plan.risk}]",
            f"Approval required: {approval}",
            "Execution: not started",
        )

    def _plan_exact(self, step_name: str) -> DispatchResult:
        inventory = self._inventory_for(step_name)
        plan = self.application.begin_operation(
            step_name=step_name,
            inventory=inventory,
        )
        return DispatchResult(self._plan_lines(plan), operation_id=plan.operation_id)

    def _plan_workflow(self, workflow: str) -> DispatchResult:
        plan = self.application.begin_workflow_operation(workflow)
        return DispatchResult(self._plan_lines(plan), operation_id=plan.operation_id)

    def _plan_up(self) -> DispatchResult:
        snapshot = self.application.snapshot()
        if snapshot.blocks:
            raise WorkspaceError("workspace is blocked; inspect status before requesting /up")
        if not snapshot.next_steps:
            return DispatchResult(("Network already has no pending reconciliation action.",))
        if len(snapshot.next_steps) != 1:
            raise WorkspaceError(
                "current reconciliation has multiple read-only actions; inspect status and resolve them first"
            )
        step_name = snapshot.next_steps[0]
        if step_name == "verify-path":
            return DispatchResult(("Network is ready; use /verify to prove the end-to-end path.",))
        if step_name not in {"reserve", "allocate", "prepare", "up"}:
            raise WorkspaceError(
                f"/up cannot execute current reconciliation action {step_name}; use /status"
            )
        return self._plan_exact(step_name)

    def _plan_recovery(self) -> DispatchResult:
        snapshot = self.application.snapshot()
        candidates = tuple(
            step for step in snapshot.next_steps if step.startswith("recover-")
        )
        if len(candidates) != 1:
            raise WorkspaceError(
                "no single SynthRAN-owned recovery action is currently planable; inspect status first"
            )
        return self._plan_exact(candidates[0])

    def _config(self, topic: str) -> DispatchResult:
        snapshot = self.application.snapshot()
        if topic == "resources":
            workspace = self.application.authority.workspace
            return DispatchResult(
                (
                    f"Project: {workspace.project}",
                    f"Placement: {workspace.placement}",
                    f"Reservation minutes: {workspace.reservation_minutes}",
                    f"Ownership policy: {workspace.ownership}",
                    f"Radio mode: {snapshot.radio_mode or '—'}",
                )
            )
        if topic == "experiment":
            if snapshot.experiment_id is None:
                return DispatchResult(("No active experiment.",))
            return DispatchResult(
                (
                    f"Experiment: {snapshot.experiment_id}",
                    f"Provider experiment: {snapshot.provider_experiment or '—'}",
                    f"Intent: {snapshot.intent or '—'}",
                    f"Radio mode: {snapshot.radio_mode or '—'}",
                    f"Lifecycle: {snapshot.lifecycle}",
                )
            )
        raise TerminalCommandError("config topic is unsupported")

    def dispatch(self, request: CommandRequest) -> DispatchResult:
        """Dispatch one already-parsed request through application policy."""

        if request.name not in DISPATCH_COMMANDS:
            raise TerminalCommandError(
                f"terminal command {request.name} is not a routed workflow command"
            )
        try:
            if request.name == "/config":
                assert request.subcommand is not None
                return self._config(request.subcommand)
            if request.name == "/reserve":
                return self._plan_exact("reserve")
            if request.name == "/up":
                return self._plan_up()
            if request.name == "/verify":
                return self._plan_exact("verify-path")
            if request.name == "/recover":
                return self._plan_recovery()
            if request.name == "/down":
                return self._plan_workflow("down")
            if request.name == "/run":
                assert request.subcommand is not None
                return self._plan_workflow(f"run-{request.subcommand}")
            if request.name == "/stop":
                return self._plan_workflow("stop")
            if request.name == "/collect":
                return self._plan_workflow("collect")
            if request.name == "/logs":
                assert request.subcommand is not None
                return self._plan_workflow(f"logs-{request.subcommand}")
        except WorkspaceError as exc:
            return self._error(str(exc))
        raise AssertionError("unreachable terminal dispatch")
