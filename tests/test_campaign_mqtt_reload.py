from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from synthran.research import ResearchError
from synthran.research.campaign_runtime import CampaignRuntimeSession


class CampaignMqttReloadTests(unittest.TestCase):
    def test_campaign_config_forces_immediate_bridge_reload(self) -> None:
        session = CampaignRuntimeSession(arguments=())
        session._original_render_edge_config = MagicMock(
            return_value=(
                "connection synthran-central\n"
                "address 192.0.2.10:18884\n"
                "restart_timeout 5\n"
            )
        )

        rendered = session._render_edge_mosquitto_config(
            object(),
            central_broker_address="192.0.2.10",
            central_broker_port=18884,
        )

        self.assertIn("bridge_reload_type immediate\nrestart_timeout 5", rendered)

    def test_campaign_reload_sends_sighup_not_sigterm(self) -> None:
        inventory = object()
        with patch(
            "synthran.research.campaign_runtime.base_runtime._remote"
        ) as remote:
            CampaignRuntimeSession._reload_edge_sidecar(inventory, "ue-pod")

        remote.assert_called_once()
        command = " ".join(str(part) for part in remote.call_args.args[1:])
        self.assertIn("kill -HUP 1", command)
        self.assertNotIn("kill -TERM 1", command)
        self.assertEqual(remote.call_args.kwargs["label"], "edge MQTT sidecar reload")

    def test_reload_keeps_restart_count_stable(self) -> None:
        inventory = object()
        reload_sidecar = MagicMock()
        statuses = [
            (4, True, True, True),
            (4, True, True, True),
        ]
        with (
            patch(
                "synthran.research.campaign_runtime."
                "research_instrumentation._edge_sidecar_status",
                side_effect=statuses,
            ),
            patch("synthran.research.campaign_runtime.time.sleep"),
        ):
            CampaignRuntimeSession._reload_edge_sidecar_and_wait(
                inventory,
                "ue-pod",
                restart=reload_sidecar,
                timeout_seconds=5,
            )

        reload_sidecar.assert_called_once_with(inventory, "ue-pod")

    def test_reload_fails_closed_if_container_restarts(self) -> None:
        inventory = object()
        reload_sidecar = MagicMock()
        statuses = [
            (4, True, True, True),
            (5, True, True, True),
        ]
        with (
            patch(
                "synthran.research.campaign_runtime."
                "research_instrumentation._edge_sidecar_status",
                side_effect=statuses,
            ),
            patch("synthran.research.campaign_runtime.time.sleep"),
            self.assertRaisesRegex(ResearchError, "restarted during in-place"),
        ):
            CampaignRuntimeSession._reload_edge_sidecar_and_wait(
                inventory,
                "ue-pod",
                restart=reload_sidecar,
                timeout_seconds=5,
            )

    def test_campaign_context_restores_reload_overrides(self) -> None:
        from synthran.experiment import runtime as base_runtime
        from synthran.research import instrumentation as research_instrumentation

        original_restart = base_runtime._restart_edge_sidecar
        original_barrier = research_instrumentation._restart_edge_sidecar_and_wait
        original_renderer = base_runtime.render_edge_mosquitto_config
        session = CampaignRuntimeSession(arguments=())

        with session:
            self.assertIsNot(base_runtime._restart_edge_sidecar, original_restart)
            self.assertIsNot(
                research_instrumentation._restart_edge_sidecar_and_wait,
                original_barrier,
            )
            self.assertIsNot(base_runtime.render_edge_mosquitto_config, original_renderer)

        self.assertIs(base_runtime._restart_edge_sidecar, original_restart)
        self.assertIs(
            research_instrumentation._restart_edge_sidecar_and_wait,
            original_barrier,
        )
        self.assertIs(base_runtime.render_edge_mosquitto_config, original_renderer)


if __name__ == "__main__":
    unittest.main()
