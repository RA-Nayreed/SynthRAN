from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from synthran.research import ResearchError
from synthran.research.campaign_runtime import (
    CampaignRuntimeSession,
    _campaign_edge_config_name,
)
from synthran.rfsim_runtime import RfsimRuntimeState


class CampaignRuntimeRenderingTests(unittest.TestCase):
    def _session(self, root: Path) -> CampaignRuntimeSession:
        return CampaignRuntimeSession(
            arguments=(),
            campaign_id="campaign-test-01",
            network_run_id="network-test-01",
            expected_run_ids=("campaign-test-01-b01-baseline",),
            evidence_path=root / "runtime.json",
            target="192.0.2.10",
        )

    def test_edge_patch_is_campaign_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session = self._session(Path(temporary))
            session._original_edge_patch = lambda scenario, *, lock, core_address: {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "synthran.experiment/run": scenario.run_id,
                            }
                        },
                        "spec": {
                            "volumes": [
                                {
                                    "name": "synthran-experiment-edge-config",
                                    "configMap": {"name": "run-specific"},
                                }
                            ]
                        },
                    }
                }
            }
            first = SimpleNamespace(
                run_id="campaign-test-01-b01-baseline",
                network_run_id="network-test-01",
            )
            second = SimpleNamespace(
                run_id="campaign-test-01-b01-load95",
                network_run_id="network-test-01",
            )
            patch_one = session._render_edge_patch(first, lock=object(), core_address="192.0.2.1")
            patch_two = session._render_edge_patch(second, lock=object(), core_address="192.0.2.1")

        name = _campaign_edge_config_name("campaign-test-01")
        for value in (patch_one, patch_two):
            template = value["spec"]["template"]
            self.assertEqual(
                template["metadata"]["annotations"]["synthran.experiment/run"],
                "campaign-test-01",
            )
            self.assertEqual(
                template["spec"]["volumes"][0]["configMap"]["name"],
                name,
            )
        self.assertEqual(patch_one, patch_two)

    def test_only_edge_configmap_becomes_campaign_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            session = self._session(Path(temporary))
            session._original_experiment_objects = (
                lambda scenario, *, lock, core_node, core_address: (
                    {
                        "kind": "ConfigMap",
                        "metadata": {
                            "name": "run-edge",
                            "labels": {"synthran.experiment/run": scenario.run_id},
                        },
                    },
                    {
                        "kind": "ConfigMap",
                        "metadata": {
                            "name": "central-config",
                            "labels": {"synthran.experiment/run": scenario.run_id},
                        },
                    },
                    {
                        "kind": "Deployment",
                        "metadata": {
                            "name": "central",
                            "labels": {"synthran.experiment/run": scenario.run_id},
                        },
                    },
                )
            )
            scenario = SimpleNamespace(
                run_id="campaign-test-01-b01-load80",
                network_run_id="network-test-01",
            )
            objects = session._render_experiment_objects(
                scenario,
                lock=object(),
                core_node="core",
                core_address="192.0.2.1",
            )

        self.assertEqual(
            objects[0]["metadata"]["name"],
            _campaign_edge_config_name("campaign-test-01"),
        )
        self.assertEqual(
            objects[0]["metadata"]["labels"]["synthran.experiment/run"],
            "campaign-test-01",
        )
        self.assertEqual(
            objects[1]["metadata"]["labels"]["synthran.experiment/run"],
            "campaign-test-01-b01-load80",
        )
        self.assertEqual(
            objects[2]["metadata"]["labels"]["synthran.experiment/run"],
            "campaign-test-01-b01-load80",
        )

    def test_per_run_sidecar_cleanup_is_noop(self) -> None:
        session = CampaignRuntimeSession(arguments=())
        self.assertEqual(session._render_edge_cleanup_patch(), {})


