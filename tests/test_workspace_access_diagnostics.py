from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from synthran.workspace.access import (
    ProbeResult,
    _parse_slices_expiry,
    probe_r2lab_gateway_access,
    subprocess_runner,
)
from synthran.workspace.model import WorkspaceError


class WorkspaceAccessDiagnosticsTests(unittest.TestCase):
    def test_subprocess_timeout_identifies_r2lab_gateway(self) -> None:
        command = ("ssh", "-o", "BatchMode=yes", "example")
        with patch(
            "synthran.workspace.access.subprocess.run",
            side_effect=subprocess.TimeoutExpired(command, 30),
        ):
            with self.assertRaisesRegex(
                WorkspaceError,
                r"R2Lab SSH gateway probe timed out after 30s",
            ):
                subprocess_runner(command, 30)

    def test_subprocess_timeout_identifies_slices_probe(self) -> None:
        command = ("slices", "project", "show")
        with patch(
            "synthran.workspace.access.subprocess.run",
            side_effect=subprocess.TimeoutExpired(command, 30),
        ):
            with self.assertRaisesRegex(
                WorkspaceError,
                r"SLICES project show probe timed out after 30s",
            ):
                subprocess_runner(command, 30)

    def test_slices_expiry_accepts_cest_and_normalizes_to_utc(self) -> None:
        parsed = _parse_slices_expiry(
            "The project expires on 2026-10-23 01:59 CEST (later)."
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.isoformat(), "2026-10-22T23:59:00+00:00")

    def test_r2lab_failure_reports_safe_permission_reason_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            identity = Path(temporary) / "id_r2lab"
            identity.write_text("fixture", encoding="utf-8")
            stderr = (
                "private-host.example: Permission denied (publickey).\n"
                "sensitive diagnostic details"
            )
            with patch(
                "synthran.workspace.access.ssh_identity_fingerprint",
                return_value="SHA256:fixture",
            ):
                with self.assertRaisesRegex(
                    WorkspaceError,
                    r"R2Lab Faraday public-key access could not be verified: permission denied",
                ) as raised:
                    probe_r2lab_gateway_access(
                        slice_name="slice_user",
                        identity_reference=str(identity),
                        runner=lambda command, timeout: ProbeResult(255, "", stderr),
                    )
            self.assertNotIn("private-host.example", str(raised.exception))
            self.assertNotIn("sensitive diagnostic details", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
