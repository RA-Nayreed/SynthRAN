from __future__ import annotations

import tomllib
from pathlib import Path
import unittest

from synthran.cli import _parser


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_package_exposes_one_synthran_executable(self) -> None:
        project = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            project["project"]["scripts"],
            {"synthran": "synthran.cli:main"},
        )

    def test_parser_contains_experiment_commands(self) -> None:
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

    def test_parser_keeps_network_commands(self) -> None:
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

    def test_parser_contains_r2lab_commands(self) -> None:
        parser = _parser()
        args = parser.parse_args(
            [
                "r2lab",
                "plan",
                "--slice",
                "oulu_user",
                "--radio",
                "n300",
                "--ue",
                "qhat01",
                "--run-id",
                "r2lab-test-01",
            ]
        )
        self.assertEqual(args.command, "r2lab")
        self.assertEqual(args.r2lab_command, "plan")
        self.assertEqual(args.radio, "n300")
        self.assertEqual(args.ue, "qhat01")


if __name__ == "__main__":
    unittest.main()
