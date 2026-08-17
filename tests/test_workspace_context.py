from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from synthran.workspace.context import resolve_workspace_authority
from synthran.workspace.model import Profile, WorkspaceError, format_utc
from synthran.workspace.registry import WorkspaceRegistry
from synthran.workspace.store import initialize_workspace, save_profile


UTC = timezone.utc
NOW = datetime(2026, 8, 17, 19, 0, tzinfo=UTC)


class WorkspaceContextTests(unittest.TestCase):
    def _build(
        self,
        base: Path,
        *,
        r2lab: bool = True,
        provider_experiment: str | None = "provider-exp-01",
    ) -> tuple[Path, dict[str, str]]:
        root = base / "repo"
        root.mkdir()
        config_home = base / "config"
        environment = {"SYNTHRAN_CONFIG_HOME": str(config_home)}
        profile = Profile(
            name="controller",
            created_at_utc=format_utc(NOW),
            updated_at_utc=format_utc(NOW),
            slices_username="operator",
            r2lab_slice=("slice_user" if r2lab else None),
            r2lab_identity=(str((base / "id_r2lab").resolve()) if r2lab else None),
            r2lab_identity_fingerprint=("SHA256:fixture" if r2lab else None),
        )
        save_profile(profile, environment=environment)
        initialize_workspace(
            root=root,
            profile="controller",
            project="research-project",
            now=NOW,
        )
        if provider_experiment is not None:
            WorkspaceRegistry(root).create_experiment(
                profile="controller",
                project="research-project",
                slices_experiment=provider_experiment,
                now=NOW,
            )
        return root, environment

    def test_workspace_profile_and_active_experiment_are_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, environment = self._build(base)
            with patch(
                "synthran.workspace.context.verify_profile_identity",
                return_value="SHA256:fixture",
            ):
                context = resolve_workspace_authority(
                    start=root,
                    environment={
                        **environment,
                        "SYNTHRAN_SLICES_PROJECT": "research-project",
                        "SYNTHRAN_SLICES_EXPERIMENT": "provider-exp-01",
                        "SYNTHRAN_R2LAB_SLICE": "slice_user",
                    },
                )
            self.assertEqual(context.slices_project, "research-project")
            self.assertEqual(context.slices_experiment, "provider-exp-01")
            self.assertEqual(context.r2lab_slice, "slice_user")
            self.assertEqual(context.r2lab_identity, (base / "id_r2lab").resolve())
            self.assertIsNotNone(context.experiment_id)

    def test_conflicting_project_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, environment = self._build(Path(temporary), r2lab=False)
            with patch(
                "synthran.workspace.context.verify_profile_identity",
                return_value=None,
            ):
                with self.assertRaises(WorkspaceError):
                    resolve_workspace_authority(
                        start=root,
                        environment={
                            **environment,
                            "SYNTHRAN_SLICES_PROJECT": "other-project",
                        },
                    )

    def test_conflicting_provider_experiment_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, environment = self._build(Path(temporary), r2lab=False)
            with patch(
                "synthran.workspace.context.verify_profile_identity",
                return_value=None,
            ):
                with self.assertRaises(WorkspaceError):
                    resolve_workspace_authority(
                        start=root,
                        environment={
                            **environment,
                            "SYNTHRAN_SLICES_EXPERIMENT": "other-exp",
                        },
                    )

    def test_provider_experiment_cannot_bypass_missing_durable_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, environment = self._build(
                Path(temporary), r2lab=False, provider_experiment=None
            )
            with patch(
                "synthran.workspace.context.verify_profile_identity",
                return_value=None,
            ):
                with self.assertRaises(WorkspaceError):
                    resolve_workspace_authority(
                        start=root,
                        environment={
                            **environment,
                            "SYNTHRAN_SLICES_EXPERIMENT": "untracked-exp",
                        },
                    )

    def test_conflicting_r2lab_slice_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, environment = self._build(Path(temporary))
            with patch(
                "synthran.workspace.context.verify_profile_identity",
                return_value="SHA256:fixture",
            ):
                with self.assertRaises(WorkspaceError):
                    resolve_workspace_authority(
                        start=root,
                        environment={
                            **environment,
                            "SYNTHRAN_R2LAB_SLICE": "other_slice",
                        },
                    )

    def test_explicit_values_must_also_match_durable_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, environment = self._build(Path(temporary), r2lab=False)
            with patch(
                "synthran.workspace.context.verify_profile_identity",
                return_value=None,
            ):
                with self.assertRaises(WorkspaceError):
                    resolve_workspace_authority(
                        start=root,
                        environment=environment,
                        slices_project="other-project",
                    )


if __name__ == "__main__":
    unittest.main()
