from __future__ import annotations

from types import SimpleNamespace
import unittest

from synthran.app.model import ApplicationSnapshot
from synthran.terminal.commands import parse_command
from synthran.terminal.router import TerminalCommandRouter


class FakePlan:
    def __init__(self, operation_id: str, kind: str, risk: str) -> None:
        self.operation_id = operation_id
        self.kind = kind
        self.risk = risk

    @property
    def approval_required(self) -> bool:
        return self.risk in {"R2", "R3"}


class FakeApplication:
    def __init__(self, *, next_steps: tuple[str, ...] = ()) -> None:
        self.next_steps = next_steps
        self.blocks: tuple[str, ...] = ()
        self.begin_calls: list[tuple[str | None, object | None]] = []
        self.workflow_calls: list[str] = []
        self.authority = SimpleNamespace(
            workspace=SimpleNamespace(
                project="research-project",
                placement="automatic",
                reservation_minutes=120,
                ownership="strict",
            )
        )

    def snapshot(self) -> ApplicationSnapshot:
        return ApplicationSnapshot(
            workspace_root="/workspace",
            profile="controller",
            project="research-project",
            experiment_id="sran-20260818-001",
            provider_experiment="provider-exp-01",
            intent="iot-to-5g",
            radio_mode="virtual",
            lifecycle="CONFIGURED",
            next_steps=self.next_steps,
            blocks=self.blocks,
        )

    def begin_operation(self, *, step_name=None, inventory=None):
        self.begin_calls.append((step_name, inventory))
        risk = "R1" if step_name == "verify-path" else "R2"
        return FakePlan("op-000001", step_name or "next", risk)

    def begin_workflow_operation(self, workflow: str):
        self.workflow_calls.append(workflow)
        risk = "R3" if workflow == "down" else "R1" if workflow.startswith("logs-") or workflow == "collect" else "R2"
        return FakePlan("op-000002", workflow, risk)


class TerminalRouterTests(unittest.TestCase):
    def test_config_resources_uses_workspace_authority(self) -> None:
        app = FakeApplication()
        result = TerminalCommandRouter(app).dispatch(parse_command("/config resources"))
        self.assertFalse(result.error)
        self.assertIn("Project: research-project", result.lines)
        self.assertIn("Placement: automatic", result.lines)

    def test_config_experiment_uses_truthful_snapshot(self) -> None:
        app = FakeApplication()
        result = TerminalCommandRouter(app).dispatch(parse_command("/config experiment"))
        self.assertFalse(result.error)
        self.assertIn("Experiment: sran-20260818-001", result.lines)
        self.assertIn("Intent: iot-to-5g", result.lines)

    def test_resource_bound_operation_fails_closed_without_inventory_adapter(self) -> None:
        app = FakeApplication(next_steps=("reserve",))
        result = TerminalCommandRouter(app).dispatch(parse_command("/reserve"))
        self.assertTrue(result.error)
        self.assertIn("fresh provider inventory", result.lines[0])
        self.assertEqual(app.begin_calls, [])

    def test_resource_bound_operation_receives_exact_fresh_inventory(self) -> None:
        app = FakeApplication(next_steps=("reserve",))
        inventory = object()
        result = TerminalCommandRouter(
            app,
            inventory_source=lambda: inventory,  # type: ignore[arg-type]
        ).dispatch(parse_command("/reserve"))
        self.assertFalse(result.error)
        self.assertEqual(result.operation_id, "op-000001")
        self.assertEqual(app.begin_calls, [("reserve", inventory)])
        self.assertIn("Approval required: standard", result.lines)
        self.assertIn("Execution: not started", result.lines)

    def test_up_plans_only_the_current_reconciliation_mutation(self) -> None:
        app = FakeApplication(next_steps=("allocate",))
        inventory = object()
        result = TerminalCommandRouter(
            app,
            inventory_source=lambda: inventory,  # type: ignore[arg-type]
        ).dispatch(parse_command("/up"))
        self.assertFalse(result.error)
        self.assertEqual(app.begin_calls, [("allocate", inventory)])

    def test_up_does_not_turn_path_verification_into_a_mutation(self) -> None:
        app = FakeApplication(next_steps=("verify-path",))
        result = TerminalCommandRouter(app).dispatch(parse_command("/up"))
        self.assertFalse(result.error)
        self.assertIn("use /verify", result.lines[0])
        self.assertEqual(app.begin_calls, [])

    def test_verify_uses_read_only_application_operation(self) -> None:
        app = FakeApplication(next_steps=("verify-path",))
        result = TerminalCommandRouter(app).dispatch(parse_command("/verify"))
        self.assertFalse(result.error)
        self.assertEqual(app.begin_calls, [("verify-path", None)])
        self.assertIn("Approval required: none", result.lines)

    def test_recover_requires_one_explicit_recovery_step(self) -> None:
        app = FakeApplication(next_steps=("recover-allocation",))
        result = TerminalCommandRouter(app).dispatch(parse_command("/recover"))
        self.assertFalse(result.error)
        self.assertEqual(app.begin_calls, [("recover-allocation", None)])

    def test_run_conditions_are_first_class_application_workflows(self) -> None:
        app = FakeApplication()
        baseline = TerminalCommandRouter(app).dispatch(parse_command("/run baseline"))
        congestion = TerminalCommandRouter(app).dispatch(parse_command("/run congestion"))
        self.assertFalse(baseline.error)
        self.assertFalse(congestion.error)
        self.assertEqual(app.workflow_calls, ["run-baseline", "run-congestion"])
        self.assertIn("Approval required: standard", baseline.lines)
        self.assertIn("Execution: not started", baseline.lines)

    def test_stop_collect_and_logs_are_routed_through_application_policy(self) -> None:
        app = FakeApplication()
        router = TerminalCommandRouter(app)
        stop = router.dispatch(parse_command("/stop"))
        collect = router.dispatch(parse_command("/collect"))
        logs = router.dispatch(parse_command("/logs ue"))
        self.assertFalse(stop.error)
        self.assertFalse(collect.error)
        self.assertFalse(logs.error)
        self.assertEqual(app.workflow_calls, ["stop", "collect", "logs-ue"])
        self.assertIn("Approval required: standard", stop.lines)
        self.assertIn("Approval required: none", collect.lines)
        self.assertIn("Approval required: none", logs.lines)

    def test_down_is_planned_as_destructive_application_workflow(self) -> None:
        app = FakeApplication()
        result = TerminalCommandRouter(app).dispatch(parse_command("/down"))
        self.assertFalse(result.error)
        self.assertEqual(app.workflow_calls, ["down"])
        self.assertIn("Approval required: destructive", result.lines)


if __name__ == "__main__":
    unittest.main()
