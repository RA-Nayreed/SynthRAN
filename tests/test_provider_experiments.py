from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from synthran.workspace import (
    WorkspaceError,
    WorkspaceRegistry,
    bind_slices_experiment,
    discover_slices_experiments,
    load_experiment_record,
    parse_slices_experiment_list,
    verified_slices_experiment,
)
from synthran.workspace.access import ProbeResult
from synthran.workspace.model import Profile, format_utc
from synthran.workspace.store import initialize_workspace, save_profile


UTC = timezone.utc
NOW = datetime(2026, 8, 18, 2, 0, tzinfo=UTC)


class ProviderExperimentTests(unittest.TestCase):
    def test_list_parser_reads_only_first_table_column(self) -> None:
        output = """
                              Experiments
        ┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┓
        ┃ Name              ┃ Expires At            ┃
        ┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━┩
        │ alpha-exp         │ 2026-08-19 03:00 CEST │
        │ beta_02           │ 2026-08-20 03:00 CEST │
        └───────────────────┴───────────────────────┘
        """
        self.assertEqual(
            [item.name for item in parse_slices_experiment_list(output)],
            ["alpha-exp", "beta_02"],
        )

    def test_list_parser_fails_closed_on_unknown_shape(self) -> None:
        with self.assertRaisesRegex(WorkspaceError, "could not be recognized safely"):
            parse_slices_experiment_list("alpha-exp beta-exp")

    def test_list_parser_accepts_explicit_empty_result(self) -> None:
        self.assertEqual(parse_slices_experiment_list("No experiments found."), ())

    def test_discovery_uses_read_only_list_command(self) -> None:
        calls: list[tuple[tuple[str, ...], int]] = []

        def runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
            calls.append((command, timeout))
            return ProbeResult(0, "│ experiment-a │ active │\n")

        choices = discover_slices_experiments(runner=runner, timeout_seconds=60)
        self.assertEqual([choice.name for choice in choices], ["experiment-a"])
        self.assertEqual(calls, [(("slices", "experiment", "list"), 60)])

    def test_selected_experiment_is_rechecked_exactly(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command: tuple[str, ...], timeout: int) -> ProbeResult:
            calls.append(command)
            return ProbeResult(0, "Experiment exact-exp is active")

        self.assertEqual(
            verified_slices_experiment("exact-exp", runner=runner),
            "exact-exp",
        )
        self.assertEqual(calls, [("slices", "experiment", "show", "exact-exp")])

    def test_binding_is_one_time_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repo"
            root.mkdir()
            config_home = base / "config"
            save_profile(
                Profile(
                    name="controller",
                    created_at_utc=format_utc(NOW),
                    updated_at_utc=format_utc(NOW),
                    slices_username="operator",
                ),
                environment={"SYNTHRAN_CONFIG_HOME": str(config_home)},
            )
            initialize_workspace(
                root=root,
                profile="controller",
                project="research-project",
                now=NOW,
            )
            record = WorkspaceRegistry(root).create_experiment(
                profile="controller",
                project="research-project",
                now=NOW,
            )

            bound = bind_slices_experiment(root, record.experiment_id, "provider-one")
            self.assertEqual(bound.slices_experiment, "provider-one")
            self.assertEqual(
                bind_slices_experiment(root, record.experiment_id, "provider-one"),
                bound,
            )
            with self.assertRaisesRegex(WorkspaceError, "different SLICES provider binding"):
                bind_slices_experiment(root, record.experiment_id, "provider-two")
            self.assertEqual(
                load_experiment_record(root, record.experiment_id).slices_experiment,
                "provider-one",
            )


if __name__ == "__main__":
    unittest.main()
