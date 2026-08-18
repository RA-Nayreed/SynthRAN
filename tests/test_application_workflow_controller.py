from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from synthran.app import ApplicationController
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import Profile, format_utc
from synthran.workspace.observed import Observation
from synthran.workspace.store import initialize_workspace, save_profile


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)


def live(
    dimension: str,
    *,
    ownership: str = "synthran",
    resource_id: str | None = None,
    running: bool | None = None,
) -> Observation:
    return Observation(
        dimension=dimension,
        state="ready",
        source="provider",
        observed_at_utc=format_utc(NOW),
        fresh_until_utc=format_utc(NOW + timedelta(minutes=10)),
        ownership=ownership,
        resource_id=resource_id,
        facts={} if running is None else {"running": running},
    )


def authority() -> dict[str, list[Observation]]:
    return {
        "controller": [live("controller", ownership="operator")],
        "project_access": [live("project_access", ownership="operator")],
        "provider_experiment": [
            live("provider_experiment", ownership="operator", resource_id="provider-exp-01")
        ],
    }


class ApplicationWorkflowControllerTests(unittest.TestCase):
    def _controller(self, base: Path) -> ApplicationController:
        root = base / "repo"
        root.mkdir()
        config_home = base / "config"
        environment = {"SYNTHRAN_CONFIG_HOME": str(config_home)}
        save_profile(
            Profile(
                name="controller",
                created_at_utc=format_utc(NOW),
                updated_at_utc=format_utc(NOW),
                slices_username="operator",
            ),
            environment=environment,
        )
        initialize_workspace(
            root=root,
            profile="controller",
            project="research-project",
            now=NOW,
        )
        controller = ApplicationController(start=root, environment=environment)
        controller.create_experiment(
            desired=ExperimentDesiredState.recommended(intent="iot-to-5g"),
            slices_experiment="provider-exp-01",
            now=NOW,
        )
        return controller

    def test_run_workflow_uses_shared_approval_authorization_and_claim_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            controller = self._controller(Path(temporary))
            controller.record_observations(
                {
                    **authority(),
                    "path": [live("path", resource_id="accepted-path")],
                },
                now=NOW,
            )

            plan = controller.begin_workflow_operation("run-baseline", now=NOW)
            self.assertEqual(plan.kind, "run-baseline")
            self.assertEqual(plan.risk, "R2")
            controller.approve_operation(plan.operation_id, now=NOW)
            permit = controller.authorize_operation(plan.operation_id, now=NOW)
            self.assertEqual(permit.operation_id, plan.operation_id)
            self.assertTrue(permit.mutates)
            state = controller.finish_operation(plan.operation_id, success=True, now=NOW)
            self.assertEqual(state.status, "completed")

    def test_collect_workflow_is_read_only_and_needs_no_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            controller = self._controller(Path(temporary))
            controller.record_observations(
                {
                    **authority(),
                    "path": [live("path", resource_id="accepted-path")],
                },
                now=NOW,
            )

            plan = controller.begin_workflow_operation("collect", now=NOW)
            self.assertEqual(plan.risk, "R1")
            self.assertFalse(plan.approval_required)
            permit = controller.authorize_operation(plan.operation_id, now=NOW)
            self.assertFalse(permit.mutates)
            controller.finish_operation(plan.operation_id, success=True, now=NOW)

    def test_down_plan_binds_exact_targets_and_requires_destructive_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            controller = self._controller(Path(temporary))
            controller.record_observations(
                {
                    **authority(),
                    "path": [live("path", resource_id="accepted-path")],
                    "reservation": [
                        live(
                            "reservation",
                            ownership="operator",
                            resource_id="reservation-17",
                        )
                    ],
                    "allocation": [live("allocation", resource_id="allocation-42")],
                    "core": [live("core", resource_id="core-node-f2")],
                    "ran": [live("ran", resource_id="ran-node-f3")],
                },
                now=NOW,
            )

            plan = controller.begin_workflow_operation("down", now=NOW)
            self.assertEqual(plan.risk, "R3")
            self.assertEqual(
                plan.targets,
                ("allocation-42", "core-node-f2", "ran-node-f3"),
            )
            controller.approve_operation(
                plan.operation_id,
                destructive=True,
                now=NOW,
            )
            permit = controller.authorize_operation(plan.operation_id, now=NOW)
            self.assertEqual(permit.targets, plan.targets)
            controller.finish_operation(plan.operation_id, success=True, now=NOW)


if __name__ == "__main__":
    unittest.main()
