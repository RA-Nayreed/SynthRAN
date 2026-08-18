from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from synthran.app.workflows import plan_workflow, workflow_targets
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import WorkspaceError, format_utc
from synthran.workspace.observed import Observation, ObservedState


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 0, 30, tzinfo=UTC)
EXPERIMENT_ID = "sran-20260818-001"


def observation(
    dimension: str,
    *,
    state: str = "ready",
    ownership: str = "synthran",
    running: bool | None = None,
    fresh: bool = True,
    exact: bool = True,
) -> Observation:
    facts = {} if running is None else {"running": running}
    return Observation(
        dimension=dimension,
        state=state,
        source="provider",
        observed_at_utc=format_utc(NOW - timedelta(minutes=1)),
        fresh_until_utc=format_utc(
            NOW + timedelta(minutes=10) if fresh else NOW - timedelta(seconds=1)
        ),
        ownership=ownership,
        resource_id=f"{dimension}-resource" if exact else None,
        facts=facts,
    )


def state(*items: Observation) -> ObservedState:
    return ObservedState(
        experiment_id=EXPERIMENT_ID,
        collected_at_utc=format_utc(NOW),
        observations=items,
    )


def controlled(*items: Observation) -> ObservedState:
    return state(
        observation("controller", ownership="operator"),
        observation("project_access", ownership="operator"),
        observation("provider_experiment", ownership="operator"),
        *items,
    )


class ApplicationWorkflowPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.desired = ExperimentDesiredState.recommended(intent="iot-to-5g")

    def test_live_workflow_requires_current_controller_authority(self) -> None:
        report = plan_workflow(
            self.desired,
            state(observation("path")),
            "run-baseline",
            now=NOW,
        )
        self.assertTrue(report.blocks)
        self.assertIn("controller", report.blocks[0])

        stale = plan_workflow(
            self.desired,
            state(
                observation("controller", fresh=False),
                observation("project_access"),
                observation("provider_experiment"),
                observation("path"),
            ),
            "run-baseline",
            now=NOW,
        )
        self.assertTrue(stale.blocks)
        self.assertIn("controller", stale.blocks[0])

    def test_run_baseline_requires_current_path_proof(self) -> None:
        ready = plan_workflow(
            self.desired,
            controlled(observation("path")),
            "run-baseline",
            now=NOW,
        )
        self.assertFalse(ready.blocks)
        self.assertEqual(ready.lifecycle, "PATH_PROVEN")
        self.assertEqual(ready.steps[0].name, "run-baseline")
        self.assertEqual(ready.steps[0].risk, "R2")
        self.assertTrue(ready.steps[0].mutates)

        blocked = plan_workflow(
            self.desired,
            controlled(observation("path", state="absent")),
            "run-baseline",
            now=NOW,
        )
        self.assertTrue(blocked.blocks)
        self.assertIn("path-proven", blocked.blocks[0])

    def test_run_is_blocked_while_an_experiment_is_running(self) -> None:
        report = plan_workflow(
            self.desired,
            controlled(
                observation("path"),
                observation("experiment", running=True),
            ),
            "run-congestion",
            now=NOW,
        )
        self.assertTrue(report.blocks)
        self.assertEqual(report.lifecycle, "EXPERIMENT_RUNNING")

    def test_stop_requires_running_experiment(self) -> None:
        running = plan_workflow(
            self.desired,
            controlled(
                observation("path"),
                observation("experiment", running=True),
            ),
            "stop",
            now=NOW,
        )
        self.assertFalse(running.blocks)
        self.assertEqual(running.steps[0].risk, "R2")

        idle = plan_workflow(
            self.desired,
            controlled(observation("path"), observation("experiment", running=False)),
            "stop",
            now=NOW,
        )
        self.assertTrue(idle.blocks)

    def test_collect_is_read_only_and_requires_current_path(self) -> None:
        report = plan_workflow(
            self.desired,
            controlled(observation("path")),
            "collect",
            now=NOW,
        )
        self.assertFalse(report.blocks)
        self.assertEqual(report.steps[0].risk, "R1")
        self.assertFalse(report.steps[0].mutates)

        stale = plan_workflow(
            self.desired,
            controlled(observation("path", fresh=False)),
            "collect",
            now=NOW,
        )
        self.assertTrue(stale.blocks)

    def test_component_logs_require_the_relevant_runtime(self) -> None:
        missing = plan_workflow(
            self.desired,
            controlled(observation("path")),
            "logs-open5gs",
            now=NOW,
        )
        self.assertTrue(missing.blocks)

        ready = plan_workflow(
            self.desired,
            controlled(observation("path"), observation("core")),
            "logs-open5gs",
            now=NOW,
        )
        self.assertFalse(ready.blocks)
        self.assertEqual(ready.steps[0].risk, "R1")

    def test_down_is_r3_and_binds_exact_sorted_targets(self) -> None:
        current = controlled(
            observation("path"),
            observation("reservation", ownership="operator"),
            observation("allocation"),
            observation("core"),
        )
        safe = plan_workflow(self.desired, current, "down", now=NOW)
        self.assertFalse(safe.blocks)
        self.assertEqual(safe.steps[0].risk, "R3")
        self.assertTrue(safe.steps[0].mutates)
        self.assertEqual(
            workflow_targets(current, "down", now=NOW),
            ("allocation-resource", "core-resource"),
        )

    def test_down_fails_closed_on_foreign_stale_or_unidentified_resources(self) -> None:
        foreign = plan_workflow(
            self.desired,
            controlled(observation("path"), observation("allocation", ownership="other")),
            "down",
            now=NOW,
        )
        self.assertTrue(foreign.blocks)
        self.assertIn("ownership", foreign.blocks[0])

        stale = plan_workflow(
            self.desired,
            controlled(observation("path"), observation("allocation", fresh=False)),
            "down",
            now=NOW,
        )
        self.assertTrue(stale.blocks)
        self.assertIn("stale", stale.blocks[0])

        unidentified = plan_workflow(
            self.desired,
            controlled(observation("path"), observation("allocation", exact=False)),
            "down",
            now=NOW,
        )
        self.assertTrue(unidentified.blocks)
        self.assertIn("exact resource ID", unidentified.blocks[0])
        with self.assertRaises(WorkspaceError):
            workflow_targets(
                state(observation("allocation", exact=False)),
                "down",
                now=NOW,
            )

    def test_down_requires_stop_before_teardown(self) -> None:
        report = plan_workflow(
            self.desired,
            controlled(
                observation("path"),
                observation("experiment", running=True),
            ),
            "down",
            now=NOW,
        )
        self.assertTrue(report.blocks)
        self.assertIn("stop", report.blocks[0])


if __name__ == "__main__":
    unittest.main()
