import copy
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from synthran.deployment_state import (
    assert_reusable,
    bindings_match_deployment,
    build_manifest,
    build_ue_map,
)
from synthran.workload.replay import replay

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "physical_probe", ROOT / "deployment/scripts/probe_physical_ue.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def scenario_contract():
    scenario = yaml.safe_load(
        (ROOT / "scenarios/r2lab-reference-oai-srsran.yml").read_text()
    )
    profile = yaml.safe_load(
        (ROOT / "deployment/group_vars/all/5g_profile_scenario1.yaml").read_text()
    )
    ues = build_ue_map(scenario, profile)
    return scenario, profile, build_manifest(scenario, profile, ues)


def observations(contract):
    address = "14.1.1.12" if contract["dnn"] == "streaming" else "12.1.1.11"
    contexts = [f'+CGDCONT: 1,"IP","{contract["dnn"]}","0.0.0.0",0,0']
    if contract["sd"] != "EMPTY":
        contexts.append(
            f'+CGDCONT: 2,"IP","{contract["dnn"]}",,,,,,,,,,,,,,1,"01.100000",'
        )
    return {
        "links": [
            {
                "ifname": "wwan0",
                "flags": ["UP"],
                "addr_info": [{"family": "inet", "scope": "global", "local": address}],
            }
        ],
        "modem": str(contexts + ["OK"]),
        "subscriber": f"Subscriber ID: '{contract['imsi']}'",
        "connection": "Session ID: '0'\nActivation state: 'activated'",
        "ip_config": f"IPv4 configuration available: 'address'\nIP [0]: '{address}/24'",
    }


class PhysicalIdentityTests(unittest.TestCase):
    def setUp(self):
        self.scenario, self.profile, self.manifest = scenario_contract()
        self.contract = self.manifest["deployment"]["ues"][1]
        self.data = observations(self.contract)

    def verify(self):
        return probe.verify_observations(self.contract, **self.data)

    def test_selected_slice_does_not_create_second_mbim_session(self):
        for contract in self.manifest["deployment"]["ues"]:
            self.assertEqual(contract["tunnel"]["interface"], "wwan0")
            self.assertEqual(contract["tunnel"]["mbim_session"], 0)
        self.assertEqual(self.contract["dnn"], "streaming")
        self.assertEqual(self.contract["sd"], "100000")

    def test_qmi_transport_remains_separate(self):
        self.scenario["deployment"]["ues"] = ["qhat20"]
        contract = build_ue_map(self.scenario, self.profile)[0]
        self.assertEqual(contract["tunnel"]["mode"], "qmi")
        self.assertIsNone(contract["tunnel"]["mbim_session"])

    def test_diagnostics_with_python_list_output_are_accepted(self):
        binding = self.verify()
        self.assertEqual(binding["imsi"], self.contract["imsi"])
        self.assertEqual(binding["address"], "14.1.1.12")
        self.assertTrue(binding["modem_verified"])

    def test_wrong_sim_is_rejected(self):
        self.data["subscriber"] = "Subscriber ID: '001010000000099'"
        with self.assertRaisesRegex(ValueError, "SIM identity"):
            self.verify()

    def test_disconnected_modem_with_stale_address_is_rejected(self):
        self.data["connection"] = "Session ID: '0'\nActivation state: 'deactivated'"
        with self.assertRaisesRegex(ValueError, "not activated"):
            self.verify()

    def test_other_mbim_session_is_rejected(self):
        self.data["connection"] = "Session ID: '1'\nActivation state: 'activated'"
        with self.assertRaisesRegex(ValueError, "session ID"):
            self.verify()

    def test_host_and_modem_address_must_match(self):
        self.data["ip_config"] = "IP [0]: '14.1.1.99/24'"
        with self.assertRaisesRegex(ValueError, "differs from the host"):
            self.verify()

    def test_ambiguous_host_addresses_are_rejected(self):
        self.data["links"][0]["addr_info"].append(
            {"family": "inet", "scope": "global", "local": "14.1.1.99"}
        )
        with self.assertRaisesRegex(ValueError, "one global"):
            self.verify()

    def test_different_slice_subnet_is_rejected(self):
        self.data["links"][0]["addr_info"][0]["local"] = "12.1.1.11"
        with self.assertRaisesRegex(ValueError, "does not identify"):
            self.verify()

    def test_expected_dnn_must_be_observed(self):
        self.data["modem"] = '+CGDCONT: 1,"IP","internet"'
        with self.assertRaisesRegex(ValueError, "configured DNN"):
            self.verify()

    def test_expected_nssai_must_be_observed(self):
        self.data["modem"] = self.data["modem"].replace("01.100000", "01.999999")
        with self.assertRaisesRegex(ValueError, "NSSAI"):
            self.verify()

    def test_physical_bindings_require_modem_observations(self):
        bindings = [
            probe.verify_observations(ue, **observations(ue))
            for ue in self.manifest["deployment"]["ues"]
        ]
        self.assertTrue(
            bindings_match_deployment(self.manifest["deployment"], bindings)
        )
        del bindings[0]["modem_verified"]
        self.assertFalse(
            bindings_match_deployment(self.manifest["deployment"], bindings)
        )

    def test_old_session_one_deployment_cannot_be_reused(self):
        from synthran.deployment_state import content_hash

        active = copy.deepcopy(self.manifest)
        active["status"] = "active"
        active["deployment"]["ues"][1]["tunnel"].update(
            interface="wwan0.1", mbim_session=1
        )
        active["deployment_hash"] = content_hash(active["deployment"])
        with self.assertRaisesRegex(ValueError, "does not match"):
            assert_reusable(self.manifest, active)

    def test_publisher_rechecks_supplied_bind_address(self):
        with tempfile.TemporaryDirectory() as temp:
            trace = Path(temp, "events.jsonl")
            trace.write_text("")
            with patch("synthran.workload.replay.subprocess.run") as read_ip:
                read_ip.return_value.stdout = json.dumps(self.data["links"])
                with self.assertRaisesRegex(ValueError, "proved binding"):
                    replay(
                        trace, "127.0.0.1", interface="wwan0", bind_address="14.1.1.99"
                    )


