from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from synthran.dependencies import DependencyError, load_lock, sync_dependencies


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class DependencyLockTests(unittest.TestCase):
    def test_repository_lock_is_valid_and_immutable(self) -> None:
        lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        self.assertEqual(4, len(lock.git))
        self.assertTrue(all(len(item.commit) == 40 for item in lock.git))
        self.assertEqual(2, sum(item.sync for item in lock.git))

    def test_dry_run_selects_direct_dependencies_without_writing(self) -> None:
        lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        output = StringIO()
        root = REPOSITORY_ROOT / ".dry-run-deps-must-not-exist"
        self.assertFalse(root.exists())
        sync_dependencies(lock, root, dry_run=True, output=output)
        self.assertFalse(root.exists())
        rendered = output.getvalue()
        self.assertIn("fiveg_ansible", rendered)
        self.assertIn("contiki_ng", rendered)
        self.assertNotIn("open5gs_k8s", rendered)

    def test_dry_run_all_includes_transitive_dependencies(self) -> None:
        lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        output = StringIO()
        with patch.object(Path, "mkdir") as mkdir:
            sync_dependencies(
                lock,
                REPOSITORY_ROOT / ".dry-run-deps-must-not-exist",
                include_transitive=True,
                dry_run=True,
                output=output,
            )
            mkdir.assert_not_called()
        self.assertIn("open5gs_k8s", output.getvalue())
        self.assertIn("srsran_helm", output.getvalue())

    def test_mutable_git_ref_is_rejected_as_commit(self) -> None:
        lock_data = json.loads((REPOSITORY_ROOT / "dependencies.lock.yml").read_text())
        lock_data["git"]["fiveg_ansible"]["commit"] = "main"
        with patch.object(Path, "read_text", return_value=json.dumps(lock_data)):
            with self.assertRaisesRegex(DependencyError, "full lowercase commit SHA"):
                load_lock(Path("virtual-lock.yml"))

    def test_checkout_path_cannot_escape_dependency_root(self) -> None:
        lock_data = json.loads((REPOSITORY_ROOT / "dependencies.lock.yml").read_text())
        lock_data["git"]["fiveg_ansible"]["checkout"] = "../outside"
        with patch.object(Path, "read_text", return_value=json.dumps(lock_data)):
            with self.assertRaisesRegex(DependencyError, "stay below"):
                load_lock(Path("virtual-lock.yml"))

    def test_conda_version_range_is_rejected(self) -> None:
        lock_data = json.loads((REPOSITORY_ROOT / "dependencies.lock.yml").read_text())
        lock_data["conda"]["packages"]["paho-mqtt"]["version"] = ">=2.1"
        with patch.object(Path, "read_text", return_value=json.dumps(lock_data)):
            with self.assertRaisesRegex(DependencyError, "one exact package version"):
                load_lock(Path("virtual-lock.yml"))

    def test_conda_channels_cannot_fall_back_to_defaults(self) -> None:
        lock_data = json.loads((REPOSITORY_ROOT / "dependencies.lock.yml").read_text())
        lock_data["conda"]["channels"] = ["conda-forge", "defaults"]
        with patch.object(Path, "read_text", return_value=json.dumps(lock_data)):
            with self.assertRaisesRegex(DependencyError, "exactly"):
                load_lock(Path("virtual-lock.yml"))

    def test_conda_environment_name_is_fixed(self) -> None:
        lock_data = json.loads((REPOSITORY_ROOT / "dependencies.lock.yml").read_text())
        lock_data["conda"]["environment_name"] = "something-else"
        with patch.object(Path, "read_text", return_value=json.dumps(lock_data)):
            with self.assertRaisesRegex(DependencyError, "must be 'synthran'"):
                load_lock(Path("virtual-lock.yml"))


if __name__ == "__main__":
    unittest.main()
