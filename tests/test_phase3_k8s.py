from __future__ import annotations

from pathlib import Path
import unittest

from synthran.dependencies import load_lock
from synthran.phase3_k8s import EDGE_CONTAINER, EDGE_VOLUME, render_edge_cleanup_patch, render_edge_patch, render_phase3_objects
from synthran.phase3_runtime import Phase3Scenario


class Phase3KubernetesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load_lock(Path("dependencies.lock.yml"))
        self.scenario = Phase3Scenario(
            "phase3-01",
            "acceptance-20260815-05",
            "12.1.0.1",
        )

    def test_edge_sidecar_uses_locked_mosquitto_digest(self) -> None:
        patch = render_edge_patch(
            self.scenario,
            lock=self.lock,
            core_address="172.28.2.77",
        )
        container = patch["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(container["name"], EDGE_CONTAINER)
        self.assertIn("@sha256:", container["image"])
        self.assertEqual(
            patch["spec"]["template"]["spec"]["volumes"][0]["name"],
            EDGE_VOLUME,
        )

    def test_cleanup_patch_removes_only_phase3_additions(self) -> None:
        patch = render_edge_cleanup_patch()
        template = patch["spec"]["template"]
        self.assertEqual(
            template["spec"]["containers"],
            [{"name": EDGE_CONTAINER, "$patch": "delete"}],
        )
        self.assertEqual(
            template["spec"]["volumes"],
            [{"name": EDGE_VOLUME, "$patch": "delete"}],
        )

    def test_central_broker_is_host_network_and_core_pinned(self) -> None:
        objects = render_phase3_objects(
            self.scenario,
            lock=self.lock,
            core_node="sopnode-f2",
            core_address="172.28.2.77",
        )
        self.assertEqual(len(objects), 3)
        central = objects[2]
        pod_spec = central["spec"]["template"]["spec"]
        self.assertTrue(pod_spec["hostNetwork"])
        self.assertEqual(
            pod_spec["nodeSelector"]["kubernetes.io/hostname"],
            "sopnode-f2",
        )
        config = objects[0]["data"]["mosquitto.conf"]
        self.assertIn("bridge_bind_address 12.1.0.1", config)
        self.assertIn("address 172.28.2.77:18884", config)


if __name__ == "__main__":
    unittest.main()