class GnbGateTests(unittest.TestCase):
    def run_gate(self, mode):
        from jinja2 import Environment

        tasks = yaml.safe_load(
            (
                ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/deploy_with_check.yml"
            ).read_text()
        )
        gate = next(
            task["ansible.builtin.shell"]
            for task in tasks
            if task["name"] == "Wait for the physical gNB startup gate"
        )
        script = (
            Environment()
            .from_string(gate)
            .render(
                kubectl_bin="kubectl",
                ran_ns="oai",
                gnb_pod_name="gnb-1",
                physical_gnb_startup_timeout_seconds=40,
                physical_gnb_poll_interval_seconds=5,
                physical_gnb_stability_seconds=15,
            )
        )
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            clock = directory / "clock"
            clock.write_text("100")
            stub = directory / "stub"
            stub.write_text("""#!/usr/bin/env python
import os, pathlib, sys
clock = pathlib.Path(os.environ['TEST_CLOCK'])
tick = int(clock.read_text())
cmd = pathlib.Path(sys.argv[0]).name
mode = os.environ['TEST_MODE']
if cmd == 'date': print(tick)
elif cmd == 'sleep': clock.write_text(str(tick + int(sys.argv[1])))
elif 'logs' in sys.argv:
    if mode == 'fatal': print('Segmentation fault')
    elif mode != 'timeout': print('MPM timeout during early startup\\nN2: Connection to AMF completed\\ngNB started')
else:
    uid = 'new' if mode == 'replacement' and tick >= 105 else 'original'
    restart = 1 if mode == 'restart' and tick >= 105 else 0
    ready = 'false' if mode == 'unready' and tick >= 105 else 'true'
    print(f'{uid}|Running|{ready}|{restart}')
""")
            stub.chmod(0o755)
            for name in ("date", "sleep", "kubectl"):
                (directory / name).symlink_to(stub)
            env = {
                **os.environ,
                "PATH": f"{temp}:{os.environ['PATH']}",
                "TEST_CLOCK": str(clock),
                "TEST_MODE": mode,
            }
            return subprocess.run(
                ["bash", "-c", script],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )

    def test_recovered_early_uhd_warning_can_pass_after_stability(self):
        result = self.run_gate("success")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stable=15s", result.stdout)

    def test_restart_replacement_readiness_loss_fatal_and_timeout_fail(self):
        for mode in ("restart", "replacement", "unready", "fatal", "timeout"):
            with self.subTest(mode=mode):
                result = self.run_gate(mode)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertNotIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
