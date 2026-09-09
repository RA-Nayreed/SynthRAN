"""Exercise deployment lifetime with real terminals, signals, and file locks."""

import fcntl
import json
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "deployment/scripts/run_deployment.sh"

ANSIBLE_FIXTURE = """import json, os, signal, sys, time
from pathlib import Path
run = Path(os.environ['TEST_RUN_DIR'])
(run / 'ansible-child.pid').write_text(str(os.getpid()))
(run / 'stdin.json').write_text(json.dumps({'tty': sys.stdin.isatty(), 'input': sys.stdin.read()}))
def stop(signum, frame):
    (run / 'ansible-terminated').touch()
    sys.exit(128 + signum)
signal.signal(signal.SIGTERM, stop)
print('TASK [Fixture deployment] ***', flush=True)
print('fixture waiting', flush=True)
while not (run / 'release').exists():
    time.sleep(.02)
print('fixture finished', flush=True)
sys.exit(int(os.environ.get('TEST_ANSIBLE_EXIT', '0')))
"""

PYTHON_FIXTURE = """import json, os, runpy, sys, time
from pathlib import Path
run = Path(os.environ['TEST_RUN_DIR'])
args = sys.argv[1:]
if args[0] == '-u':
    sys.argv = args[1:]
    runpy.run_path(sys.argv[0], run_name='__main__')
elif args[0] == '-':
    sys.argv = args
    exec(sys.stdin.read())
elif args[:2] == ['-m', 'synthran.deployment_state']:
    (run / 'state-action').write_text(args[2])
    if os.environ.get('TEST_FINALIZATION_WAIT'):
        (run / 'finalization.pid').write_text(str(os.getpid()))
        while not (run / 'release-finalization').exists():
            time.sleep(.02)
    sys.exit(int(os.environ.get('TEST_FINALIZATION_EXIT', '0')))
elif args[:2] == ['-m', 'synthran.cli']:
    Path(args[args.index('--output') + 1]).write_text(json.dumps({'fixture_reconciled': True}))
    print('fixture reconciliation finished', flush=True)
else:
    sys.exit(99)
"""


def controlling_terminal():
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


