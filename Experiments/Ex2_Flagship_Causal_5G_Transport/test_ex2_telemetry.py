"""Unit tests for Experiment-2 read-only transport telemetry."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from Experiments.Ex2_Flagship_Causal_5G_Transport import telemetry


class TransportTelemetryTests(unittest.TestCase):
    def test_proc_network_counter_selection(self) -> None:
        text = """\
Ip: InReceives InDiscards OutRequests OutDiscards
Ip: 100 2 90 1
Tcp: ActiveOpens PassiveOpens InSegs OutSegs RetransSegs
Tcp: 4 3 1000 900 7
Udp: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors SndbufErrors
Udp: 10 1 2 20 3 4
TcpExt: TCPSynRetrans TCPTimeouts TCPFastRetrans TCPLostRetransmit
TcpExt: 5 6 7 8
"""
        selected = telemetry._selected_network_counters(text)
        self.assertEqual(selected["Tcp"]["RetransSegs"], 7)
        self.assertEqual(selected["Udp"]["RcvbufErrors"], 3)
        self.assertEqual(selected["Ip"]["OutDiscards"], 1)
        self.assertEqual(selected["TcpExt"]["TCPTimeouts"], 6)

    def test_pod_summary_keeps_only_relevant_5g_components(self) -> None:
        payload = {
            "items": [
                {
                    "metadata": {"namespace": "oai", "name": "oai-gnb-abc", "uid": "u1"},
                    "spec": {"nodeName": "sopnode-f3"},
                    "status": {
                        "phase": "Running",
                        "podIP": "10.0.0.1",
                        "hostIP": "192.0.2.3",
                        "startTime": "2026-09-15T09:00:00Z",
                        "containerStatuses": [
                            {"name": "gnb", "ready": True, "restartCount": 0, "imageID": "sha256:a"}
                        ],
                    },
                },
                {
                    "metadata": {"namespace": "default", "name": "unrelated-web"},
                    "spec": {},
                    "status": {"phase": "Running"},
                },
            ]
        }
        result = telemetry._pod_summary(payload)
        self.assertTrue(result["available"])
        self.assertEqual(len(result["pods"]), 1)
        self.assertEqual(result["pods"][0]["name"], "oai-gnb-abc")
        self.assertEqual(result["pods"][0]["containers"][0]["restart_count"], 0)

    def test_snapshot_deduplicates_hosts_and_records_roles(self) -> None:
        environment = {
            "deployment_hash": "hash",
            "deployment": {
                "platform": "r2lab",
                "core": "oai",
                "ran": "oai",
                "radio_unit": "n320",
                "nodes": {
                    "ran": "sopnode-f3",
                    "core": "sopnode-f2",
                    "broker": "sopnode-f2",
                },
            },
            "bindings": [
                {
                    "device": "qhat01",
                    "slice": "slice1",
                    "dnn": "internet",
                    "address": "12.1.1.11",
                    "host": "qhat01",
                    "interface": "wwan0",
                },
                {
                    "device": "qhat03",
                    "slice": "slice1",
                    "dnn": "internet",
                    "address": "12.1.1.12",
                    "host": "qhat03",
                    "interface": "wwan0",
                },
            ],
        }

        def fake_host(_environment, host, roles):
            return {"host": host, "roles": roles}

        with patch.object(telemetry, "_host_snapshot", side_effect=fake_host) as snapshot:
            result = telemetry.capture_transport_snapshot(
                environment, broker_address="172.28.2.77"
            )

        self.assertTrue(result["read_only"])
        self.assertEqual(snapshot.call_count, 4)
        self.assertEqual(set(result["hosts"]), {"sopnode-f2", "sopnode-f3", "qhat01", "qhat03"})
        self.assertEqual(set(result["hosts"]["sopnode-f2"]["roles"]), {"core", "broker"})
        self.assertEqual(result["bindings"][0]["role"], "workload_ue")
        self.assertEqual(result["bindings"][1]["role"], "competing_ue")


if __name__ == "__main__":
    unittest.main()
