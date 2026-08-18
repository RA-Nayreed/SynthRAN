from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from synthran.control import ControlService, serve
from synthran.workspace.model import AccessRecord, Profile, format_utc
from synthran.workspace.store import initialize_workspace, save_access_record, save_profile


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)


class ControlServiceTests(unittest.TestCase):
    def _service(self, base: Path) -> tuple[Path, ControlService]:
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
        return root, ControlService(start=root, environment=environment)

    def test_handshake_advertises_local_write_without_provider_mutation(self) -> None:
        service = ControlService(start=Path("/missing"), environment={})
        response = service.handle(
            {"v": 2, "id": "req-1", "method": "system.handshake", "params": {}}
        )
        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertFalse(result["provider_mutation"])
        self.assertEqual(result["protocol"], 2)
        self.assertEqual(result["local_write_methods"], ["experiment.create"])
        self.assertEqual(
            result["methods"],
            ["experiment.create", "system.handshake", "workspace.snapshot"],
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
            self.assertTrue(result["access"]["slices"]["fresh"])
            self.assertFalse(result["access"]["r2lab"]["configured"])
            self.assertNotIn("workspace_root", result)
            rendered = json.dumps(result)
            self.assertNotIn(str(root), rendered)
            self.assertNotIn("fingerprint", rendered.lower())

    def test_unknown_method_fails_closed(self) -> None:
        service = ControlService(environment={})
        response = service.handle(
            {"v": 2, "id": "req-2", "method": "resource.reserve", "params": {}}
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "method_not_found")

    def test_stream_returns_one_bounded_response_per_input_line(self) -> None:
        service = ControlService(environment={})
        source = StringIO(
            "not-json\n"
            '{"v":2,"id":"req-3","method":"system.handshake","params":{}}\n'
        )
        target = StringIO()
        serve(service, input_stream=source, output_stream=target)
        responses = [json.loads(line) for line in target.getvalue().splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["error"]["code"], "invalid_json")
        self.assertTrue(responses[1]["ok"])


if __name__ == "__main__":
    unittest.main()
