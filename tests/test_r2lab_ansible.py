"""Execute the real Ansible UE role against local command fixtures."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from synthran.deployment_state import build_manifest, build_ue_map
from test_r2lab import ROOT, observations, scenario_contract

STUB = r"""import argparse, json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ['TEST_FIXTURES'])
name = pathlib.Path(sys.argv[0]).name
host = os.environ['TEST_DEVICE']
with (root / f'{host}-commands.jsonl').open('a') as log:
    log.write(json.dumps([name] + sys.argv[1:]) + '\n')
fixture = json.loads((root / f'{host}.json').read_text())
args = sys.argv[1:]
if name == 'ip':
    if args[:3] == ['-j', 'route', 'get']:
        print(json.dumps([{'dev': fixture.get('route_interface', 'wwan0')}]))
    elif '-j' in args: print(json.dumps(fixture['links']))
    elif 'addr' in args: print('1: wwan0 inet ' + fixture['links'][0]['addr_info'][0]['local'] + '/24')
    elif args[:2] != ['route', 'replace']: sys.exit(91)
elif name in ('check-ue', 'qhat-check'): print(fixture['modem'])
elif name == 'mbimcli':
    option = args[-1]
    if option == '--query-subscriber-ready-status': print(fixture['subscriber'])
    elif option == '--query-connection-state=0': print(fixture['connection'])
    elif option == '--query-ip-configuration=0': print(fixture['ip_config'])
    else: sys.exit(92)
elif name == 'pgrep': print(fixture['manager'])
elif name == 'getent': print('192.0.2.10 STREAM broker')
elif name == 'start.sh':
    if fixture.get('attach_failure'): print('activation failed'); sys.exit(1)
elif name == 'python3':
    if args[0] == '/usr/local/bin/ci_ctl_qtel.py' and args[-1] in ('detach','wup'): pass
    elif args[0] != '-c' or 'sock.bind' not in args[1]: sys.exit(93)
elif name == 'ssh':
    if 'prepare-ue' not in args: sys.exit(95)
    options = args[args.index('prepare-ue') + 1:]
    if os.environ['TEST_PREPARE_HELPER'] == 'installed':
        parser = argparse.ArgumentParser(prog='prepare-ue', allow_abbrev=False)
        for option in ('dnn', 'dnn2', 'nssai', 'nssai2'):
            parser.add_argument('--' + option)
        parser.parse_args(options)
    else:
        result = subprocess.run(['bash', os.environ['TEST_PREPARE_SOURCE'], *options])
        if result.returncode: sys.exit(result.returncode)
    if fixture.get('prepare_failure'):
        print('prepare-ue failed after argument validation', file=sys.stderr)
        sys.exit(17)
