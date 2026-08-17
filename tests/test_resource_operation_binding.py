from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from synthran.app import ApplicationController
from synthran.operations import OperationController
from synthran.resources import (
    ProviderResourceSnapshot,
    ResourceInventory,
    ResourceSelectionError,
    ResourceState,
    build_resource_decision,
    reviewed_resource_descriptors,
)
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import Profile, WorkspaceError, format_utc
from synthran.workspace.observed import Observation, ObservedState
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
        fresh_until_utc=format_utc(NOW + timedelta(minutes=30)),
        ownership=ownership,
    )


def resource_inventory(
    *,
    observed_at: datetime = NOW,
    minutes: int = 10,
    complete: bool = True,
    unavailable: set[str] | None = None,
    ownership: dict[str, str] | None = None,
) -> ResourceInventory:
    unavailable = unavailable or set()
    ownership = ownership or {}
    descriptors = reviewed_resource_descriptors()
    compute = [
        item.resource_id
        for item in descriptors
        if item.provider == "slices" and item.kind == "compute"
    ]
    states: list[ResourceState] = []
    for resource_id in compute:
        owner = ownership.get(resource_id, "unowned")
        if resource_id in unavailable:
            availability = "unavailable"
        elif owner in {"synthran", "operator", "other"}:
            availability = "allocated"
        else:
            availability = "available"
        states.append(ResourceState(resource_id, availability, owner))
    return ResourceInventory(
        descriptors=descriptors,
        snapshots=(
            ProviderResourceSnapshot(
                provider="slices",
                observed_at_utc=format_utc(observed_at),
                fresh_until_utc=format_utc(observed_at + timedelta(minutes=minutes)),
                complete=complete,
                resources=tuple(states),
            ),
        ),
    )


class ResourceOperationBindingTests(unittest.TestCase):
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
        return root, controller

    def test_resource_decision_binds_selected_state_without_snapshot_timestamp(self) -> None:
        desired = ExperimentDesiredState.recommended(intent="virtual-5g")
        decision = build_resource_decision(
            desired,
            resource_inventory(),
            now=NOW,
        )
        payload = decision.to_dict()
        self.assertIn("sopnode-f2", decision.targets)
        self.assertIn("sopnode-f3", decision.targets)
        self.assertIn("virtual:rfsim", decision.targets)
        encoded = json.dumps(payload, sort_keys=True)
        self.assertNotIn("observed_at_utc", encoded)
        self.assertNotIn("fresh_until_utc", encoded)

    def test_mutating_plan_contains_exact_targets_and_only_decision_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, controller = self._controller(Path(temporary))
            plan = controller.begin_operation(
                inventory=resource_inventory(),
                now=NOW,
            )
            payload = plan.to_dict()
            encoded = json.dumps(payload, sort_keys=True)
            self.assertEqual(plan.kind, "reserve")
            self.assertEqual(
                plan.targets,
                ("sopnode-f2", "sopnode-f3", "virtual:rfsim"),
            )
            self.assertEqual(set(plan.input_sha256), {"resource_decision"})
            self.assertNotIn("availability", encoded)
            self.assertNotIn("ownership", encoded)
            plan_file = (
                root
                / ".synthran"
                / "operations"
                / plan.operation_id
                / "plan.json"
            ).read_text(encoding="utf-8")
            self.assertNotIn('"availability"', plan_file)
            self.assertNotIn('"ownership"', plan_file)

    def test_refresh_with_same_selected_state_keeps_approval_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, controller = self._controller(Path(temporary))
            initial = resource_inventory()
            plan = controller.begin_operation(inventory=initial, now=NOW)
            controller.approve_operation(plan.operation_id, now=NOW)

            refreshed = resource_inventory(
                observed_at=NOW + timedelta(minutes=1),
                minutes=10,
            )
            permit = controller.authorize_operation(
                plan.operation_id,
                inventory=refreshed,
                now=NOW + timedelta(minutes=1),
            )
            self.assertEqual(permit.targets, plan.targets)
            controller.finish_operation(
                plan.operation_id,
                success=True,
                now=NOW + timedelta(minutes=1),
            )

    def test_selected_resource_state_change_invalidates_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, controller = self._controller(Path(temporary))
            initial = resource_inventory()
            plan = controller.begin_operation(inventory=initial, now=NOW)
            controller.approve_operation(plan.operation_id, now=NOW)

            changed = resource_inventory(
                observed_at=NOW + timedelta(minutes=1),
                ownership={"sopnode-f2": "operator"},
            )
            with self.assertRaises(WorkspaceError):
                controller.authorize_operation(
                    plan.operation_id,
                    inventory=changed,
                    now=NOW + timedelta(minutes=1),
                )

    def test_selection_change_invalidates_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, controller = self._controller(Path(temporary))
            initial = resource_inventory()
            plan = controller.begin_operation(inventory=initial, now=NOW)
            controller.approve_operation(plan.operation_id, now=NOW)

            changed = resource_inventory(
                observed_at=NOW + timedelta(minutes=1),
                unavailable={"sopnode-f2"},
            )
            with self.assertRaisesRegex(
                WorkspaceError,
                "resource placement changed after approval",
            ):
                controller.authorize_operation(
                    plan.operation_id,
                    inventory=changed,
                    now=NOW + timedelta(minutes=1),
                )

    def test_stale_or_partial_inventory_cannot_create_resource_bound_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, controller = self._controller(Path(temporary))
            with self.assertRaises(ResourceSelectionError):
                controller.begin_operation(
                    inventory=resource_inventory(minutes=1),
                    now=NOW + timedelta(minutes=2),
                )
            with self.assertRaises(ResourceSelectionError):
                controller.begin_operation(
                    inventory=resource_inventory(complete=False),
                    now=NOW,
                )

    def test_missing_inventory_fails_before_mutating_plan_is_issued(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, controller = self._controller(Path(temporary))
            with self.assertRaisesRegex(
                WorkspaceError,
                "requires fresh complete resource inventory",
            ):
                controller.begin_operation(now=NOW)

    def test_plan_without_extra_bindings_keeps_legacy_unsigned_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            initialize_workspace(
                root=root,
                profile="default",
                project="research-project",
                now=NOW,
            )
            registry_desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            from synthran.workspace.registry import WorkspaceRegistry

            record = WorkspaceRegistry(root).create_experiment(
                profile="default",
                project="research-project",
                slices_experiment="provider-exp-01",
                network_intent="virtual-5g",
                radio_mode="virtual",
                now=NOW,
            )
            observed = ObservedState(
                experiment_id=record.experiment_id,
                collected_at_utc=format_utc(NOW),
                observations=tuple(
                    [
                        live("controller"),
                        live("project_access"),
                        live("provider_experiment"),
                        live("reservation", state="absent", ownership="unowned"),
                    ]
                ),
            )
            plan = OperationController(root).begin(
                desired=registry_desired,
                observed=observed,
                now=NOW,
            )
            unsigned = plan.unsigned_dict()
            self.assertNotIn("targets", unsigned)
            self.assertNotIn("input_sha256", unsigned)


if __name__ == "__main__":
    unittest.main()
