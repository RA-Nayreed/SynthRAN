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

# PR7 also changed shared files only to support its custom R2Lab guardrails.
# The refactor intentionally restores those files to the pre-PR7 SynthRAN base
# instead of replacing unrelated RFSIM/SynthRAN behavior with upstream wholesale.
SYNTHRAN_BASE_BLOBS = {
    "deployment/roles/5g/srsRAN/common/defaults/main.yml": "4a2bf0cb955f116b275adb5f77564abb329fbd5b",
    "deployment/roles/5g/srsRAN/config/tasks/main.yml": "6d42f7853112ace49e3e1a39b97b321b317408f0",
    "deployment/roles/setup/optimization/cpu/tasks/main.yml": "8db139bb808a2596b7adbffdf2c771a900d326d2",
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

    def test_pr7_only_shared_guardrail_changes_are_gone(self):
        for relative, expected in SYNTHRAN_BASE_BLOBS.items():
            with self.subTest(path=relative):
                path = ROOT / relative
                self.assertTrue(path.is_file(), relative)
                self.assertEqual(git_blob_sha(path), expected)
        self.assertFalse(
            (ROOT / "deployment/roles/r2lab/rru/defaults/main.yml").exists()
        )

    def test_r2lab_provisioning_uses_upstream_roles(self):
        playbook = (ROOT / "deployment/playbooks/provision_r2lab.yml").read_text()
        self.assertIn("role: r2lab/cleanup", playbook)
        self.assertIn("role: r2lab/rru", playbook)
        self.assertIn("role: r2lab/ue/setup", playbook)
        self.assertNotIn("r2lab/ue_setup", playbook)
        self.assertNotIn("synthran_r2lab_preflight_ok", playbook)

    def test_r2lab_attachment_uses_upstream_connect_role(self):
        playbook = (ROOT / "deployment/playbooks/mqtt.yml").read_text()
        start = playbook.index("- name: Connect R2Lab UEs with the upstream 5g_ansible role")
        end = playbook.index("- name: Prepare non-R2Lab physical UE interfaces")
        r2lab_connect = playbook[start:end]
        self.assertIn("name: r2lab/ue/connect", r2lab_connect)
        self.assertIn("when: platform == 'r2lab'", r2lab_connect)
        self.assertIn("any_errors_fatal: true", r2lab_connect)
        self.assertNotIn("ignore_errors:", r2lab_connect)

        non_r2lab = playbook[end:]
        self.assertIn("name: synthran/physical_ue", non_r2lab)
        self.assertIn("when: platform == 'physical'", non_r2lab)

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

    def test_removed_custom_r2lab_guardrail_names_do_not_return(self):
        files = [
            ROOT / "deployment/playbooks/network.yml",
            ROOT / "deployment/playbooks/provision_r2lab.yml",
            ROOT / "deployment/roles/5g/srsRAN/common/defaults/main.yml",
            ROOT / "deployment/roles/5g/srsRAN/config/tasks/main.yml",
            ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/deploy_with_check.yml",
        ]
        text = "\n".join(path.read_text() for path in files)
        for forbidden in (
            "synthran_r2lab_preflight_ok",
            "physical_gnb_startup_timeout_seconds",
            "physical_gnb_stability_seconds",
            "synthran_radio_overrides",
            "gnb_startup_gate",
            "exec stdbuf -oL -eL",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
