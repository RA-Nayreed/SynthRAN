from __future__ import annotations

import json
from pathlib import Path

from amber.capacitor import Capacitor as AmberCapacitor
from synthran.amber import AmberRunner
from synthran.amber.bridge import decoded_events
from synthran.amber.evidence import write
from synthran.model.capacitor import Capacitor as CompatibilityCapacitor


def scenario(protocol: str = "unicast") -> dict:
    return {
        "_source_directory": str(Path(__file__).parents[1] / "scenarios"),
        "model": {
            "engine": "amber",
            "seed": 7,
            "duration_ms": 80,
            "energy": {"mode": "wpt", "trace": "builtin:stable", "units": "uw"},
            "capacitor": {"initial_voltage_v": 2.0, "maximum_voltage_v": 2.0},
            "controller": {
                "threshold_low_v": 1.0,
                "threshold_high_v": 1.1,
                "max_startup_time_ms": 1,
                "currents_a": {"listening": 1e-6, "sensing": 1e-6, "processing": 1e-6, "transmitting": 1e-6},
                "durations_ms": {"listening": 1, "sensing": 1, "processing": 1, "transmitting": 1},
            },
            "topology": {
                "frequency_hz": 924000000,
                "base_station": {"sectors": [{"azimuth_deg": 0, "beamwidth_deg": 360, "power_dbm": 46}]},
            },
            "propagation": {"model": "fspl", "los": True},
            "protocol": {"type": protocol, "tx_duration_ms": 2, "rx_duration_ms": 5, "slots": 2},
            "receiver": {"sic": True, "collision_window_ms": 2},
        },
        "mqtt": {"topic_prefix": "synthran", "payload_bytes": 128},
        "devices": {"ue-a": {"x": 0, "y": 5, "subcarrier_shift": 1}},
    }


def test_compatibility_path_is_same_amber_class():
    assert CompatibilityCapacitor is AmberCapacitor


def test_runner_is_deterministic_and_bridge_uses_decoded_packets():
    first = AmberRunner(scenario()).run()
    second = AmberRunner(scenario()).run()
    first_events = decoded_events(first, scenario())
    second_events = decoded_events(second, scenario())
    assert first_events == second_events
    assert first_events
    assert all(json.loads(event["payload"])["ambient_outcome"] == "decoded" for event in first_events)
    assert all(not packet.collided for packet in first["bs_behavior"].rx_packets if packet.matched)


def test_protocols_construct_and_execute():
    for name in ("broadcast", "broadcast_sic", "unicast", "framed_aloha", "adaptive_aloha"):
        result = AmberRunner(scenario(name)).run()
        assert result["environment"].now == 80


def test_multiple_base_stations_and_evidence(tmp_path):
    configured = scenario("broadcast_sic")
    station = configured["model"]["topology"].pop("base_station")
    configured["model"]["topology"]["base_stations"] = [station, {**station, "id": 1, "x": 10}]
    result = AmberRunner(configured).run()
    bridge = write(result, configured, tmp_path)
    assert len(result["bs_behaviors"]) == 2
    assert (tmp_path / "amber" / "transitions.jsonl").exists()
    assert (tmp_path / "amber" / "bs-rx.jsonl").exists()
    assert bridge["summary"]["base_stations"] == 2


def test_custom_static_schedule():
    configured = scenario()
    configured["model"]["protocol"] = {
        "type": "custom",
        "schedule": [
            {"mode": "tx", "duration_ms": 2, "slot_id": "request", "payload": {"target": -1, "cmd": "send_data"}},
            {"mode": "rx", "duration_ms": 5, "slot_id": "response"},
        ],
    }
    assert AmberRunner(configured).run()["environment"].now == 80
