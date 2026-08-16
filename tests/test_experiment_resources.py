from __future__ import annotations

from pathlib import Path
import unittest

from synthran.dependencies import load_lock
from synthran.experiment import ExperimentScenario
from synthran.experiment_resources import (
    EDGE_CONTAINER,
    RUN_LABEL,
    render_edge_cleanup_patch,
    render_edge_patch,
    render_experiment_objects,
)


class ExperimentResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = ExperimentScenario(
            "experiment-01",
            "network-accepted-01",
            "12.1.0.1",
        )
        self.lock = load_lock(Path("dependencies.lock.yml"))

    def test_edge_sidecar_is_digest_locked_and_run_owned(self) -> None:
        patch = render_edge_patch(
            self.scenario,
            lock=self.lock,
            core_address="192.0.2.10",
        )
        template = patch["spec"]["template"]
        self.assertEqual(template["metadata"]["annotations"][RUN_LABEL], "experiment-01")
        container = template["spec"]["containers"][0]
        self.assertEqual(container["name"], EDGE_CONTAINER)
        self.assertIn("@sha256:", container["image"])

    def test_cleanup_deletes_only_injected_sidecar_and_volume(self) -> None:
        patch = render_edge_cleanup_patch()
        spec = patch["spec"]["template"]["spec"]
        self.assertEqual(spec["containers"][0]["$patch"], "delete")
        self.assertEqual(spec["volumes"][0]["$patch"], "delete")

    def test_central_resources_are_run_scoped(self) -> None:
        objects = render_experiment_objects(
            self.scenario,
            lock=self.lock,
            core_node="lab-core",
            core_address="192.0.2.10",
        )
        self.assertEqual(len(objects), 3)
        for value in objects:
            self.assertEqual(
                value["metadata"]["labels"][RUN_LABEL],
                "experiment-01",
            )
            self.assertNotIn("phase3", str(value).lower())


if __name__ == "__main__":
    unittest.main()
