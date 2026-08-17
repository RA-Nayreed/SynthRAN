from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from synthran.operations import (
    OperationController,
    load_operation_events,
    operation_events_path,
    session_events_path,
)
from synthran.workspace.desired import ExperimentDesiredState
from synthran.workspace.model import WorkspaceError, format_utc
from synthran.workspace.observed import Observation, ObservedState
from synthran.workspace.registry import WorkspaceRegistry
from synthran.workspace.store import initialize_workspace


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


def running_read_only_operation(root: Path) -> tuple[OperationController, str]:
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
    desired = ExperimentDesiredState.recommended(intent="virtual-5g")
    observed = ObservedState(
        experiment_id=experiment.experiment_id,
        collected_at_utc=format_utc(NOW),
        observations=(
            live("controller"),
            live("project_access"),
            live("provider_experiment"),
            live("reservation"),
            live("allocation"),
            live("preparation", ownership="synthran"),
            live("kubernetes", ownership="synthran"),
            live("core", ownership="synthran"),
            live("ran", ownership="synthran"),
            live("ue", ownership="synthran"),
            live("pdu", ownership="synthran"),
            live("upf", ownership="synthran"),
            live("radio", ownership="synthran"),
        ),
    )
    controller = OperationController(root)
    plan = controller.begin(desired=desired, observed=observed, now=NOW)
    controller.authorize(
        plan.operation_id,
        desired=desired,
        observed=observed,
        now=NOW,
    )
    return controller, plan.operation_id


class OperationProgressEventTests(unittest.TestCase):
    def test_structured_progress_and_state_change_are_ordered_and_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller, operation_id = running_read_only_operation(root)
            controller.stage_started(operation_id, "path-check", now=NOW)
            controller.stage_progress(operation_id, "path-check", 1, 3, now=NOW)
            controller.state_changed(operation_id, "pdu", "ready", now=NOW)
            controller.stage_progress(operation_id, "path-check", 3, 3, now=NOW)
            controller.stage_completed(operation_id, "path-check", now=NOW)
            controller.finish(operation_id, success=True, now=NOW)

            events = load_operation_events(root, operation_id)
            self.assertEqual(
                [event.sequence for event in events],
                list(range(1, len(events) + 1)),
            )
            self.assertEqual(
                [event.event_type for event in events][-6:],
                [
                    "stage.started",
                    "stage.progress",
                    "state.changed",
                    "stage.progress",
                    "stage.completed",
                    "operation.completed",
                ],
            )
            progress = next(
                event
                for event in events
                if event.event_type == "stage.progress"
            )
            self.assertEqual(progress.attributes["current"], "1")
            self.assertEqual(progress.attributes["total"], "3")

    def test_stage_failure_uses_safe_code_not_raw_provider_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller, operation_id = running_read_only_operation(root)
            controller.stage_failed(
                operation_id,
                "ssh-check",
                "transport-error",
                now=NOW,
            )
            events = load_operation_events(root, operation_id)
            self.assertEqual(events[-1].event_type, "stage.failed")
            self.assertEqual(events[-1].attributes["code"], "transport-error")

            with self.assertRaises(WorkspaceError):
                controller.stage_failed(
                    operation_id,
                    "ssh-check",
                    "Permission denied for private@example.invalid",
                    now=NOW,
                )

    def test_progress_values_are_validated_before_event_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller, operation_id = running_read_only_operation(root)
            initial = len(load_operation_events(root, operation_id))
            for current, total in ((-1, 10), (11, 10), (0, 0)):
                with self.assertRaises(WorkspaceError):
                    controller.stage_progress(
                        operation_id,
                        "deploy",
                        current,
                        total,
                        now=NOW,
                    )
            with self.assertRaises(WorkspaceError):
                controller.stage_progress(
                    operation_id,
                    "deploy",
                    True,
                    10,
                    now=NOW,
                )
            self.assertEqual(len(load_operation_events(root, operation_id)), initial)

    def test_state_change_rejects_unknown_dimensions_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller, operation_id = running_read_only_operation(root)
            with self.assertRaises(WorkspaceError):
                controller.state_changed(
                    operation_id,
                    "secret-provider-field",
                    "ready",
                    now=NOW,
                )
            with self.assertRaises(WorkspaceError):
                controller.state_changed(
                    operation_id,
                    "ue",
                    "attached-with-private-details",
                    now=NOW,
                )

    def test_progress_events_require_running_operation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller, operation_id = running_read_only_operation(root)
            controller.finish(operation_id, success=True, now=NOW)
            with self.assertRaises(WorkspaceError):
                controller.stage_started(operation_id, "late-stage", now=NOW)

    def test_tampered_event_plan_digest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller, operation_id = running_read_only_operation(root)
            controller.stage_started(operation_id, "verify", now=NOW)
            path = operation_events_path(root, operation_id)
            lines = path.read_text(encoding="utf-8").splitlines()
            value = json.loads(lines[-1])
            value["plan_sha256"] = "0" * 64
            lines[-1] = json.dumps(value, sort_keys=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                load_operation_events(root, operation_id)

    def test_tampered_event_id_or_sequence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller, operation_id = running_read_only_operation(root)
            controller.stage_started(operation_id, "verify", now=NOW)
            path = operation_events_path(root, operation_id)
            lines = path.read_text(encoding="utf-8").splitlines()
            value = json.loads(lines[-1])
            value["event_id"] = f"{operation_id}:9999"
            lines[-1] = json.dumps(value, sort_keys=True)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(WorkspaceError):
                load_operation_events(root, operation_id)

    def test_session_transcript_receives_same_structured_progress_event(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller, operation_id = running_read_only_operation(root)
            controller.stage_progress(operation_id, "verify", 2, 5, now=NOW)
            operation_event = load_operation_events(root, operation_id)[-1]
            session_lines = session_events_path(root).read_text(encoding="utf-8").splitlines()
            session_event = json.loads(session_lines[-1])
            self.assertEqual(session_event, operation_event.to_dict())


if __name__ == "__main__":
    unittest.main()