class CampaignRuntimeIdentityTests(unittest.TestCase):
    def _session(self) -> CampaignRuntimeSession:
        session = CampaignRuntimeSession(
            arguments=(),
            campaign_id="campaign-test-01",
            network_run_id="network-test-01",
        )
        session._original_reconcile = MagicMock(
            return_value=RfsimRuntimeState(
                ue_pod="ue-a",
                gnb_pod="gnb-a",
                gnb_deployment="gnb-deployment",
                pdu_address="12.1.0.2",
            )
        )
        return session

    def test_reconcile_happens_once_then_identity_is_observed_only(self) -> None:
        session = self._session()
        inventory = object()
        first = session._reconcile_runtime(inventory, network_run_id="network-test-01")
        with (
            patch(
                "synthran.research.campaign_runtime._discover_pod",
                side_effect=["ue-a", "gnb-a"],
            ),
            patch(
                "synthran.research.campaign_runtime._current_pdu_address",
                return_value="12.1.0.2",
            ),
        ):
            second = session._reconcile_runtime(
                inventory,
                network_run_id="network-test-01",
            )

        self.assertIs(first, second)
        session._original_reconcile.assert_called_once_with(
            inventory,
            network_run_id="network-test-01",
        )

    def test_ue_pdu_drift_fails_closed(self) -> None:
        session = self._session()
        inventory = object()
        session._reconcile_runtime(inventory, network_run_id="network-test-01")
        with (
            patch(
                "synthran.research.campaign_runtime._discover_pod",
                side_effect=["ue-b", "gnb-a"],
            ),
            patch(
                "synthran.research.campaign_runtime._current_pdu_address",
                return_value="12.1.0.4",
            ),
            self.assertRaisesRegex(ResearchError, "identity drift"),
        ):
            session._reconcile_runtime(
                inventory,
                network_run_id="network-test-01",
            )

    def test_pre_window_loaded_gate_uses_transport_not_icmp(self) -> None:
        calls: list[str] = []
        spec = SimpleNamespace(load=SimpleNamespace(enabled=True))
        CampaignRuntimeSession._prove_pre_window_target(
            spec=spec,
            prove_icmp=lambda: calls.append("icmp"),
            prove_transport=lambda: calls.append("transport"),
        )
        self.assertEqual(calls, ["transport"])

    def test_pre_window_baseline_gate_requires_icmp_only(self) -> None:
        calls: list[str] = []
        spec = SimpleNamespace(load=SimpleNamespace(enabled=False))
        CampaignRuntimeSession._prove_pre_window_target(
            spec=spec,
            prove_icmp=lambda: calls.append("icmp"),
            prove_transport=lambda: calls.append("transport"),
        )
        self.assertEqual(calls, ["icmp"])


class CampaignRuntimeCleanupTests(unittest.TestCase):
    def test_campaign_exit_restores_sidecar_once_and_reproves_network(self) -> None:
        session = CampaignRuntimeSession(
            arguments=(),
            campaign_id="campaign-test-01",
            network_run_id="network-test-01",
            sidecar_patch_requested=True,
        )
        inventory = object()
        lock = object()
        session._inventory = inventory
        session._lock = lock
        session._original_reconcile = MagicMock(
            return_value=RfsimRuntimeState(
                ue_pod="ue-base",
                gnb_pod="gnb-base",
                gnb_deployment="gnb-deployment",
                pdu_address="12.1.0.8",
            )
        )
        report = SimpleNamespace(ready=True, checks=())

        with (
            patch(
                "synthran.research.campaign_runtime.base_runtime._discover_ue_deployment",
                return_value="ue-deployment",
            ),
            patch(
                "synthran.research.campaign_runtime.base_runtime._kubectl_patch_deployment"
            ) as patch_deployment,
            patch(
                "synthran.research.campaign_runtime.base_runtime._wait_rollout"
            ) as wait_rollout,
            patch(
                "synthran.research.campaign_runtime.base_runtime._delete_experiment_objects"
            ) as delete_objects,
            patch(
                "synthran.research.campaign_runtime.verify_network_path",
                return_value=report,
            ) as verify,
        ):
            session._restore_base_runtime()

        patch_deployment.assert_called_once()
        wait_rollout.assert_called_once_with(
            inventory,
            "ue-deployment",
            label="campaign srsUE cleanup rollout",
        )
        session._original_reconcile.assert_called_once_with(
            inventory,
            network_run_id="network-test-01",
        )
        delete_objects.assert_called_once_with(inventory, "campaign-test-01")
        verify.assert_called_once_with(
            inventory=inventory,
            lock=lock,
            run_id="network-test-01",
            timeout_seconds=120,
        )
        self.assertEqual(session.final_base_state.pdu_address, "12.1.0.8")


if __name__ == "__main__":
    unittest.main()
