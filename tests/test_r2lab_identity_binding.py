from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.live_preflight import CommandResult
from synthran.network.r2lab import (
    R2LabSelection,
    build_plan,
    execute_prepare,
    gateway_command,
)


class IdentityAwareRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command, timeout_seconds: int) -> CommandResult:
        self.commands.append(tuple(command))
        return CommandResult(0, "", "")


class R2LabIdentityBindingTests(unittest.TestCase):
    def test_explicit_identity_is_live_only_and_never_persisted(self) -> None:
        reference = "~/.ssh/synthran-r2lab-test-identity"
        resolved = str(Path(reference).expanduser().resolve())
        environment = {"SYNTHRAN_R2LAB_IDENTITY": reference}

        with patch.dict(os.environ, environment, clear=False):
            command = gateway_command(
                "oulu_user", "rhubarbe", "leases", "--check"
            )
            self.assertIn("IdentitiesOnly=yes", command)
            self.assertIn("-i", command)
            identity_index = command.index("-i")
            self.assertEqual(resolved, command[identity_index + 1])
            self.assertLess(identity_index, command.index("--"))

            selection = R2LabSelection.build(
                slice_name="oulu_user", radio="n300", ue="qhat01"
            )
            plan = build_plan(run_id="r2lab-identity-test", selection=selection)
            self.assertNotIn(resolved, plan.render(as_json=True))

            runner = IdentityAwareRunner()
            with tempfile.TemporaryDirectory() as directory:
                result = execute_prepare(
                    plan=plan,
                    run_root=Path(directory) / "r2lab",
                    runner=runner,
                    sleeper=lambda _: None,
                    reachability_attempts=1,
                )
                manifest = result.manifest_path.read_text(encoding="utf-8")
                log = result.log_path.read_text(encoding="utf-8")

        self.assertNotIn(resolved, manifest)
        self.assertNotIn(resolved, log)
        self.assertTrue(runner.commands)
        for command in runner.commands:
            self.assertIn("IdentitiesOnly=yes", command)
            self.assertIn(resolved, command)


if __name__ == "__main__":
    unittest.main()
