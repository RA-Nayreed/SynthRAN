"""Run the physical launch tasks and exercise real C stdio before UE traffic."""

import os
import selectors
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

import test_r2lab

ROOT = test_r2lab.ROOT


@unittest.skipUnless(
    all(shutil.which(command) for command in ("ansible-playbook", "cc", "stdbuf")),
    "Ansible, a C compiler, and GNU stdbuf are required",
)
class GnbLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.binary = Path(cls.workspace.name, "gnb")
        subprocess.run(
            ["cc", str(ROOT / "tests/fixtures/gnb_stdio.c"), "-o", str(cls.binary)],
            check=True,
            capture_output=True,
            timeout=30,
        )

    def patch_launch(self, directory, source):
        chart = directory / "charts/srsran-gnb/templates/deployment.yaml"
        chart.parent.mkdir(parents=True)
        chart.write_text(source)
        tasks = yaml.safe_load(
            (
                ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/deploy_with_check.yml"
            ).read_text()
        )
        selected_tasks = [
            task
            for task in tasks
            if task["name"]
            in (
                "Flush physical gNB console output without a terminal",
                "Read the physical gNB launch template",
                "Require one physical gNB launch with immediate console output",
            )
        ]
        playbook = directory / "launch.yml"
        playbook.write_text(
            yaml.safe_dump(
                [
                    {
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "vars": {
                            "repo_dest_abs": str(directory),
                            "ansible_python_interpreter": sys.executable,
                        },
                        "tasks": selected_tasks + selected_tasks,
                    }
                ],
                sort_keys=False,
            )
        )
        result = subprocess.run(
            ["ansible-playbook", "-i", "localhost,", str(playbook)],
            env={**os.environ, "ANSIBLE_CONFIG": str(ROOT / "deployment/ansible.cfg")},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result, chart.read_text()

    def observe_startup(self, command, output):
        with output.open("w") as console:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=console,
                stderr=subprocess.PIPE,
            )
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stderr, selectors.EVENT_READ)
                    self.assertTrue(
                        selector.select(timeout=5), "gNB fixture did not start"
                    )
                self.assertEqual(process.stderr.read(1), b"1")
                result = test_r2lab.GnbGateTests().run_gate("success", output)
                self.assertIsNone(
                    process.poll(), "gNB must still be running at the gate"
                )
                return result
            finally:
                process.terminate()
                process.communicate(timeout=5)

    def test_live_markers_are_visible_without_ue_traffic_or_process_exit(self):
        # Representative launch line, including the pinned chart's optional Helm arguments.
        source = (
            "before-launch\n"
            "              /usr/local/bin/gnb -c $CONFIG_FILE"
            "{{- if .Values.csi_logger_enabled }} --csi-logger-enabled{{- end }}\n"
            "after-launch\n"
        )
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            old = self.observe_startup([str(self.binary)], directory / "old.log")
            self.assertNotEqual(old.returncode, 0)
            self.assertIn("N2_seen=0 gNB_start_seen=0", old.stdout)

            result, patched = self.patch_launch(directory, source)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("changed=1", result.stdout)
            self.assertEqual(patched.replace("exec stdbuf -oL -eL ", ""), source)
            launch = next(
                line.strip() for line in patched.splitlines() if "exec stdbuf" in line
            )
            command = shlex.split(launch.split(" -c ", 1)[0])[1:]
            command[-1] = str(self.binary)
            current = self.observe_startup(command, directory / "new.log")
            self.assertEqual(current.returncode, 0, current.stdout + current.stderr)
            self.assertIn("stable=15s", current.stdout)

    def test_changed_upstream_launch_shape_fails_before_helm(self):
        with tempfile.TemporaryDirectory() as temp:
            result, _ = self.patch_launch(
                Path(temp), "exec /another/path/gnb -c config.yml\n"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no longer has the expected", result.stdout + result.stderr)

    def test_failed_gate_retains_and_prints_console_and_application_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            kubectl = directory / "kubectl"
            kubectl.write_text(
                f"#!{sys.executable}\n"
                "import sys\n"
                "args = sys.argv[1:]\n"
                "if 'logs' in args:\n"
                "    print('N2: Connection to AMF on 192.168.3.201:38412 completed')\n"
                "    print('UHD startup still pending')\n"
                "elif 'get' in args: print('uid-1|Running|true|0')\n"
                "elif 'describe' in args: print('Name: gnb-1')\n"
                "elif 'exec' in args and args[-2:] == ['cat', '/tmp/gnb.log']:\n"
                "    print('application diagnostic')\n"
                "else: sys.exit(90)\n"
            )
            kubectl.chmod(0o755)
            tasks = yaml.safe_load(
                (
                    ROOT
                    / "deployment/roles/5g/srsRAN/deploy/tasks/deploy_with_check.yml"
                ).read_text()
            )
            start = next(
                i
                for i, task in enumerate(tasks)
                if task["name"] == "Wait for the physical gNB startup gate"
            )
            playbook = directory / "gate.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "connection": "local",
                            "gather_facts": False,
                            "vars": {
                                "ansible_python_interpreter": sys.executable,
                                "helm_result": {},
                                "kubectl_bin": str(kubectl),
                                "ran_ns": "oai",
                                "gnb_pod_name": "gnb-1",
                                "run_dir": temp,
                                "physical_gnb_startup_timeout_seconds": 2,
                                "physical_gnb_poll_interval_seconds": 1,
                                "physical_gnb_stability_seconds": 0,
                            },
                            "tasks": tasks[start:],
                        }
                    ],
                    sort_keys=False,
                )
            )
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", str(playbook)],
                env={
                    **os.environ,
                    "ANSIBLE_CONFIG": str(ROOT / "deployment/ansible.cfg"),
                },
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("N2_seen=1 gNB_start_seen=0", result.stdout)
            self.assertIn("UHD startup still pending", result.stdout)
            self.assertIn("application diagnostic", result.stdout)
            self.assertIn(
                "UHD startup still pending", (directory / "gnb.log").read_text()
            )
            self.assertIn("success=False", (directory / "gnb-health.txt").read_text())
            self.assertIn("Name: gnb-1", (directory / "gnb-describe.txt").read_text())
            self.assertIn(
                "application diagnostic",
                (directory / "gnb-application.log").read_text(),
            )


if __name__ == "__main__":
    unittest.main()
