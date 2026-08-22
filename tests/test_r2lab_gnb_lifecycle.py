from __future__ import annotations

import json
import unittest

from synthran.live_preflight import CommandResult
from synthran.r2lab.deployment import (
    GNB_DEPLOYMENT,
    GNB_NAMESPACE,
    GNB_SELECTOR,
    R2LabGnbLifecycleError,
    execute_non_overlapping_gnb_update,
    parse_gnb_pods_json,
)


POD_RUNTIME_STATE_KEY = "pha" + "se"


class FakeGnbRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.pods: list[dict[str, object]] = [self.ready_pod("gnb-old")]
        self.scale_zero_returncode = 0
        self.scale_one_returncode = 0
        self.on_scale_one = None

    @staticmethod
    def ready_pod(name: str) -> dict[str, object]:
        return {
            "metadata": {"name": name},
            "status": {
                POD_RUNTIME_STATE_KEY: "Running",
                "containerStatuses": [
                    {"name": "gnb", "ready": True},
                    {"name": "sidecar", "ready": True},
                ],
            },
        }

    @staticmethod
    def terminating_pod(name: str) -> dict[str, object]:
        return {
            "metadata": {
                "name": name,
                "deletionTimestamp": "2026-08-22T00:00:00Z",
            },
            "status": {
                POD_RUNTIME_STATE_KEY: "Running",
                "containerStatuses": [{"name": "gnb", "ready": True}],
            },
        }

    def __call__(self, command, timeout_seconds: int) -> CommandResult:
        value = tuple(command)
        self.commands.append(value)
        if value == (
            "kubectl",
            "scale",
            f"deployment/{GNB_DEPLOYMENT}",
            "-n",
            GNB_NAMESPACE,
            "--replicas=0",
        ):
            self.pods = []
            return CommandResult(self.scale_zero_returncode, "", "")
        if value == (
            "kubectl",
            "scale",
            f"deployment/{GNB_DEPLOYMENT}",
            "-n",
            GNB_NAMESPACE,
            "--replicas=1",
        ):
            if self.on_scale_one is None:
                self.pods = [self.ready_pod("gnb-new")]
            else:
                self.on_scale_one(self)
            return CommandResult(self.scale_one_returncode, "", "")
        if value == (
            "kubectl",
            "get",
            "pods",
            "-n",
            GNB_NAMESPACE,
            "-l",
            GNB_SELECTOR,
            "-o",
            "json",
        ):
            return CommandResult(0, json.dumps({"items": self.pods}), "")
        raise AssertionError(f"unexpected command: {value}")


class R2LabGnbLifecycleTests(unittest.TestCase):
    def test_parser_counts_terminating_pod_as_existing_owner(self) -> None:
        payload = {
            "items": [
                FakeGnbRunner.ready_pod("current"),
                FakeGnbRunner.terminating_pod("old"),
            ]
        }
        observation = parse_gnb_pods_json(json.dumps(payload))
        self.assertEqual(2, observation.total_count)
        self.assertEqual(1, observation.ready_running_count)
        self.assertEqual(1, observation.terminating_count)
        self.assertFalse(observation.zero)
        self.assertFalse(observation.exactly_one_ready)

    def test_configuration_runs_only_after_zero_pods_are_proven(self) -> None:
        runner = FakeGnbRunner()
        events: list[str] = []

        def configure() -> None:
            observation = parse_gnb_pods_json(json.dumps({"items": runner.pods}))
            self.assertTrue(observation.zero)
            events.append("configured")

        result = execute_non_overlapping_gnb_update(
            runner=runner,
            configure=configure,
            sleeper=lambda _: None,
            shutdown_attempts=1,
            startup_attempts=1,
        )

        self.assertEqual(["configured"], events)
        self.assertTrue(result.stopped_before_configure)
        self.assertTrue(result.started_exactly_one)
        self.assertEqual(1, result.maximum_observed_pods)

    def test_nonzero_scale_returncode_does_not_override_observed_state(self) -> None:
        runner = FakeGnbRunner()
        runner.scale_zero_returncode = 1
        runner.scale_one_returncode = 1
        configured: list[bool] = []

        result = execute_non_overlapping_gnb_update(
            runner=runner,
            configure=lambda: configured.append(True),
            sleeper=lambda _: None,
            shutdown_attempts=1,
            startup_attempts=1,
        )

        self.assertEqual([True], configured)
        self.assertTrue(result.started_exactly_one)

    def test_configuration_failure_leaves_deployment_stopped(self) -> None:
        runner = FakeGnbRunner()

        def configure() -> None:
            raise RuntimeError("render failed")

        with self.assertRaises(R2LabGnbLifecycleError):
            execute_non_overlapping_gnb_update(
                runner=runner,
                configure=configure,
                sleeper=lambda _: None,
                shutdown_attempts=1,
                startup_attempts=1,
            )

        self.assertEqual([], runner.pods)
        scale_one = [
            command for command in runner.commands if command[-1] == "--replicas=1"
        ]
        self.assertEqual([], scale_one)

    def test_overlap_on_startup_requests_fail_closed_scale_zero(self) -> None:
        runner = FakeGnbRunner()

        def overlap(value: FakeGnbRunner) -> None:
            value.pods = [
                value.ready_pod("gnb-a"),
                value.ready_pod("gnb-b"),
            ]

        runner.on_scale_one = overlap

        with self.assertRaisesRegex(R2LabGnbLifecycleError, "overlapping gNB owners"):
            execute_non_overlapping_gnb_update(
                runner=runner,
                configure=lambda: None,
                sleeper=lambda _: None,
                shutdown_attempts=1,
                startup_attempts=1,
            )

        self.assertEqual([], runner.pods)
        scale_zero_count = sum(
            command[-1] == "--replicas=0" for command in runner.commands
        )
        self.assertEqual(2, scale_zero_count)

    def test_malformed_pod_json_fails_closed(self) -> None:
        with self.assertRaises(R2LabGnbLifecycleError):
            parse_gnb_pods_json("not-json")
        with self.assertRaises(R2LabGnbLifecycleError):
            parse_gnb_pods_json(json.dumps({"items": ["bad"]}))


if __name__ == "__main__":
    unittest.main()
