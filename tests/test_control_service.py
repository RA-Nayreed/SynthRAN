from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from synthran.control import ControlService, serve
from synthran.workspace.access import ProbeResult
from synthran.workspace.desired_store import load_desired_state
from synthran.workspace.model import AccessRecord, Profile, format_utc
from synthran.workspace.store import (
    bind_slices_experiment,
    initialize_workspace,
    load_active_experiment_id,
    load_experiment_record,
    load_workspace,
    save_access_record,
    save_profile,
    workspace_directory,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)


class ControlServiceTests(unittest.TestCase):
    def _service(
        self,
        base: Path,
        *,
        provider_runner=None,
    ) -> tuple[Path, ControlService]:
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
        options = {"start": root, "environment": environment}
        if provider_runner is not None:
            options["provider_runner"] = provider_runner
        return root, ControlService(**options)

    @staticmethod
    def _virtual_create_params(**overrides):
        params = {
            "intent": "iot-to-5g",
            "radio_mode": "virtual",
            "placement": "automatic",
            "core_node": None,
            "ran_node": None,
        }
        params.update(overrides)
        return params

    def test_handshake_declares_explicit_live_operation_control(self) -> None:
        service = ControlService(start=Path("/missing"), environment={})
        response = service.handle(
            {"v": 7, "id": "req-1", "method": "system.handshake", "params": {}}
        )
        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertTrue(result["local_writes"])
        self.assertTrue(result["provider_reads"])
        self.assertTrue(result["provider_mutation"])
        self.assertEqual(result["protocol"], 7)
        self.assertEqual(
            result["methods"],
            [
                "experiment.bind_provider",
                "experiment.create",
                "operation.approve",
                "operation.cancel",
                "operation.execute",
                "operation.inspect",
                "operation.plan",
                "operation.read",
                "provider.experiments",
                "setup.inspect",
                "system.handshake",
                "workspace.initialize",
                "workspace.snapshot",
                "workspace.switch_profile",
                "workspace.update_defaults",
            ],
        )

    def test_workspace_snapshot_exposes_sanitized_local_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            save_access_record(
                root,
                AccessRecord(
                    provider="slices",
                    subject="operator",
                    scope="research-project",
                    verified_at_utc=format_utc(NOW - timedelta(minutes=5)),
                    refresh_after_utc=format_utc(NOW + timedelta(hours=1)),
                    access_until_utc=format_utc(NOW + timedelta(days=1)),
                ),
            )

            result = service.workspace_snapshot(now=NOW)
            self.assertEqual(result["workspace"]["project"], "research-project")
            self.assertEqual(result["experiment"]["lifecycle"], "EMPTY")
            self.assertIsNone(result["experiment"]["placement_mode"])
            self.assertEqual(result["profiles"][0]["name"], "controller")
            self.assertIn("sopnode-f2", result["compute_nodes"])
            self.assertIn("sopnode-f3", result["compute_nodes"])
            self.assertTrue(result["access"]["slices"]["fresh"])
            self.assertFalse(result["access"]["r2lab"]["configured"])
            self.assertNotIn("workspace_root", result)
            rendered = json.dumps(result)
            self.assertNotIn(str(root), rendered)
            self.assertNotIn("fingerprint", rendered.lower())

    def test_create_experiment_persists_new_active_local_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            response = service.handle(
                {
                    "v": 7,
                    "id": "req-create",
                    "method": "experiment.create",
                    "params": self._virtual_create_params(),
                }
            )
            self.assertTrue(response["ok"])
            experiment_id = response["result"]["experiment_id"]
            snapshot = service.workspace_snapshot(now=NOW)
            self.assertEqual(snapshot["experiment"]["id"], experiment_id)
            self.assertEqual(snapshot["experiment"]["intent"], "iot-to-5g")
            self.assertEqual(snapshot["experiment"]["radio_mode"], "virtual")
            self.assertEqual(snapshot["experiment"]["placement_mode"], "automatic")
            self.assertIsNone(snapshot["experiment"]["provider_experiment"])
            self.assertEqual(snapshot["experiment"]["lifecycle"], "CONFIGURED")
            self.assertTrue(
                (workspace_directory(root) / "experiments" / experiment_id / "desired.json").is_file()
            )

    def test_manual_node_selection_is_persisted_in_desired_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            response = service.handle(
                {
                    "v": 7,
                    "id": "manual",
                    "method": "experiment.create",
                    "params": self._virtual_create_params(
                        placement="manual",
                        core_node="sopnode-f2",
                        ran_node="sopnode-f3",
                    ),
                }
            )
            self.assertTrue(response["ok"])
            experiment_id = response["result"]["experiment_id"]
            desired = load_desired_state(root, experiment_id)
            self.assertEqual(desired.placement.mode, "manual")
            self.assertEqual(desired.placement.core_node, "sopnode-f2")
            self.assertEqual(desired.placement.ran_node, "sopnode-f3")
            snapshot = service.workspace_snapshot(now=NOW)
            self.assertEqual(snapshot["experiment"]["core_node"], "sopnode-f2")
            self.assertEqual(snapshot["experiment"]["ran_node"], "sopnode-f3")

    def test_invalid_create_params_fail_before_experiment_is_issued(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            response = service.handle(
                {
                    "v": 7,
                    "id": "req-create",
                    "method": "experiment.create",
                    "params": self._virtual_create_params(
                        intent="virtual-5g",
                        radio_mode="physical",
                    ),
                }
            )
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "invalid_params")
            experiment_root = workspace_directory(root) / "experiments"
            self.assertEqual(list(experiment_root.iterdir()), [])

    def test_incomplete_manual_placement_fails_before_experiment_is_issued(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            response = service.handle(
                {
                    "v": 7,
                    "id": "bad-manual",
                    "method": "experiment.create",
                    "params": self._virtual_create_params(
                        placement="manual",
                        core_node="sopnode-f2",
                    ),
                }
            )
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "invalid_params")
            self.assertEqual(list((workspace_directory(root) / "experiments").iterdir()), [])

    def test_invalid_label_fails_before_experiment_id_is_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary))
            response = service.handle(
                {
                    "v": 7,
                    "id": "req-label",
                    "method": "experiment.create",
                    "params": self._virtual_create_params(label="   "),
                }
            )
            self.assertFalse(response["ok"])
            experiment_root = workspace_directory(root) / "experiments"
            self.assertEqual(list(experiment_root.iterdir()), [])

            valid = service.handle(
                {
                    "v": 7,
                    "id": "req-valid",
                    "method": "experiment.create",
                    "params": self._virtual_create_params(),
                }
            )
            self.assertTrue(valid["ok"])
            self.assertTrue(str(valid["result"]["experiment_id"]).endswith("-001"))

    def test_profile_switch_reverifies_then_preserves_old_local_config_as_history(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command, timeout):
            command = tuple(command)
            calls.append(command)
            if command == ("slices", "auth", "show"):
                return ProbeResult(0, "Logged in as operator-two")
            if command == ("slices", "project", "show"):
                return ProbeResult(
                    0,
                    "The current project is research-project. You are a member. It expires on 2026-10-22 23:59 UTC.",
                )
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, service = self._service(base, provider_runner=runner)
            environment = {"SYNTHRAN_CONFIG_HOME": str(base / "config")}
            save_profile(
                Profile(
                    name="second",
                    created_at_utc=format_utc(NOW),
                    updated_at_utc=format_utc(NOW),
                    slices_username="operator-two",
                ),
                environment=environment,
            )
            created = service.handle(
                {
                    "v": 7,
                    "id": "create",
                    "method": "experiment.create",
                    "params": self._virtual_create_params(),
                }
            )
            old_id = created["result"]["experiment_id"]

            switched = service.handle(
                {
                    "v": 7,
                    "id": "switch",
                    "method": "workspace.switch_profile",
                    "params": {"profile_name": "second"},
                }
            )

            self.assertTrue(switched["ok"])
            self.assertEqual(load_workspace(root).profile, "second")
            self.assertIsNone(load_active_experiment_id(root))
            self.assertTrue((workspace_directory(root) / "experiments" / old_id).is_dir())
            self.assertEqual(service.workspace_snapshot(now=NOW)["workspace"]["profile"], "second")
        self.assertEqual(
            calls,
            [("slices", "auth", "show"), ("slices", "project", "show")],
        )

    def test_provider_discovery_verifies_project_then_lists(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command, timeout):
            command = tuple(command)
            calls.append(command)
            if command == ("slices", "auth", "show"):
                return ProbeResult(0, "Logged in as operator")
            if command == ("slices", "project", "show"):
                return ProbeResult(
                    0,
                    "The current project is research-project. You are a member. It expires on 2026-10-22 23:59 UTC.",
                )
            if command == ("slices", "experiment", "list"):
                return ProbeResult(0, "│ provider-a │ active │\n│ provider-b │ active │")
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temporary:
            _, service = self._service(Path(temporary), provider_runner=runner)
            response = service.handle(
                {"v": 7, "id": "providers", "method": "provider.experiments", "params": {}}
            )

        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["experiments"], ["provider-a", "provider-b"])
        self.assertEqual(
            calls,
            [
                ("slices", "auth", "show"),
                ("slices", "project", "show"),
                ("slices", "experiment", "list"),
            ],
        )

    def test_provider_binding_rechecks_project_and_exact_experiment(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command, timeout):
            command = tuple(command)
            calls.append(command)
            if command == ("slices", "auth", "show"):
                return ProbeResult(0, "Logged in as operator")
            if command == ("slices", "project", "show"):
                return ProbeResult(
                    0,
                    "The current project is research-project. You are a member. It expires on 2026-10-22 23:59 UTC.",
                )
            if command == ("slices", "experiment", "show", "provider-a"):
                return ProbeResult(0, "Experiment provider-a is active")
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary), provider_runner=runner)
            created = service.handle(
                {
                    "v": 7,
                    "id": "create",
                    "method": "experiment.create",
                    "params": self._virtual_create_params(),
                }
            )
            experiment_id = created["result"]["experiment_id"]
            response = service.handle(
                {
                    "v": 7,
                    "id": "bind",
                    "method": "experiment.bind_provider",
                    "params": {"provider_experiment": "provider-a"},
                }
            )

            self.assertTrue(response["ok"])
            self.assertEqual(response["result"]["provider_experiment"], "provider-a")
            self.assertEqual(
                load_experiment_record(root, experiment_id).slices_experiment,
                "provider-a",
            )
        self.assertEqual(
            calls,
            [
                ("slices", "auth", "show"),
                ("slices", "project", "show"),
                ("slices", "experiment", "show", "provider-a"),
            ],
        )

    def test_different_existing_binding_is_refused_before_provider_call(self) -> None:
        provider_called = False

        def runner(command, timeout):
            nonlocal provider_called
            provider_called = True
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as temporary:
            root, service = self._service(Path(temporary), provider_runner=runner)
            created = service.handle(
                {
                    "v": 7,
                    "id": "create",
                    "method": "experiment.create",
                    "params": self._virtual_create_params(),
                }
            )
            experiment_id = created["result"]["experiment_id"]
            bind_slices_experiment(root, experiment_id, "provider-a")
            response = service.handle(
                {
                    "v": 7,
                    "id": "bind",
                    "method": "experiment.bind_provider",
                    "params": {"provider_experiment": "provider-b"},
                }
            )

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_params")
        self.assertFalse(provider_called)

    def test_unknown_method_fails_closed(self) -> None:
        service = ControlService(environment={})
        response = service.handle(
            {"v": 7, "id": "req-2", "method": "provider.execute", "params": {}}
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "method_not_found")

    def test_old_protocol_is_rejected(self) -> None:
        service = ControlService(environment={})
        response = service.handle(
            {"v": 6, "id": "req-old", "method": "system.handshake", "params": {}}
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "workspace_error")
        self.assertIn("protocol version is unsupported", response["error"]["message"])

    def test_stream_returns_one_bounded_response_per_input_line(self) -> None:
        service = ControlService(environment={})
        source = StringIO(
            "not-json\n"
            '{"v":7,"id":"req-3","method":"system.handshake","params":{}}\n'
        )
        target = StringIO()
        serve(service, input_stream=source, output_stream=target)
        responses = [json.loads(line) for line in target.getvalue().splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["error"]["code"], "invalid_json")
        self.assertTrue(responses[1]["ok"])


if __name__ == "__main__":
    unittest.main()
