import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Exact Git blob IDs from sopnode/5g_ansible at
# a0149fc0dde39e2872945a0f3c91e804ece52d4f.
UPSTREAM_BLOBS = {
    "deployment/roles/r2lab/cleanup/tasks/main.yml": "6960d88f289c9b0fe94135e03a9ceda597399aee",
    "deployment/roles/r2lab/rru/tasks/main.yml": "560103d81d6fe5c067dad2d96437178fc95afa00",
    "deployment/roles/r2lab/ue/setup/tasks/main.yml": "92c353aa7a6b5a0b1f0699a44dc4203c68499ad3",
    "deployment/roles/r2lab/ue/connect/tasks/main.yml": "d13dae48d370424f48a3240f657b91d16333d62d",
    "deployment/roles/5g/srsRAN/deploy/tasks/deploy_gnb.yml": "674bfa91925ddcecf5e651b285b910ce7c99dd5f",
    "deployment/roles/5g/srsRAN/deploy/tasks/deploy_with_check.yml": "fc74ffe811ebeff449b9ab6a9472279d9fe6d00b",
}


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    payload = f"blob {len(data)}\0".encode() + data
    return hashlib.sha1(payload).hexdigest()


class R2LabUpstreamParityTests(unittest.TestCase):
    def test_upstream_owned_files_are_byte_identical(self):
        for relative, expected in UPSTREAM_BLOBS.items():
            with self.subTest(path=relative):
                path = ROOT / relative
                self.assertTrue(path.is_file(), relative)
                self.assertEqual(git_blob_sha(path), expected)

    def test_r2lab_provisioning_uses_upstream_roles(self):
        playbook = (ROOT / "deployment/playbooks/provision_r2lab.yml").read_text()
        self.assertIn("role: r2lab/cleanup", playbook)
        self.assertIn("role: r2lab/rru", playbook)
        self.assertIn("role: r2lab/ue/setup", playbook)
        self.assertNotIn("r2lab/ue_setup", playbook)
        self.assertNotIn("synthran_r2lab_preflight_ok", playbook)

    def test_r2lab_attachment_uses_upstream_connect_role(self):
        playbook = (ROOT / "deployment/playbooks/mqtt.yml").read_text()
        self.assertIn("name: r2lab/ue/connect", playbook)
        self.assertIn("when: platform == 'r2lab'", playbook)
        self.assertIn("when: platform == 'physical'", playbook)

    def test_r2lab_publisher_uses_upstream_wwan0_without_binding_contract(self):
        replay = (
            ROOT / "deployment/roles/synthran/publisher/tasks/replay.yml"
        ).read_text()
        self.assertIn("--interface wwan0", replay)
        r2lab_section = replay.split(
            "- name: Replay through a non-R2Lab physical UE", 1
        )[0]
        self.assertNotIn("synthran_physical_binding", r2lab_section)
        self.assertNotIn("--bind-address", r2lab_section)


if __name__ == "__main__":
    unittest.main()
