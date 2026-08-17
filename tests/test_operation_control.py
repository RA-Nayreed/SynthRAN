from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from synthran.operations import (
    ApprovalGrant,
    OperationController,
    active_mutation_path,
    load_plan,
    load_state,
    operation_events_path,
    session_events_path,
)
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import WorkspaceError
from synthran.workspace.observed import Observation, ObservedState
from synthran.workspace.records import load_operation_record
from synthran.workspace.registry import WorkspaceRegistry
from synthran.workspace.store import initialize_workspace


UTC = timezone.utc
NOW = datetime(2026, 8, 17, 19, 0, tzinfo=UTC)


def live(
    dimension: str,
    state: str = "ready",
    *,
    ownership: str = "operator",
    facts: dict[str, object] | None = None,
    minutes: int = 10,
) -> Observation:
    return Observation(
        dimension=dimension,
        state=state,
        source="provider",
        observed_at_utc="2026-08-17T19:00:00Z",
        fresh_until_utc=(NOW + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
        ownership=ownership,
        facts=facts or {},
    )


def authority_ready() -> list[Observation]:
    return [
        live("controller"),
        live("project_access"),
        live("provider_experiment"),
    ]


def resources_ready() -> list[Observation]:
    return [
        live("reservation"),
        live("allocation"),
        live("preparation", ownership="synthran"),
    ]


def network_ready() -> list[Observation]:
    return [
        live("kubernetes", ownership="synthran"),
        live("core", ownership="synthran"),
        live("ran", ownership="synthran"),
        live("ue", ownership="synthran"),
        live(
            "pdu",
            ownership="synthran",
            facts={"address": "203.0.113.77"},
        ),
        live("upf", ownership="synthran"),
        live("radio", ownership="synthran"),
    ]


def read_events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class OperationControlTests(unittest.TestCase):
    def _workspace(self, base: Path) -> tuple[Path, str, OperationController]:
        root = base / "repo"
        root.mkdir()
        initialize_workspace(root=root, profile="default", project="project", now=NOW)
        registry = WorkspaceRegistry(root)
        experiment = registry.create_experiment(
            profile="default",
            project="project",
            slices_experiment="provider-exp",
            network_intent="virtual-5g",
            radio_mode="virtual",
            now=NOW,
        )
        return root, experiment.experiment_id, OperationController(root)

    @staticmethod
    def _snapshot(experiment_id: str, *items: Observation) -> ObservedState:
        return ObservedState(
            experiment_id=experiment_id,
            collected_at_utc="2026-08-17T19:00:00Z",
            observations=tuple(items),
        )

    def test_r2_operation_persists_plan_state_and_approval_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, experiment_id, controller = self._workspace(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            observed = self._snapshot(
                experiment_id,
                *authority_ready(),
                live("reservation", state="absent", ownership="unowned"),
            )
            plan = controller.begin(desired=desired, observed=observed, now=NOW)

            self.assertEqual(plan.kind, "reserve")
            self.assertEqual(plan.risk, "R2")
            self.assertTrue(plan.mutates)
            self.assertEqual(load_plan(root, plan.operation_id), plan)
            self.assertEqual(load_state(root, plan.operation_id).status, "awaiting-approval")
            record = load_operation_record(root, plan.operation_id)
            self.assertEqual(record.experiment_id, experiment_id)
            self.assertEqual(record.kind, "reserve")
            events = read_events(operation_events_path(root, plan.operation_id))
            self.assertEqual(
                [event["event_type"] for event in events],
                ["operation.started", "plan.created", "approval.requested"],
            )

    def test_r2_cannot_authorize_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, experiment_id, controller = self._workspace(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            observed = self._snapshot(
                experiment_id,
                *authority_ready(),
                live("reservation", state="absent", ownership="unowned"),
            )
            plan = controller.begin(desired=desired, observed=observed, now=NOW)
            with self.assertRaises(WorkspaceError):
                controller.authorize(
                    plan.operation_id,
                    desired=desired,
                    observed=observed,
                    now=NOW,
                )

    def test_approval_is_bound_to_plan_and_state_drift_requires_replanning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, experiment_id, controller = self._workspace(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            observed = self._snapshot(
                experiment_id,
                *authority_ready(),
                live("reservation", state="absent", ownership="unowned"),
            )
            plan = controller.begin(desired=desired, observed=observed, now=NOW)
            approval = controller.approve(plan.operation_id, now=NOW)
            self.assertEqual(approval.plan_sha256, plan.plan_sha256)

            changed = self._snapshot(
                experiment_id,
                *authority_ready(),
                live("reservation", ownership="operator"),
            )
            with self.assertRaises(WorkspaceError):
                controller.authorize(
                    plan.operation_id,
                    desired=desired,
                    observed=changed,
                    now=NOW,
                )

    def test_expired_observations_cannot_authorize_an_old_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, experiment_id, controller = self._workspace(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            observed = self._snapshot(
                experiment_id,
                *authority_ready(),
                live("reservation", state="absent", ownership="unowned"),
            )
            plan = controller.begin(desired=desired, observed=observed, now=NOW)
            controller.approve(plan.operation_id, now=NOW)
            with self.assertRaises(WorkspaceError):
                controller.authorize(
                    plan.operation_id,
                    desired=desired,
                    observed=observed,
                    now=NOW + timedelta(minutes=11),
                )

    def test_only_one_mutating_operation_can_be_authorized_at_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, experiment_id, controller = self._workspace(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            observed = self._snapshot(
                experiment_id,
                *authority_ready(),
                live("reservation", state="absent", ownership="unowned"),
            )
            first = controller.begin(desired=desired, observed=observed, now=NOW)
            second = controller.begin(desired=desired, observed=observed, now=NOW)
            controller.approve(first.operation_id, now=NOW)
            controller.approve(second.operation_id, now=NOW)

            controller.authorize(
                first.operation_id,
                desired=desired,
                observed=observed,
                now=NOW,
            )
            self.assertTrue(active_mutation_path(root).is_file())
            with self.assertRaises(WorkspaceError):
                controller.authorize(
                    second.operation_id,
                    desired=desired,
                    observed=observed,
                    now=NOW,
                )

            controller.finish(first.operation_id, success=True, now=NOW)
            self.assertFalse(active_mutation_path(root).exists())
            permit = controller.authorize(
                second.operation_id,
                desired=desired,
                observed=observed,
                now=NOW,
            )
            self.assertEqual(permit.operation_id, second.operation_id)

    def test_failed_mutation_retains_claim_and_requires_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, experiment_id, controller = self._workspace(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            observed = self._snapshot(
                experiment_id,
                *authority_ready(),
                live("reservation", state="absent", ownership="unowned"),
            )
            plan = controller.begin(desired=desired, observed=observed, now=NOW)
            controller.approve(plan.operation_id, now=NOW)
            controller.authorize(
                plan.operation_id,
                desired=desired,
                observed=observed,
                now=NOW,
            )
            state = controller.finish(plan.operation_id, success=False, now=NOW)

            self.assertEqual(state.status, "recovery-required")
            self.assertTrue(state.claim_held)
            self.assertTrue(active_mutation_path(root).is_file())
            events = read_events(operation_events_path(root, plan.operation_id))
            self.assertEqual(
                [event["event_type"] for event in events][-2:],
                ["operation.failed", "recovery.required"],
            )

    def test_read_only_operation_needs_no_approval_or_mutation_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, experiment_id, controller = self._workspace(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            observed = self._snapshot(
                experiment_id,
                *authority_ready(),
                *resources_ready(),
                *network_ready(),
            )
            plan = controller.begin(desired=desired, observed=observed, now=NOW)
            self.assertEqual(plan.kind, "verify-path")
            self.assertEqual(plan.risk, "R1")
            self.assertFalse(plan.mutates)
            permit = controller.authorize(
                plan.operation_id,
                desired=desired,
                observed=observed,
                now=NOW,
            )
            self.assertEqual(permit.kind, "verify-path")
            self.assertFalse(active_mutation_path(root).exists())
            state = controller.finish(plan.operation_id, success=True, now=NOW)
            self.assertEqual(state.status, "completed")

            combined = session_events_path(root).read_text(encoding="utf-8")
            self.assertNotIn("203.0.113.77", combined)

    def test_interrupt_of_authorized_mutation_keeps_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, experiment_id, controller = self._workspace(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            observed = self._snapshot(
                experiment_id,
                *authority_ready(),
                live("reservation", state="absent", ownership="unowned"),
            )
            plan = controller.begin(desired=desired, observed=observed, now=NOW)
            controller.approve(plan.operation_id, now=NOW)
            controller.authorize(
                plan.operation_id,
                desired=desired,
                observed=observed,
                now=NOW,
            )
            state = controller.interrupt(plan.operation_id, now=NOW)
            self.assertEqual(state.status, "recovery-required")
            self.assertTrue(state.claim_held)
            self.assertTrue(active_mutation_path(root).exists())

    def test_plan_integrity_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, experiment_id, controller = self._workspace(Path(temporary))
            desired = ExperimentDesiredState.recommended(intent="virtual-5g")
            observed = self._snapshot(
                experiment_id,
                *authority_ready(),
                live("reservation", state="absent", ownership="unowned"),
            )
            plan = controller.begin(desired=desired, observed=observed, now=NOW)
            path = root / ".synthran" / "operations" / plan.operation_id / "plan.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["reason"] = "tampered"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                load_plan(root, plan.operation_id)

    def test_r3_requires_destructive_approval_mode(self) -> None:
        with self.assertRaises(WorkspaceError):
            ApprovalGrant(
                operation_id="op-000001",
                plan_sha256="a" * 64,
                risk="R3",
                mode="standard",
                approved_at_utc="2026-08-17T19:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
