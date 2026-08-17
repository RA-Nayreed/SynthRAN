from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from synthran.app import ApplicationController
from synthran.operations import active_mutation_path, load_state
from synthran.resources import (
    AcquisitionReceipt,
    ProviderResourceSnapshot,
    ReleaseReceipt,
    ResourceInventory,
    ResourceState,
    ResourceTransactionError,
    reviewed_resource_descriptors,
)
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import Profile, format_utc
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


def inventory() -> ResourceInventory:
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
                    ResourceState(item, "available", "unowned") for item in compute
                ),
            ),
        ),
    )


@dataclass
class SlicesAdapter:
    provider: str = "slices"
    acquire_status: str = "ready"
    acquire_raises: bool = False

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def acquire(self, resource_ids, permit):
        resources = tuple(resource_ids)
        self.calls.append(("acquire", resources))
        if self.acquire_raises:
            raise RuntimeError("private provider details")
        created = resources if self.acquire_status == "ready" else resources[:1]
        return AcquisitionReceipt(
            provider="slices",
            requested_ids=resources,
            created_ids=created,
            status=self.acquire_status,
        )

    def release(self, resource_ids, permit):
        resources = tuple(resource_ids)
        self.calls.append(("release", resources))
        return ReleaseReceipt(
            provider="slices",
            requested_ids=resources,
            released_ids=resources,
            status="ready",
        )


class ResourceTransactionApplicationTests(unittest.TestCase):
    def _approved_operation(
        self,
        base: Path,
    ) -> tuple[Path, ApplicationController, str, ResourceInventory]:
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
        controller.create_experiment(
            desired=ExperimentDesiredState.recommended(intent="virtual-5g"),
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
        current = inventory()
        plan = controller.begin_operation(inventory=current, now=NOW)
        controller.approve_operation(plan.operation_id, now=NOW)
        return root, controller, plan.operation_id, current

    def test_successful_transaction_completes_operation_and_releases_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, controller, operation_id, current = self._approved_operation(
                Path(temporary)
            )
            adapter = SlicesAdapter()
            result = controller.execute_resource_operation(
                operation_id,
                inventory=current,
                adapters={"slices": adapter},
                now=NOW,
            )
            self.assertEqual(result.status, "ready")
            self.assertEqual(load_state(root, operation_id).status, "completed")
            self.assertFalse(active_mutation_path(root).exists())

    def test_clean_provider_failure_rolls_back_and_releases_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, controller, operation_id, current = self._approved_operation(
                Path(temporary)
            )
            adapter = SlicesAdapter(acquire_status="failed")
            result = controller.execute_resource_operation(
                operation_id,
                inventory=current,
                adapters={"slices": adapter},
                now=NOW,
            )
            self.assertEqual(result.status, "rolled-back")
            state = load_state(root, operation_id)
            self.assertEqual(state.status, "failed")
            self.assertFalse(state.claim_held)
            self.assertFalse(active_mutation_path(root).exists())
            self.assertEqual(adapter.calls[-1][0], "release")

    def test_unknown_provider_failure_retains_claim_for_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, controller, operation_id, current = self._approved_operation(
                Path(temporary)
            )
            adapter = SlicesAdapter(acquire_raises=True)
            result = controller.execute_resource_operation(
                operation_id,
                inventory=current,
                adapters={"slices": adapter},
                now=NOW,
            )
            self.assertEqual(result.status, "recovery-required")
            state = load_state(root, operation_id)
            self.assertEqual(state.status, "recovery-required")
            self.assertTrue(state.claim_held)
            self.assertTrue(active_mutation_path(root).is_file())

    def test_missing_adapter_fails_before_operation_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, controller, operation_id, current = self._approved_operation(
                Path(temporary)
            )
            with self.assertRaises(ResourceTransactionError):
                controller.execute_resource_operation(
                    operation_id,
                    inventory=current,
                    adapters={},
                    now=NOW,
                )
            self.assertEqual(load_state(root, operation_id).status, "approved")
            self.assertFalse(active_mutation_path(root).exists())


if __name__ == "__main__":
    unittest.main()
