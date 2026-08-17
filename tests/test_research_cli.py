from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.experiment_cli import add_experiment_parser, dispatch_experiment


class ResearchCliTests(unittest.TestCase):
    def _parse(self, argv: list[str]) -> argparse.Namespace:
        parser = argparse.ArgumentParser()
        commands = parser.add_subparsers(dest="command", required=True)
        add_experiment_parser(commands)
        return parser.parse_args(argv)

    def test_research_plan_is_read_only_and_renders_derived_target(self) -> None:
        args = self._parse(
            [
                "experiment",
                "research-plan",
                "--campaign-id",
                "research-c01",
                "--network-run-id",
                "network-acceptance",
                "--run-id",
                "research-c01-s1-c80",
                "--seed",
                "1",
                "--condition",
                "congestion",
                "--target-fraction",
                "0.8",
                "--reference-kbps",
                "10000",
            ]
        )
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(dispatch_experiment(args), 0)
        text = output.getvalue()
        document = json.loads(text.split("\n\nExecution action:", 1)[0])
        self.assertEqual(document["load"]["target_kbps"], 8000.0)
        self.assertIn("Execution action: none", text)
        self.assertIn("Reservation action: none", text)
        self.assertIn("Network deployment action: none", text)

    def test_campaign_plan_writes_requested_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "campaign.json"
            args = self._parse(
                [
                    "experiment",
                    "campaign-plan",
                    "--campaign-id",
                    "research-c01",
                    "--network-run-id",
                    "network-acceptance",
                    "--seeds",
                    "1,2",
                    "--congestion-fractions",
                    "0.5,0.8",
                    "--reference-kbps",
                    "10000",
                    "--randomization-seed",
                    "7",
                    "--output",
                    str(output_path),
                ]
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(dispatch_experiment(args), 0)
            document = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema"], "synthran/research-campaign/v1alpha1")
            self.assertEqual(len(document["runs"]), 6)

    def test_research_run_dispatches_with_immutable_spec(self) -> None:
        args = self._parse(
            [
                "experiment",
                "research-run",
                "--campaign-id",
                "research-c01",
                "--network-run-id",
                "network-acceptance",
                "--run-id",
                "research-c01-s1-baseline",
                "--seed",
                "17",
                "--sensor-period-seconds",
                "5",
                "--condition",
                "baseline",
                "--inventory",
                "hosts.ini",
            ]
        )
        fake_experiment = type(
            "ExperimentResult",
            (),
            {"run_directory": Path("run"), "ready": True},
        )()
        fake_result = type(
            "ResearchResult",
            (),
            {
                "experiment": fake_experiment,
                "summary_path": Path("run/research-summary.json"),
                "valid": True,
            },
        )()
        with (
            patch("synthran.experiment_cli.load_inventory", return_value="inventory"),
            patch("synthran.experiment_cli.load_lock", return_value="lock"),
            patch("synthran.experiment_cli.repository_root", return_value=Path("repo")),
            patch(
                "synthran.experiment_cli.execute_research_run",
                return_value=fake_result,
            ) as execute,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(dispatch_experiment(args), 0)
        spec = execute.call_args.kwargs["spec"]
        self.assertEqual(spec.condition, "baseline")
        self.assertEqual(spec.cooja_seed, 17)
        self.assertEqual(spec.sensor_period_seconds, 5)
        self.assertEqual(spec.load.target_kbps, 0.0)

    def test_campaign_analyze_uses_only_persisted_run_arguments(self) -> None:
        args = self._parse(
            [
                "experiment",
                "campaign-analyze",
                "--campaign-id",
                "research-c01",
                "--run-ids",
                "run-a,run-b",
                "--output",
                "campaign-summary.json",
            ]
        )
        with (
            patch(
                "synthran.experiment_cli.analyze_campaign",
                return_value={"schema": "synthran/research-summary/v1alpha1"},
            ) as analyze,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(dispatch_experiment(args), 0)
        self.assertEqual(analyze.call_args.kwargs["run_ids"], ("run-a", "run-b"))
        self.assertEqual(analyze.call_args.kwargs["destination"], Path("campaign-summary.json"))


if __name__ == "__main__":
    unittest.main()
