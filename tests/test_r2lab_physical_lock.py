from __future__ import annotations

from pathlib import Path
import unittest

from synthran.dependencies import load_lock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class R2LabPhysicalLockTests(unittest.TestCase):
    def test_physical_gnb_has_separate_digest_lock_from_rfsim(self) -> None:
        lock = load_lock(REPOSITORY_ROOT / "dependencies.lock.yml")
        containers = lock.raw["containers"]
        virtual = containers["srsran_gnb"]
        physical = containers["srsran_gnb_physical"]

        self.assertEqual("docker.io/r2labuser/srsran-gnb-zmq-csi", virtual["image"])
        self.assertEqual("docker.io/r2labuser/srsran-gnb-uhd-csi", physical["image"])
        self.assertEqual("v1.0.0.21", physical["tag"])
        self.assertEqual(
            "sha256:7c3bd04fca5e241e9e245c52cc5882bb47c522a55c32b5ed1b9a1ed8fc56a7f2",
            physical["digest"],
        )
        self.assertEqual("linux/amd64", physical["platform"])
        self.assertNotEqual(virtual["digest"], physical["digest"])
        self.assertIn("N300", physical["role"])


if __name__ == "__main__":
    unittest.main()