@unittest.skipUnless(shutil.which("setsid"), "requires Linux deployment utilities")
class DeploymentProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.run = self.directory / "run"
        self.run.mkdir()
        self.lock = self.directory / "deploy.lock"
        self.python = self.directory / "python-fixture"
        self.python.write_text(f"#!{sys.executable}\n" + PYTHON_FIXTURE)
        self.python.chmod(0o755)
        self.ansible = self.directory / "ansible-fixture.py"
        self.ansible.write_text(ANSIBLE_FIXTURE)
        self.env = {**os.environ, "TEST_RUN_DIR": str(self.run)}
        self.master = None
        self.process = None
        self.output = b""
        (self.run / "publisher-qhat01.jsonl").write_text('{"event_id":"one"}\n')

    def tearDown(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        pid_file = self.run / "controller.pid"
        if pid_file.exists() and not (self.run / "controller-exit-code").exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGTERM)
                self.wait_for(lambda: (self.run / "controller-exit-code").exists())
            except ProcessLookupError:
                pass
        if self.master is not None:
            os.close(self.master)
        self.temp.cleanup()

    def pump(self):
        if self.master is None:
            return
        ready, _, _ = select.select([self.master], [], [], 0)
        if ready:
            try:
                self.output += os.read(self.master, 65536)
            except OSError:
                pass

    def wait_for(self, condition, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            if condition():
                return
            time.sleep(0.02)
        self.fail(
            "Timed out; terminal output:\n" + self.output.decode(errors="replace")
        )

    def start(self, reuse=False, command=None):
        self.master, slave = pty.openpty()
        self.initial_termios = termios.tcgetattr(slave)
        args = [
            "bash",
            "-c",
            'exec 9>"$1"; shift; flock -n 9 || exit 90; exec bash "$@"',
            "fixture",
            str(self.lock),
            str(RUNNER),
            str(self.run),
            str(self.python),
            str(self.directory / "scenario.yml"),
            str(self.directory / "active.json"),
            str(reuse).lower(),
            *(command or [sys.executable, str(self.ansible)]),
        ]
        try:
            self.process = subprocess.Popen(
                args,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=self.env,
                cwd=ROOT,
                preexec_fn=controlling_terminal,
            )
        finally:
            os.close(slave)
        self.wait_for(lambda: (self.run / "controller.pid").exists())

    def release_and_wait(self):
        (self.run / "release").touch()
        self.wait_for(lambda: (self.run / "controller-exit-code").exists())
        self.wait_for(lambda: self.process.poll() is not None)
        self.pump()

    def assert_lock(self, held):
        with self.lock.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.assertTrue(held)
            else:
                self.assertFalse(held)

    def test_terminal_hangup_preserves_worker_lock_and_reconciliation(self):
        self.start()
        self.wait_for(lambda: (self.run / "stdin.json").exists())
        self.assertEqual(
            json.loads((self.run / "stdin.json").read_text()),
            {"tty": False, "input": ""},
        )
        self.assertEqual(termios.tcgetattr(self.master), self.initial_termios)
        os.close(self.master)
        self.master = None
        self.wait_for(lambda: self.process.poll() is not None)
        self.assertFalse((self.run / "controller-exit-code").exists())
        self.assert_lock(held=True)
        self.release_and_wait()
        self.assertEqual((self.run / "controller-exit-code").read_text().strip(), "0")
        self.assertEqual((self.run / "state-action").read_text(), "activate")
        self.assertTrue(
            json.loads((self.run / "summary.json").read_text())["fixture_reconciled"]
        )
        self.assertEqual(
            (self.run / "publisher.jsonl").read_text(), '{"event_id":"one"}\n'
        )
        self.assertIn("fixture finished", (self.run / "ansible.log").read_text())
        self.assert_lock(held=False)

    def test_success_streams_output_and_records_reuse(self):
        self.start(reuse=True)
        self.wait_for(lambda: b"fixture waiting" in self.output)
        self.release_and_wait()
        self.assertEqual(self.process.returncode, 0)
        self.assertEqual((self.run / "state-action").read_text(), "record-reuse")
        self.assertIn(b"fixture finished", self.output)
        self.assertIn(b"fixture reconciliation finished", self.output)

    def test_ansible_failure_is_preserved_without_finalization(self):
        self.env["TEST_ANSIBLE_EXIT"] = "7"
        self.start()
        self.release_and_wait()
        self.assertEqual(self.process.returncode, 7)
        self.assertEqual((self.run / "controller-exit-code").read_text().strip(), "7")
        self.assertFalse((self.run / "state-action").exists())
        self.assertFalse((self.run / "summary.json").exists())
        self.assert_lock(held=False)

    def test_finalization_failure_is_preserved(self):
        self.env["TEST_FINALIZATION_EXIT"] = "17"
        self.start()
        self.release_and_wait()
        self.assertEqual(self.process.returncode, 17)
        self.assertEqual((self.run / "controller-exit-code").read_text().strip(), "17")
        self.assertFalse((self.run / "summary.json").exists())

    def test_interrupt_cancels_ansible_and_releases_lock(self):
        self.start()
        self.wait_for(lambda: b"fixture waiting" in self.output)
        os.kill(self.process.pid, signal.SIGINT)
        self.wait_for(lambda: self.process.poll() is not None)
        self.wait_for(lambda: (self.run / "controller-exit-code").exists())
        self.assertEqual(self.process.returncode, 130)
        self.assertTrue((self.run / "ansible-terminated").exists())
        self.assertFalse((self.run / "summary.json").exists())
        self.assert_lock(held=False)

    def test_interrupt_cancels_finalization(self):
        self.env["TEST_FINALIZATION_WAIT"] = "1"
        self.start()
        (self.run / "release").touch()
        self.wait_for(lambda: (self.run / "finalization.pid").exists())
        child_pid = int((self.run / "finalization.pid").read_text())
        os.kill(self.process.pid, signal.SIGINT)
        self.wait_for(lambda: self.process.poll() is not None)
        self.assertEqual(self.process.returncode, 130)
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)
        self.assertFalse((self.run / "summary.json").exists())
        self.assert_lock(held=False)

    @unittest.skipUnless(shutil.which("ansible-playbook"), "requires Ansible")
    def test_interrupt_reaches_real_ansible_child_process(self):
        playbook = self.directory / "child.yml"
        playbook.write_text(
            yaml.safe_dump(
                [
                    {
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "vars": {"ansible_python_interpreter": sys.executable},
                        "tasks": [
                            {
                                "ansible.builtin.command": {
                                    "argv": [sys.executable, str(self.ansible)]
                                }
                            }
                        ],
                    }
                ]
            )
        )
        self.start(
            command=[
                shutil.which("ansible-playbook"),
                "-i",
                "localhost,",
                str(playbook),
            ]
        )
        self.wait_for(lambda: (self.run / "stdin.json").exists())
        os.kill(self.process.pid, signal.SIGINT)
        self.wait_for(lambda: self.process.poll() is not None)
        self.assertEqual(self.process.returncode, 130)
        self.wait_for(lambda: (self.run / "ansible-terminated").exists())
        self.assertFalse((self.run / "summary.json").exists())
        self.assert_lock(held=False)

    @unittest.skipUnless(shutil.which("ansible-playbook"), "requires Ansible")
    def test_r2lab_wait_completes_after_terminal_hangup(self):
        tasks = yaml.safe_load(
            (ROOT / "deployment/roles/r2lab/rru/tasks/main.yml").read_text()
        )
        boot_wait = next(
            task
            for task in tasks
            if task["name"]
            == "Allow an N3xx to complete its cold boot before gNB deployment"
        )
        playbook = self.directory / "wait.yml"
        playbook.write_text(
            yaml.safe_dump(
                [
                    {
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "vars": {
                            "rru": "n320",
                            "r2lab_n3xx_boot_seconds": 2,
                            "ansible_python_interpreter": sys.executable,
                        },
                        "tasks": [
                            boot_wait,
                            {
                                "ansible.builtin.copy": {
                                    "dest": str(self.run / "wait-finished"),
                                    "content": "finished",
                                }
                            },
                        ],
                    }
                ]
            )
        )
        self.start(
            command=[
                shutil.which("ansible-playbook"),
                "-i",
                "localhost,",
                str(playbook),
            ]
        )
        self.wait_for(lambda: "cold boot" in (self.run / "ansible.log").read_text())
        self.assertEqual(termios.tcgetattr(self.master), self.initial_termios)
        os.close(self.master)
        self.master = None
        self.wait_for(lambda: self.process.poll() is not None)
        self.wait_for(lambda: (self.run / "controller-exit-code").exists(), timeout=20)
        self.assertEqual(
            (self.run / "controller-exit-code").read_text().strip(),
            "0",
            (self.run / "ansible.log").read_text(),
        )
        self.assertTrue((self.run / "wait-finished").exists())
        self.assertTrue((self.run / "summary.json").exists())
        self.assertNotIn("ctrl+C", (self.run / "ansible.log").read_text())


if __name__ == "__main__":
    unittest.main()
