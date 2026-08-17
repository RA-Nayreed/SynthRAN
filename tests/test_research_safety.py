from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from synthran.cli import _load_campaign
from synthran.research import CampaignCondition, ResearchError, build_campaign, save_campaign
from synthran.research_iperf import (
    OwnedIperfServer,
    start_owned_iperf_server,
    stop_owned_iperf_server,
)


class OwnedIperfLifecycleTests(unittest.TestCase):
    def test_start_uses_run_owned_pidfile_and_orphan_only_recovery(self) -> None:
        inventory = MagicMock()
        inventory.core_node = MagicMock()
        managed = MagicMock()
        managed.process.poll.return_value = None
        with (
            patch("synthran.research_iperf._reap") as reap,
            patch("synthran.research_iperf.base_runtime._remote"),
            patch(
                "synthran.research_iperf.base_runtime._start_process",
                return_value=managed,
            ) as start,
            patch(
                "synthran.research_iperf.base_runtime._remote_path_exists",
                return_value=True,
            ),
            patch(
                "synthran.research_iperf.ssh_command",
                return_value=("ssh", "iperf3"),
            ),
        ):
            server = start_owned_iperf_server(
                inventory=inventory,
                owner_id="campaign-c01-b01-high",
                port=5201,
                repository_root=Path("."),
                log_path=Path("load-server.log"),
            )
        self.assertEqual(
            server.pidfile,
            "/tmp/synthran-research/campaign-c01-b01-high/iperf3-5201.pid",
        )
        reap.assert_called_once_with(
            inventory,
            pidfile=server.pidfile,
            port=5201,
            orphan_only=True,
            label="stale research iperf3 recovery",
        )
        start.assert_called_once()

    def test_stop_reaps_exact_owned_server_and_removes_workspace(self) -> None:
        inventory = MagicMock()
        process = MagicMock()
        server = OwnedIperfServer(
            owner_id="campaign-c01-b01-high",
            port=5201,
            workspace="/tmp/synthran-research/campaign-c01-b01-high",
            pidfile="/tmp/synthran-research/campaign-c01-b01-high/iperf3-5201.pid",
            process=process,
        )
        with (
            patch("synthran.research_iperf._reap") as reap,
            patch("synthran.research_iperf.base_runtime._remote") as remote,
        ):
            stop_owned_iperf_server(inventory, server)
        process.stop.assert_called_once_with()
        reap.assert_called_once_with(
            inventory,
            pidfile=server.pidfile,
            port=5201,
            orphan_only=False,
            label="run-owned research iperf3 cleanup",
        )
        self.assertEqual(remote.call_count, 2)
        self.assertEqual(
            remote.call_args_list[0].args[1:4], ("rm", "-f", server.pidfile)
        )
        self.assertEqual(
            remote.call_args_list[1].args[1:3], ("rmdir", server.workspace)
        )


class PersistedCampaignIntegrityTests(unittest.TestCase):
    def _campaign(self):
        return build_campaign(
            campaign_id="campaign-c01",
            network_run_id="network-accepted",
            seeds=(7, 17),
            conditions=(
                CampaignCondition("baseline"),
                CampaignCondition("load-80", load_fraction=0.8),
            ),
            campaign_seed=19,
        )

    def test_saved_campaign_round_trips_exact_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            campaign = self._campaign()
            save_campaign(campaign, path)
            loaded = _load_campaign(path)
            self.assertEqual(loaded.runs, campaign.runs)

    def test_mutated_persisted_schedule_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            save_campaign(self._campaign(), path)
            value = json.loads(path.read_text(encoding="utf-8"))
            original = value["runs"][0]["condition"]
            value["runs"][0]["condition"] = (
                "baseline" if original != "baseline" else "load-80"
            )
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ResearchError, "schedule"):
                _load_campaign(path)


if __name__ == "__main__":
    unittest.main()
