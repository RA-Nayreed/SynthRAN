from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from synthran.operations import OperationController
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import WorkspaceError, format_utc
from synthran.workspace.observed import Observation, ObservedState
from synthran.workspace.reconciliation import ReconciliationReport, ReconciliationStep
from synthran.workspace.registry import WorkspaceRegistry
from synthran.workspace.store import initialize_workspace


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 0, 45, tzinfo=UTC)


def observed(experiment_id: str) -> ObservedState:
    return ObservedState(
        experiment_id=experiment_id,
        collected_at_utc=format_utc(NOW),
        observations=(
            Observation(
                dimension="path",
                state="ready",
                source="provider",
                observed_at_utc=format_utc(NOW - timedelta(minutes=1)),
                fresh_until_utc=format_utc(NOW + timedelta(minutes=10)),
                ownership="synthran",
            ),
        ),
    )


def report(reason: str = "start accepted baseline") -> ReconciliationReport:
    return ReconciliationReport(
        "PATH_PROVEN",
        steps=(
            ReconciliationStep(
                name="run-baseline",
                risk="R2",
                reason=reason,
                mutates=True,
            ),
        ),
    )


class OperationApplicationPolicyTests(unittest.TestCase):
    def test_application_policy_uses_same_plan_approval_claim_and_event_engine(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)
            registry = WorkspaceRegistry(root)
            experiment = registry.create_experiment(
                profile="default",
                project="project",
                slices_experiment="provider-exp",
                network_intent="iot-to-5g",
                radio_mode="virtual",
                now=NOW,
            )
            desired = ExperimentDesiredState.recommended(intent="iot-to-5g")
            current = observed(experiment.experiment_id)
            controller = OperationController(root)

            plan = controller.begin(
                desired=desired,
                observed=current,
                step_name="run-baseline",
                policy_report=report(),
                now=NOW,
            )
            self.assertEqual(plan.kind, "run-baseline")
            self.assertEqual(plan.risk, "R2")
            self.assertTrue(plan.approval_required)

            controller.approve(plan.operation_id, now=NOW)
            permit = controller.authorize(
                plan.operation_id,
                desired=desired,
                observed=current,
                policy_report=report(),
                now=NOW,
            )
            self.assertEqual(permit.operation_id, plan.operation_id)
            self.assertTrue(permit.mutates)
            controller.finish(plan.operation_id, success=True, now=NOW)

    def test_application_policy_drift_is_rejected_after_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            initialize_workspace(root=root, profile="default", project="project", now=NOW)
            registry = WorkspaceRegistry(root)
            experiment = registry.create_experiment(
                profile="default",
                project="project",
                slices_experiment="provider-exp",
                network_intent="iot-to-5g",
                radio_mode="virtual",
                now=NOW,
            )
            desired = ExperimentDesiredState.recommended(intent="iot-to-5g")
            current = observed(experiment.experiment_id)
            controller = OperationController(root)

            plan = controller.begin(
                desired=desired,
                observed=current,
                step_name="run-baseline",
                policy_report=report(),
                now=NOW,
            )
            controller.approve(plan.operation_id, now=NOW)

            with self.assertRaises(WorkspaceError):
                controller.authorize(
                    plan.operation_id,
                    desired=desired,
                    observed=current,
                    policy_report=report("changed application workflow policy"),
                    now=NOW,
                )


if __name__ == "__main__":
    unittest.main()
