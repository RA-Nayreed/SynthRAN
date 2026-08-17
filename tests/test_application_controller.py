from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from synthran.app import ApplicationController
from synthran.resources import (
    ProviderResourceSnapshot,
    ResourceInventory,
    ResourceState,
    reviewed_resource_descriptors,
)
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import Profile, WorkspaceError, format_utc
from synthran.workspace.observed import Observation
from synthran.workspace.store import initialize_workspace, save_profile


UTC = timezone.utc
NOW = datetime(2026, 8, 17, 19, 0, tzinfo=UTC)


def live(
    dimension: str,
    state: str = "ready",
    *,
    ownership: str = "operator",
) -> Observation:
    return Observation(
        dimension=dimension,
        state=state,
        source="provider",
        observed_at_utc=format_utc(NOW),
        fresh_until_utc=format_utc(NOW + timedelta(minutes=10)),
        ownership=ownership,
    )


def current_inventory() -> ResourceInventory:
    descriptors = reviewed_resource_descriptors()
    compute = [
        item.resource_id
        for item in descriptors
        if item.provider == "slices" and item.kind == "compute"
    ]
    return ResourceInventory(
        descriptors=descriptors,
        snapshots=(
            ProviderResourceSnapshot(
                provider="slices",
                observed_at_utc=format_utc(NOW),
                fresh_until_utc=format_utc(NOW + timedelta(minutes=10)),
                complete=True,
                resources=tuple(
                    ResourceState(item, "available", "unowned")
                    for item in compute
                ),
            ),
        ),
    )


class ApplicationControllerTests(unittest.TestCase):
    def _controller(self, base: Path) -> tuple[Path, ApplicationController]:
        root = base / "repo"
        root.mkdir()
        config_home = base / "config"
        save_profile(
            Profile(
                name="controller",
                created_at_utc=format_utc(NOW),
                updated_at_utc=format_utc(NOW),
                slices_username="operator",
            ),
            environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
        )
        initialize_workspace(
            root=root,
            profile="controller",
            project="research-project",
            now=NOW,
        )
        controller = ApplicationController(
            start=root,
            environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
        )
        return root, controller

    def test_empty_workspace_has_truthful_empty_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, controller = self._controller(Path(temporary))
            status = controller.snapshot(now=NOW)
            self.assertEqual(status.lifecycle, "EMPTY")
            self.assertIsNone(status.experiment_id)
            self.assertEqual(status.project, "research-project")
            self.assertEqual(status.next_steps, ())

    def test_created_experiment_uses_workspace_identity_and_detailed_desired_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, controller = self._controller(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            record = controller.create_experiment(
                desired=desired,
                label="baseline network",
                slices_experiment="provider-exp-01",
                now=NOW,
            )
            status = controller.snapshot(now=NOW)
            self.assertEqual(status.experiment_id, record.experiment_id)
            self.assertEqual(status.provider_experiment, "provider-exp-01")
            self.assertEqual(status.intent, "virtual-5g")
            self.assertEqual(status.radio_mode, "virtual")
            self.assertEqual(status.lifecycle, "CONFIGURED")
            self.assertEqual(
                status.next_steps,
                (
                    "inspect-controller",
                    "inspect-project-access",
                    "inspect-provider-experiment",
                ),
            )

    def test_recorded_observations_drive_same_reconciliation_used_by_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, controller = self._controller(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            controller.create_experiment(
                desired=desired,
                slices_experiment="provider-exp-01",
                now=NOW,
            )
            controller.record_observations(
                {
                    "controller": [live("controller")],
                    "project_access": [live("project_access")],
                    "provider_experiment": [live("provider_experiment")],
                    "reservation": [
                        live("reservation", state="absent", ownership="unowned")
                    ],
                },
                now=NOW,
            )
            status = controller.snapshot(now=NOW)
            self.assertEqual(status.next_steps, ("reserve",))

            inventory = current_inventory()
            plan = controller.begin_operation(inventory=inventory, now=NOW)
            self.assertEqual(plan.kind, "reserve")
            self.assertEqual(plan.risk, "R2")
            self.assertTrue(plan.targets)
            controller.approve_operation(plan.operation_id, now=NOW)
            permit = controller.authorize_operation(
                plan.operation_id,
                inventory=inventory,
                now=NOW,
            )
            self.assertEqual(permit.operation_id, plan.operation_id)
            self.assertEqual(permit.targets, plan.targets)
            state = controller.finish_operation(
                plan.operation_id,
                success=True,
                now=NOW,
            )
            self.assertEqual(state.status, "completed")

    def test_snapshot_marks_stale_observations_as_not_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, controller = self._controller(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            controller.create_experiment(
                desired=desired,
                slices_experiment="provider-exp-01",
                now=NOW,
            )
            controller.record_observations(
                {
                    "controller": [live("controller")],
                    "project_access": [live("project_access")],
                    "provider_experiment": [live("provider_experiment")],
                    "reservation": [live("reservation")],
                },
                now=NOW,
            )
            status = controller.snapshot(now=NOW + timedelta(minutes=11))
            self.assertTrue(status.observations)
            self.assertFalse(any(item.fresh for item in status.observations))
            self.assertIn("inspect-controller", status.next_steps)

    def test_live_operation_requires_a_durable_provider_experiment_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, controller = self._controller(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            controller.create_experiment(desired=desired, now=NOW)
            controller.record_observations(
                {
                    "controller": [live("controller")],
                    "project_access": [live("project_access")],
                    "reservation": [
                        live("reservation", state="absent", ownership="unowned")
                    ],
                },
                now=NOW,
            )
            with self.assertRaises(WorkspaceError):
                controller.begin_operation(now=NOW)

    def test_new_active_experiment_replaces_only_active_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, controller = self._controller(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            first = controller.create_experiment(
                desired=desired,
                slices_experiment="provider-exp-01",
                now=NOW,
            )
            second = controller.create_experiment(
                desired=desired,
                slices_experiment="provider-exp-02",
                now=NOW + timedelta(minutes=1),
            )
            status = controller.snapshot(now=NOW + timedelta(minutes=1))
            self.assertNotEqual(first.experiment_id, second.experiment_id)
            self.assertEqual(status.experiment_id, second.experiment_id)
            self.assertEqual(status.provider_experiment, "provider-exp-02")


if __name__ == "__main__":
    unittest.main()
