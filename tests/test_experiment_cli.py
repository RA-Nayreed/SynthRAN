from __future__ import annotations

import tomllib
from pathlib import Path
import unittest

from synthran.entrypoint import _parser


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ExperimentCliTests(unittest.TestCase):
    def test_package_exposes_one_synthran_executable(self) -> None:
        project = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            project["project"]["scripts"],
            {"synthran": "synthran.entrypoint:main"},
        )

    def test_unified_parser_contains_experiment_commands(self) -> None:
        parser = _parser()
        args = parser.parse_args(
            [
                "experiment",
                "plan",
                "--network-run-id",
                "network-accepted-01",
                "--run-id",
                "experiment-01",
            ]
        )
        self.assertEqual(args.command, "experiment")
        self.assertEqual(args.experiment_command, "plan")

    def test_unified_parser_keeps_existing_network_commands(self) -> None:
        parser = _parser()
        args = parser.parse_args(
            [
                "network",
                "verify",
                "--inventory",
                "hosts.ini",
                "--run-id",
                "network-accepted-01",
            ]
        )
        self.assertEqual(args.command, "network")
        self.assertEqual(args.network_command, "verify")


if __name__ == "__main__":
    unittest.main()
