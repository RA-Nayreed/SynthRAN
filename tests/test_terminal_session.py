from __future__ import annotations

import unittest

from synthran.app.model import ApplicationSnapshot, DimensionView
from synthran.operations.model import OperationEvent
from synthran.terminal import TerminalSession


class FakeApplication:
    def __init__(self) -> None:
        self.snapshot_calls = 0
        self.events: tuple[OperationEvent, ...] = ()

    def snapshot(self) -> ApplicationSnapshot:
        self.snapshot_calls += 1
        return ApplicationSnapshot(
            workspace_root="/workspace",
            profile="controller",
            project="research-project",
            experiment_id="sran-20260817-001",
            provider_experiment="provider-exp-01",
            intent="virtual-5g",
            radio_mode="virtual",
            lifecycle="NETWORK_READY",
            observations=(
                DimensionView(
                    name="reservation",
                    state="ready",
                    fresh=True,
                    source="provider",
                    ownership="operator",
                ),
                DimensionView(
                    name="core",
                    state="ready",
                    fresh=True,
                    source="observation",
                    ownership="synthran",
                ),
            ),
            next_steps=("verify-path",),
        )

    def operation_events(self, operation_id: str) -> tuple[OperationEvent, ...]:
        return self.events


def event(sequence: int, event_type: str, attributes=None) -> OperationEvent:
    return OperationEvent(
        operation_id="op-000001",
        sequence=sequence,
        event_type=event_type,
        occurred_at_utc="2026-08-17T19:00:00Z",
        risk="R1",
        mutates=False,
        plan_sha256="a" * 64,
        attributes=attributes or {},
    )


class TerminalSessionTests(unittest.TestCase):
    def test_session_starts_in_observe_and_blocks_mutation_before_dispatch(self) -> None:
        application = FakeApplication()
        session = TerminalSession(application)
        self.assertEqual(session.mode, "observe")
        response = session.submit("/reserve")
        self.assertEqual(response.action, "error")
        self.assertIsNone(response.request)
        self.assertIn("requires OPERATE mode", response.lines[0].text)

    def test_operate_mode_allows_mutating_request_but_does_not_execute_it(self) -> None:
        application = FakeApplication()
        session = TerminalSession(application)
        mode = session.submit("/mode operate")
        self.assertEqual(mode.action, "render")
        self.assertEqual(session.mode, "operate")

        response = session.submit("/reserve")
        self.assertEqual(response.action, "dispatch")
        self.assertIsNotNone(response.request)
        assert response.request is not None
        self.assertEqual(response.request.name, "/reserve")
        self.assertEqual(application.snapshot_calls, 0)

    def test_status_and_inspect_render_current_application_snapshot_inline(self) -> None:
        application = FakeApplication()
        session = TerminalSession(application)
        status = session.submit("/status")
        self.assertEqual(status.action, "render")
        self.assertTrue(any(line.text == "Lifecycle: NETWORK_READY" for line in status.lines))
        self.assertTrue(any("verify-path" in line.text for line in status.lines))

        resources = session.submit("/inspect resources")
        self.assertTrue(any("reservation: ready" in line.text for line in resources.lines))
        self.assertFalse(any("core: ready" in line.text for line in resources.lines))

        network = session.submit("/inspect network")
        self.assertTrue(any("core: ready" in line.text for line in network.lines))
        self.assertFalse(any("reservation: ready" in line.text for line in network.lines))
        self.assertEqual(application.snapshot_calls, 3)

    def test_help_is_inline_and_config_is_routed_not_invented(self) -> None:
        application = FakeApplication()
        session = TerminalSession(application)
        help_response = session.submit("/help")
        self.assertEqual(help_response.action, "render")
        self.assertTrue(any(line.text.startswith("/status") for line in help_response.lines))

        config = session.submit("/config experiment")
        self.assertEqual(config.action, "dispatch")
        self.assertEqual(config.request.subcommand if config.request else None, "experiment")

    def test_invalid_plain_text_never_becomes_a_dispatch_request(self) -> None:
        application = FakeApplication()
        session = TerminalSession(application)
        response = session.submit("bring the network up")
        self.assertEqual(response.action, "error")
        self.assertIsNone(response.request)
        self.assertEqual(application.snapshot_calls, 0)

    def test_clear_removes_visible_transcript_and_quit_closes_session(self) -> None:
        application = FakeApplication()
        session = TerminalSession(application)
        session.submit("/status")
        self.assertTrue(session.transcript)
        cleared = session.submit("/clear")
        self.assertEqual(cleared.action, "clear")
        self.assertEqual(session.transcript, ())

        quit_response = session.submit("/quit")
        self.assertEqual(quit_response.action, "quit")
        self.assertTrue(session.closed)
        after = session.submit("/status")
        self.assertEqual(after.action, "error")
        self.assertIn("closed", after.lines[0].text)

    def test_operation_updates_render_only_events_after_cursor(self) -> None:
        application = FakeApplication()
        application.events = (
            event(1, "operation.started", {"kind": "verify-path"}),
            event(2, "plan.created"),
            event(3, "operation.authorized"),
            event(4, "stage.started", {"stage": "path-check"}),
            event(
                5,
                "stage.progress",
                {"stage": "path-check", "current": "2", "total": "3"},
            ),
            event(6, "stage.completed", {"stage": "path-check"}),
            event(7, "operation.completed"),
        )
        session = TerminalSession(application)
        updates = session.operation_updates("op-000001", after_sequence=3)
        self.assertEqual(
            [line.text for line in updates],
            [
                "[path-check] running",
                "[path-check] 2/3",
                "[path-check] ready",
                "Operation op-000001: completed",
            ],
        )

    def test_event_cursor_validation_fails_closed(self) -> None:
        session = TerminalSession(FakeApplication())
        with self.assertRaises(Exception):
            session.operation_updates("op-000001", after_sequence=-1)
        with self.assertRaises(Exception):
            session.operation_updates("op-000001", after_sequence=True)


if __name__ == "__main__":
    unittest.main()
