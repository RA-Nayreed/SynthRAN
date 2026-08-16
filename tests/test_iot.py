from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from synthran.experiment import ExperimentScenario
from synthran.iot import render_cooja_scenario, render_generated_header, write_run_inputs


class IoTRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = ExperimentScenario(
            "experiment-01",
            "network-accepted-01",
            "12.1.0.1",
        )

    def test_cooja_scenario_contains_border_router_and_ten_sensors(self) -> None:
        rendered = render_cooja_scenario(self.scenario)
        self.assertEqual(rendered.count("<id>250</id>"), 1)
        for sensor in range(1, 11):
            self.assertEqual(rendered.count(f"<id>{sensor}</id>"), 1)
        self.assertIn("<randomseed>424242</randomseed>", rendered)
        self.assertIn("<port>60001</port>", rendered)
        self.assertNotIn("phase3", rendered.lower())

    def test_generated_header_contains_run_contract(self) -> None:
        header = render_generated_header(self.scenario)
        self.assertIn('#define SYNTHRAN_RUN_ID "experiment-01"', header)
        self.assertIn('#define SYNTHRAN_EDGE_BROKER_IPV6 "fd00::1"', header)
        self.assertNotIn("PHASE3", header)

    def test_run_inputs_use_product_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            header, csc, scenario = write_run_inputs(
                self.scenario,
                run_directory=Path(temporary),
            )
            self.assertEqual(header.name, "experiment-generated.h")
            self.assertEqual(csc.name, "experiment.csc")
            self.assertEqual(scenario.name, "scenario.json")


if __name__ == "__main__":
    unittest.main()
