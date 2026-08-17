from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from synthran.experiment import ExperimentError
from synthran.research import CampaignPlan, CampaignRun, LoadProfile, ResearchSpec
from synthran.research_runtime import (
    PING_RE,
    ResearchRunResult,
    _discover_research_ue_pod,
    _load_command,
    _probe_research_tools,
    _route_uses_tun,
    _scenario_parameters,
    execute_research_campaign,
)


class ResearchRuntimeHelperTests(unittest.TestCase):
    def test_ping_parser_matches_iputils_output(self) -> None:
        match = PING_RE.search("64 bytes from 192.0.2.1: time=12.7 ms")
        self.assertIsNotNone(match)
        self.assertEqual(float(match.group(1)), 12.7)

    def test_load_command_is_scoped_and_uses_central_port(self) -> None:
        command = _load_command(
            target="192.0.2.10",
            run_id="research-c01-s1-c80",
            target_kbps=8000,
            payload_bytes=1024,
        )
        self.assertIn("192.0.2.10", command)
        self.assertIn("-p 18884", command)
        self.assertIn("synthran/research-c01-s1-c80/background", command)
        self.assertIn("mosquitto_pub", command)

    def test_load_command_rejects_zero_target(self) -> None:
        with self.assertRaises(ExperimentError):
            _load_command(
                target="192.0.2.10",
                run_id="research-c01-s1-c80",
                target_kbps=0,
                payload_bytes=1024,
            )

    def test_ue_discovery_requires_exact_run_annotation_and_containers(self) -> None:
        payload = {
            "items": [
                {
                    "metadata": {
                        "name": "wrong-run",
                        "annotations": {"synthran.experiment/run": "another-run"},
                    },
                    "status": {"phase": "Running"},
                    "spec": {
                        "containers": [
                            {"name": "ue"},
                            {"name": "synthran-edge-mqtt"},
                        ]
                    },
                },
                {
                    "metadata": {
                        "name": "right-run",
                        "annotations": {
                            "synthran.experiment/run": "research-c01-s1-baseline"
                        },
                    },
                    "status": {"phase": "Running"},
                    "spec": {
                        "containers": [
                            {"name": "ue"},
                            {"name": "synthran-edge-mqtt"},
                        ]
                    },
                },
            ]
        }
        with patch("synthran.research_runtime._kubectl_json", return_value=payload):
            self.assertEqual(
                _discover_research_ue_pod(object(), "research-c01-s1-baseline"),
                "right-run",
            )

    def test_ue_discovery_fails_closed_on_multiple_owned_pods(self) -> None:
        def item(name: str) -> dict[str, object]:
            return {
                "metadata": {
                    "name": name,
                    "annotations": {
                        "synthran.experiment/run": "research-c01-s1-baseline"
                    },
                },
                "status": {"phase": "Running"},
                "spec": {
                    "containers": [
                        {"name": "ue"},
                        {"name": "synthran-edge-mqtt"},
                    ]
                },
            }

        with (
            patch(
                "synthran.research_runtime._kubectl_json",
                return_value={"items": [item("a"), item("b")]},
            ),
            self.assertRaises(ExperimentError),
        ):
            _discover_research_ue_pod(object(), "research-c01-s1-baseline")

    def test_route_gate_requires_tun_srsue1(self) -> None:
        via_tun = type(
            "Result", (), {"returncode": 0, "stdout": "192.0.2.10 dev tun_srsue1 src 12.1.0.8"}
        )()
        via_other = type(
            "Result", (), {"returncode": 0, "stdout": "192.0.2.10 dev eth0 src 10.0.0.2"}
        )()
        with patch("synthran.research_runtime._exec_ue", return_value=via_tun):
            self.assertTrue(_route_uses_tun(object(), "ue-pod", "192.0.2.10"))
        with patch("synthran.research_runtime._exec_ue", return_value=via_other):
            self.assertFalse(_route_uses_tun(object(), "ue-pod", "192.0.2.10"))

    def test_tool_probe_requires_ping_and_load_helpers(self) -> None:
        ok = type("Result", (), {"returncode": 0})()
        with (
            patch("synthran.research_runtime._exec_ue", return_value=ok) as ue,
            patch("synthran.research_runtime._exec_container", return_value=ok) as edge,
        ):
            _probe_research_tools(object(), "ue-pod", require_load_tools=True)
        self.assertIn("ping", ue.call_args.args)
        self.assertIn("mosquitto_pub", edge.call_args.args[-1])

    def test_scenario_parameters_apply_seed_and_period_then_restore_builder(self) -> None:
        spec = ResearchSpec(
            campaign_id="research-c01",
            run_id="research-c01-s1-baseline",
            network_run_id="network-run",
            condition="baseline",
            cooja_seed=17,
            sensor_period_seconds=5,
            load=LoadProfile("baseline"),
        )
        original = object()
        with (
            patch("synthran.research_runtime.experiment_runtime.build_scenario", original),
            patch(
                "synthran.research_runtime.build_base_scenario",
                return_value="scenario",
            ) as builder,
        ):
            with _scenario_parameters(spec):
                from synthran.research_runtime import experiment_runtime

                self.assertEqual(
                    experiment_runtime.build_scenario(
                        run_id=spec.run_id,
                        network_manifest=Path("manifest.json"),
                        network_evidence=Path("evidence.json"),
                    ),
                    "scenario",
                )
            self.assertIs(experiment_runtime.build_scenario, original)
        self.assertEqual(builder.call_args.kwargs["cooja_seed"], 17)
        self.assertEqual(builder.call_args.kwargs["sensor_period_seconds"], 5)


class ResearchCampaignExecutionTests(unittest.TestCase):
    def test_campaign_stops_after_first_invalid_run(self) -> None:
        plan = CampaignPlan(
            campaign_id="research-c01",
            network_run_id="network-run",
            randomization_seed=1,
            reference_kbps=10000,
            runs=(
                CampaignRun(1, 11, "baseline", 0.0, "research-c01-s11-baseline"),
                CampaignRun(2, 11, "congestion", 0.8, "research-c01-s11-c80"),
            ),
        )
        experiment = type(
            "ExperimentResult",
            (),
            {"run_directory": Path("run"), "ready": False},
        )()
        invalid = ResearchRunResult(
            experiment=experiment,
            summary_path=Path("summary.json"),
            valid=False,
        )
        with patch(
            "synthran.research_runtime.execute_research_run", return_value=invalid
        ) as execute:
            result = execute_research_campaign(
                plan=plan,
                inventory=object(),
                lock=object(),
                dependency_root=Path("deps"),
                network_manifest=Path("manifest.json"),
                network_evidence=Path("evidence.json"),
                repository_root=Path("repo"),
                run_root=Path("runs"),
                warmup_seconds=0,
                measurement_seconds=30,
                sample_interval_seconds=1.0,
                payload_bytes=1024,
            )
        self.assertEqual(len(result.runs), 1)
        self.assertFalse(result.valid)
        self.assertEqual(execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