elif name not in ('ping', 'stop.sh', 'uoff', 'uon', 'sleep', 'config-ue', 'check-ue2', 'init.sh'): sys.exit(94)
"""


@unittest.skipUnless(
    shutil.which("ansible-playbook"),
    "install .[deployment] to run Ansible integration tests",
)
class PhysicalRoleTests(unittest.TestCase):
    def run_role(
        self,
        reuse=False,
        failure=None,
        preparation=False,
        qmi=False,
        helper="installed",
    ):
        scenario, profile, manifest = scenario_contract()
        if qmi:
            scenario["deployment"]["ues"] = ["qhat20"]
            manifest = build_manifest(
                scenario, profile, build_ue_map(scenario, profile)
            )
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            bin_dir = directory / "bin"
            bin_dir.mkdir()
            stub = bin_dir / "stub"
            stub.write_text(f"#!{sys.executable}\n" + STUB)
            stub.chmod(0o755)
            for command in (
                "ip",
                "mbimcli",
                "check-ue",
                "qhat-check",
                "start.sh",
                "stop.sh",
                "ping",
                "getent",
                "python3",
                "ssh",
                "pgrep",
                "uoff",
                "uon",
                "sleep",
                "config-ue",
                "check-ue2",
                "init.sh",
            ):
                (bin_dir / command).symlink_to(stub)
            hosts = [ue["device"] for ue in manifest["deployment"]["ues"]]
            fixtures = {}
            for contract in manifest["deployment"]["ues"]:
                fixture = observations(contract)
                if qmi:
                    fixture["modem"] += (
                        f"\nIMSI: {contract['imsi']}\n" + '+QCFG: "usbnet",0'
                    )
                    dnn = "wrong" if failure == "qmi_dnn" else contract["dnn"]
                    fixture["manager"] = f"777 /usr/local/bin/quectel-CM -s {dnn} -4"
                if failure == "inactive":
                    fixture["connection"] = fixture["connection"].replace(
                        "activated", "deactivated"
                    )
                elif failure == "route":
                    fixture["route_interface"] = "eth0"
                elif failure == "attach":
                    fixture["attach_failure"] = True
                elif failure == "prepare":
                    fixture["prepare_failure"] = True
                fixtures[contract["device"]] = fixture
                (directory / f'{contract["device"]}.json').write_text(
                    json.dumps(fixture)
                )
            profile_file = directory / "profile.yml"
            if preparation:
                profile["ues"]["qfit07"] = {
                    "imsi_suffix": "0000000001",
                    "slice": "slice2",
                }
            profile_file.write_text(yaml.safe_dump(profile))
            inventory = directory / "inventory.yml"
            inventory.write_text(
                yaml.safe_dump(
                    {
                        "all": {
                            "children": {
                                "physical_ues": {
                                    "hosts": {
                                        host: {
                                            "mode": "qmi" if qmi else "mbim",
                                            "at_port": "/dev/ttyUSB3",
                                        }
                                        for host in hosts
                                    }
                                },
                                "qhats": {"hosts": {host: {} for host in hosts}},
                                "qfits": (
                                    {"hosts": {"qfit07": {"mode": "mbim"}}}
                                    if preparation
                                    else {"hosts": {}}
                                ),
                            },
                            "vars": {
                                "ansible_connection": "local",
                                "ansible_python_interpreter": sys.executable,
                            },
                        }
                    }
                )
            )
            tasks = [{"ansible.builtin.include_role": {"name": "synthran/physical_ue"}}]
            if preparation:
                tasks = yaml.safe_load(
                    (
                        ROOT / "deployment/roles/r2lab/ue_setup/tasks/main.yml"
                    ).read_text()
                )
                tasks = [
                    task
                    for task in tasks
                    if task["name"]
                    in (
                        "Build the selected R2Lab UE list",
                        "Load the active 5G profile for physical UE preparation",
                        "Prepare the selected DNN with the installed R2Lab MBIM helper",
                    )
                ]
            play = [
                {
                    "name": "Verify physical UE lifecycle with command fixtures",
                    "hosts": hosts[0] if preparation else "physical_ues",
                    "gather_facts": False,
                    "any_errors_fatal": True,
                    "environment": {
                        "PATH": f'{bin_dir}:{os.environ["PATH"]}',
                        "TEST_FIXTURES": temp,
                        "TEST_DEVICE": "{{ inventory_hostname }}",
                        "TEST_PREPARE_HELPER": helper,
                        "TEST_PREPARE_SOURCE": str(
                            ROOT / "tests/fixtures/r2lab/prepare-ue"
                        ),
                    },
                    "vars": {
                        "run_dir": temp,
                        "fiveg_profile_file": str(profile_file),
                        "synthran_ue_map": manifest["deployment"]["ues"],
                        "synthran_workload_only": reuse,
                        "mqtt_broker_address": "192.0.2.10",
                        "mqtt_port": 1883,
                    },
                    "tasks": tasks,
                }
            ]
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".yml",
                prefix="r2lab-test-",
                dir=directory,
            ) as playbook:
                playbook.write(yaml.safe_dump(play, sort_keys=False))
                playbook.flush()
                env = {
                    **os.environ,
                    "ANSIBLE_CONFIG": str(ROOT / "deployment/ansible.cfg"),
                    "ANSIBLE_ROLES_PATH": str(ROOT / "deployment/roles"),
                    "ANSIBLE_NOCOLOR": "1",
                }
                result = subprocess.run(
                    ["ansible-playbook", "-i", str(inventory), playbook.name],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
            commands = {
                host: [
                    json.loads(line)
                    for line in (directory / f"{host}-commands.jsonl")
                    .read_text()
                    .splitlines()
                ]
                for host in hosts
                if (directory / f"{host}-commands.jsonl").exists()
            }
            evidence = {
                path.name: path.read_text()
                for path in directory.glob("physical-ue-*.log")
            }
            return result, commands, evidence

    def test_full_deployment_uses_selected_dnn_on_both_ues(self):
        result, commands, evidence = self.run_role()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for host, dnn in (("qhat01", "internet"), ("qhat03", "streaming")):
            self.assertIn(["start.sh", "-q", "-F", dnn], commands[host])
            self.assertLess(
                commands[host].index(["stop.sh"]),
                commands[host].index(["start.sh", "-q", "-F", dnn]),
            )
            self.assertTrue(json.loads(evidence[f"physical-ue-{host}.log"])["verified"])

    def test_reuse_only_observes_modem_and_routes(self):
        result, commands, _ = self.run_role(reuse=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for rows in commands.values():
            self.assertTrue(any(row[0] == "mbimcli" for row in rows))
            self.assertFalse(
                any(row[0] in ("start.sh", "stop.sh", "ssh") for row in rows)
            )
            self.assertFalse(any(row[:3] == ["ip", "route", "replace"] for row in rows))
            self.assertFalse(any("--connect" in " ".join(row) for row in rows))

    def test_inactive_reuse_fails_and_retains_modem_evidence(self):
        result, commands, evidence = self.run_role(reuse=True, failure="inactive")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not activated", "".join(evidence.values()))
        self.assertFalse(
            any(row[0] == "start.sh" for rows in commands.values() for row in rows)
        )

    def test_management_route_is_rejected_without_repair(self):
        result, commands, _ = self.run_role(reuse=True, failure="route")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "broker route does not use the physical UE", result.stdout + result.stderr
        )
        self.assertFalse(
            any(
                row[:3] == ["ip", "route", "replace"]
                for rows in commands.values()
                for row in rows
            )
        )

    def test_failed_attach_retains_upstream_diagnostics(self):
        result, _, evidence = self.run_role(failure="attach")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("activation failed", "".join(evidence.values()))
        self.assertIn("+CGDCONT", "".join(evidence.values()))

    def test_qmi_uses_existing_upstream_manager_and_control_helper(self):
        result, commands, evidence = self.run_role(qmi=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = commands["qhat20"]
        for action in ("detach", "wup"):
            self.assertIn(
                ["python3", "/usr/local/bin/ci_ctl_qtel.py", "/dev/ttyUSB3", action],
                rows,
            )
        self.assertFalse(any(row[0] == "mbimcli" for row in rows))
        self.assertTrue(json.loads(evidence["physical-ue-qhat20.log"])["verified"])

    def test_qmi_refuses_wrong_existing_dnn_before_modem_control(self):
        result, commands, _ = self.run_role(qmi=True, failure="qmi_dnn")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another DNN", result.stdout + result.stderr)
        self.assertFalse(
            any("ci_ctl_qtel.py" in " ".join(row) for row in commands["qhat20"])
        )

    def test_prepare_handles_qhat_and_qfit_with_selected_dnn(self):
        result, commands, _ = self.run_role(preparation=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = commands["qhat01"]
        expected = {"qhat01": "internet", "qhat03": "streaming", "qfit07": "streaming"}
        for host, dnn in expected.items():
            call = next(row for row in calls if f"root@{host}" in row)
            self.assertIn(f"--dnn={dnn}", call)
            if dnn == "streaming":
                self.assertIn("--nssai=01.100000", call)
            self.assertFalse(
                any(arg.startswith(("--dnn2=", "--nssai2=", "--mode")) for arg in call)
            )

    def test_prepare_uses_upstream_default_mbim_mode(self):
        result, commands, _ = self.run_role(preparation=True, helper="upstream")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [call for call in commands["qhat01"] if call[0] == "config-ue"]
        self.assertEqual(len(calls), 3)
        for call, dnn, nssai in zip(
            calls,
            ["internet", "streaming", "streaming"],
            ["", "01.100000", "01.100000"],
        ):
            self.assertEqual(
                call,
                [
                    "config-ue",
                    "--dnn",
                    dnn,
                    "--dnn2",
                    "",
                    "--nssai",
                    nssai,
                    "--nssai2",
                    "",
                    "--mode",
                    "mbim",
                ],
            )

    def test_prepare_failure_is_reported(self):
        result, _, _ = self.run_role(preparation=True, failure="prepare")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "prepare-ue failed after argument validation", result.stdout + result.stderr
        )


if __name__ == "__main__":
    unittest.main()
