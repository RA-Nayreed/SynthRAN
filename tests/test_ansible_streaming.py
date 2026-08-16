from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from synthran.ansible_streaming import (
    parse_ansible_line,
    run_streaming_ansible_command,
)


class AnsibleStreamingParserTests(unittest.TestCase):
    def test_task_and_play_recognition(self) -> None:
        self.assertEqual(
            parse_ansible_line("PLAY [all] *********************************************************************"),
            "  PLAY: all",
        )
        self.assertEqual(
            parse_ansible_line("TASK [gather facts] ************************************************************"),
            "  TASK: gather facts",
        )
        self.assertEqual(
            parse_ansible_line("TASK [open5gs : install packages] **********************************************"),
            "  TASK: open5gs : install packages",
        )
        self.assertEqual(
            parse_ansible_line("RUNNING HANDLER [restart mosquitto] *********************************************"),
            "  HANDLER: restart mosquitto",
        )

    def test_host_status_recognition(self) -> None:
        self.assertEqual(
            parse_ansible_line("ok: [sopnode-f2]"),
            "    sopnode-f2: OK",
        )
        self.assertEqual(
            parse_ansible_line("ok: [sopnode-f2] => (item=pkg1)"),
            "    sopnode-f2: OK",
        )
        self.assertEqual(
            parse_ansible_line("changed: [sopnode-f3]"),
            "    sopnode-f3: CHANGED",
        )
        self.assertEqual(
            parse_ansible_line("changed: [sopnode-f3] => {\"changed\": true, \"ansible_facts\": {}}"),
            "    sopnode-f3: CHANGED",
        )
        self.assertEqual(
            parse_ansible_line("failed: [sopnode-f2] => {\"msg\": \"command failed\"}"),
            "    sopnode-f2: FAILED",
        )
        self.assertEqual(
            parse_ansible_line("fatal: [sopnode-f2]: FAILED! => {\"msg\": \"failed to start service\"}"),
            "    sopnode-f2: FATAL",
        )
        self.assertEqual(
            parse_ansible_line("skipping: [sopnode-f2]"),
            "    sopnode-f2: SKIPPED",
        )
        self.assertEqual(
            parse_ansible_line("unreachable: [sopnode-f3] => {\"msg\": \"host unreachable\"}"),
            "    sopnode-f3: UNREACHABLE",
        )

    def test_suppression_of_unsafe_and_raw_lines(self) -> None:
        raw_lines = [
            "PLAY RECAP ********************************************************************",
            "sopnode-f2                  : ok=12   changed=3    unreachable=0    failed=0",
            "{\"changed\": false, \"ansible_facts\": {\"discovered_interpreter_python\": \"/usr/bin/python3\"}}",
            "    \"stdout\": \"status=active node=sopnode-f2\"",
            "    \"cmd\": [\"/opt/tool/bin\", \"--flag\", \"alpha\"]",
            "Traceback (most recent call last):",
            "  File \"<string>\", line 1, in <module>",
            "",
            "   ",
            "META: ran handlers",
            "included: deploy/ansible/tasks.yml for sopnode-f2",
        ]
        for line in raw_lines:
            self.assertIsNone(
                parse_ansible_line(line),
                f"Expected line to be suppressed, but got parsed result: {line!r}",
            )


class AnsibleStreamingRunnerTests(unittest.TestCase):
    def test_streaming_process_success_and_full_output_preservation(self) -> None:
        script = (
            "import sys, time\n"
            "print('PLAY [all] *********************************************************************')\n"
            "print('TASK [setup] ********************************************************************')\n"
            "print('ok: [sopnode-f2]')\n"
            "print('{\"sensitive\": \"json_data_123\"}')\n"
            "print('changed: [sopnode-f3]')\n"
            "sys.stdout.flush()\n"
        )
        reported: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            result = run_streaming_ansible_command(
                [sys.executable, "-c", script],
                cwd=cwd,
                environment=None,
                timeout_seconds=10,
                report=reported.append,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            reported,
            [
                "  PLAY: all",
                "  TASK: setup",
                "    sopnode-f2: OK",
                "    sopnode-f3: CHANGED",
            ],
        )
        # Verify full raw output is preserved in result.stdout for sanitized logging
        self.assertIn('{"sensitive": "json_data_123"}', result.stdout)
        self.assertIn("PLAY [all]", result.stdout)
        self.assertIn("ok: [sopnode-f2]", result.stdout)

    def test_streaming_process_nonzero_exit(self) -> None:
        script = (
            "import sys\n"
            "print('TASK [check failure] *****************************************************')\n"
            "print('fatal: [sopnode-f2]: FAILED! => {\"msg\": \"error\"}')\n"
            "sys.stdout.flush()\n"
            "sys.exit(2)\n"
        )
        reported: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            result = run_streaming_ansible_command(
                [sys.executable, "-c", script],
                cwd=cwd,
                environment=None,
                timeout_seconds=10,
                report=reported.append,
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            reported,
            [
                "  TASK: check failure",
                "    sopnode-f2: FATAL",
            ],
        )
        self.assertIn('fatal: [sopnode-f2]: FAILED!', result.stdout)

    def test_heartbeat_emission_on_quiet_stages(self) -> None:
        script = (
            "import sys, time\n"
            "print('TASK [long operation] *****************************************************')\n"
            "sys.stdout.flush()\n"
            "time.sleep(0.35)\n"
            "print('ok: [sopnode-f2]')\n"
            "sys.stdout.flush()\n"
        )
        reported: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            result = run_streaming_ansible_command(
                [sys.executable, "-c", script],
                cwd=cwd,
                environment=None,
                timeout_seconds=10,
                report=reported.append,
                heartbeat_interval_seconds=0.1,
                poll_interval_seconds=0.05,
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("  TASK: long operation", reported)
        self.assertIn("    sopnode-f2: OK", reported)
        # Should have at least one heartbeat while sleeping
        heartbeats = [r for r in reported if "current task still running..." in r]
        self.assertTrue(len(heartbeats) >= 2, f"Expected multiple heartbeats, got: {reported}")

    def test_streaming_process_timeout_and_cleanup(self) -> None:
        script = "import time\ntime.sleep(10)\n"
        with tempfile.TemporaryDirectory() as temporary:
            cwd = Path(temporary)
            with self.assertRaises(subprocess.TimeoutExpired):
                run_streaming_ansible_command(
                    [sys.executable, "-c", script],
                    cwd=cwd,
                    environment=None,
                    timeout_seconds=1,
                    poll_interval_seconds=0.1,
                )


if __name__ == "__main__":
    unittest.main()
