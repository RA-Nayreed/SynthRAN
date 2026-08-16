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
        self.contiki = Path("/opt/deps/contiki-ng")

    def test_cooja_scenario_contains_border_router_and_ten_sensors(self) -> None:
        rendered = render_cooja_scenario(self.scenario, contiki_directory=self.contiki)
        self.assertEqual(rendered.count("<id>250</id>"), 1)
        for sensor in range(1, 11):
            self.assertEqual(rendered.count(f"<id>{sensor}</id>"), 1)
        self.assertIn("<randomseed>424242</randomseed>", rendered)
        self.assertIn("<port>60001</port>", rendered)
        self.assertIn("<title>SynthRAN experiment-01</title>", rendered)
        self.assertIn("<source>[CONTIKI_DIR]/examples/rpl-border-router/border-router.c</source>", rendered)
        self.assertNotIn("CONTIKI=[CONTIKI_DIR]", rendered)

    def test_generated_header_contains_run_contract(self) -> None:
        header = render_generated_header(self.scenario)
        self.assertIn('#define SYNTHRAN_RUN_ID "experiment-01"', header)
        self.assertIn('#define SYNTHRAN_EDGE_BROKER_IPV6 "fd00::1"', header)
        self.assertIn("SYNTHRAN_EXPERIMENT_GENERATED_H_", header)

    def test_cooja_scenario_with_explicit_contiki_directory_renders_path(self) -> None:
        contiki = Path("/opt/deps/contiki-ng")
        rendered = render_cooja_scenario(self.scenario, contiki_directory=contiki)
        resolved_str = str(contiki.resolve()).replace("\\", "/")
        expected_commands = (
            f"<commands>$(MAKE) TARGET=cooja CONTIKI={resolved_str} clean\n"
            f"$(MAKE) -j$(CPUS) TARGET=cooja CONTIKI={resolved_str} synthran-sensor.cooja</commands>"
        )
        self.assertIn(expected_commands, rendered)
        self.assertNotIn("CONTIKI=[CONTIKI_DIR]", rendered)

    def test_cooja_scenario_safely_quotes_and_escapes_contiki_path(self) -> None:
        contiki_special = Path("/opt/deps with spaces/contiki<>&ng")
        rendered = render_cooja_scenario(self.scenario, contiki_directory=contiki_special)
        self.assertIn("&lt;&gt;&amp;", rendered)
        self.assertNotIn("CONTIKI=[CONTIKI_DIR]", rendered)

    def test_run_inputs_use_product_names_and_propagate_contiki_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            header, csc, scenario = write_run_inputs(
                self.scenario,
                run_directory=Path(temporary),
                contiki_directory=Path("/mock/contiki"),
            )
            self.assertEqual(header.name, "experiment-generated.h")
            self.assertEqual(csc.name, "experiment.csc")
            self.assertEqual(scenario.name, "scenario.json")
            csc_content = csc.read_text(encoding="utf-8")
            resolved_mock = str(Path("/mock/contiki").resolve()).replace("\\", "/")
            self.assertIn(f"CONTIKI={resolved_mock}", csc_content)
            self.assertNotIn("CONTIKI=[CONTIKI_DIR]", csc_content)


if __name__ == "__main__":
    unittest.main()
