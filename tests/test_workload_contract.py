from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from synthran.results.metrics import age_process, measurements
from synthran.results.reconcile import reconcile
from synthran.workload.bundle import (
    canonical,
    import_bundle,
    read_events,
    transform_bundle,
    validate_bundle,
    write_manifest,
)
from synthran.workload.replay import replay
from synthran.workload.trace import generate
from test_scientific_model import scenario


def event(index, offset, device="sensor", gateway="gateway"):
    payload = canonical(
        {"event_id": str(index), "device": device, "generated_time_s": offset / 2}
    ).decode()
    return {
        "event_id": str(index),
        "device": device,
        "gateway": gateway,
        "topic": f"synthran/{device}",
        "payload": payload,
        "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "time_offset_s": offset,
        "decode_time_s": offset,
        "generated_time_s": offset / 2,
    }


def write_rows(path, rows):
    Path(path).write_text(
        "".join(canonical(row).decode() + "\n" for row in rows), encoding="utf-8"
    )


def make_bundle(path):
    path.mkdir()
    write_rows(
        path / "events.jsonl",
        [event(index, offset) for index, offset in enumerate([0.1, 1, 1, 2, 5, 8])],
    )
    (path / "resolved-scenario.yml").write_text(yaml.safe_dump(scenario()))
    return write_manifest(
        path,
        {
            "event_count": 6,
            "duration_seconds": 10,
            "sensor_gateways": {"sensor": "gateway"},
            "mqtt": {"payload_bytes": 256},
            "transformation": {"variant": "native", "generation_age_valid": True},
        },
    )


class BundleTests(unittest.TestCase):
    def test_interventions_preserve_identity_bytes_endpoints_warmup_and_gap_multiset(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = make_bundle(root / "native")
            original = read_events(root / "native/events.jsonl")
            for variant in ("native", "gap_permutation", "periodic"):
                output = root / f"derived-{variant}"
                transform_bundle(
                    root / "native", output, variant, seed=9, warmup_seconds=1
                )
                derived_manifest = validate_bundle(output)
                derived = read_events(output / "events.jsonl")
                self.assertEqual(original[0], derived[0])
                for before, after in zip(original, derived):
                    self.assertEqual(
                        {k: v for k, v in before.items() if k != "time_offset_s"},
                        {k: v for k, v in after.items() if k != "time_offset_s"},
                    )
                self.assertEqual(
                    original[1]["time_offset_s"], derived[1]["time_offset_s"]
                )
                self.assertEqual(
                    original[-1]["time_offset_s"], derived[-1]["time_offset_s"]
                )
                self.assertEqual(
                    derived_manifest["transformation"]["source_bundle_sha256"],
                    manifest["bundle_sha256"],
                )
                self.assertEqual(
                    derived_manifest["transformation"]["generation_age_valid"],
                    variant == "native",
                )
                offsets = [row["time_offset_s"] for row in derived[1:]]
                gaps = [b - a for a, b in zip(offsets, offsets[1:])]
                if variant == "gap_permutation":
                    self.assertEqual(sorted(gaps), [0, 1, 3, 3])
                if variant == "periodic":
                    self.assertEqual(gaps, [1.75] * 4)
            self.assertEqual(validate_bundle(root / "native"), manifest)

    def test_import_preserves_source_hash_and_rejects_mapping_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = make_bundle(root / "native")
            config = root / "config.yml"
            config.write_text(yaml.safe_dump(scenario()))
            import_bundle(root / "native", root / "imported", config)
            self.assertEqual(validate_bundle(root / "imported"), manifest)
            changed = scenario()
            changed["devices"]["sensor"]["gateway"] = "background"
            config.write_text(yaml.safe_dump(changed))
            with self.assertRaises(ValueError):
                import_bundle(root / "native", root / "bad", config)

    def test_corruption_unsafe_paths_overwrite_and_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_bundle(root / "native")
            with self.assertRaises(ValueError):
                transform_bundle(root / "native", root / "native", "native")
            with (root / "native/events.jsonl").open("a") as stream:
                stream.write("{}\n")
            with self.assertRaises(ValueError):
                validate_bundle(root / "native")
            make_bundle(root / "unsafe")
            manifest = json.loads((root / "unsafe/source-manifest.json").read_text())
            manifest["files"]["../outside"] = "0" * 64
            manifest.pop("bundle_sha256")
            manifest["bundle_sha256"] = hashlib.sha256(canonical(manifest)).hexdigest()
            (root / "unsafe/source-manifest.json").write_bytes(canonical(manifest))
            with self.assertRaises(ValueError):
                validate_bundle(root / "unsafe")
            write_rows(root / "duplicate.jsonl", [event(0, 0), event(0, 1)])
            with self.assertRaises(ValueError):
                read_events(root / "duplicate.jsonl")

    def test_generated_bundle_is_repeatable_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configuration = scenario(100)
            configuration["mqtt"]["password"] = "never-export-this"
            config = root / "config.yml"
            config.write_text(yaml.safe_dump(configuration))
            for name in ("first", "second"):
                generate(config, root / name)
            first, second = validate_bundle(root / "first"), validate_bundle(
                root / "second"
            )
            self.assertEqual(first, second)
            self.assertIn(
                "model/controller.py", first["implementation"]["source_sha256"]
            )
            self.assertNotIn(
                "never-export-this", (root / "first/source-manifest.json").read_text()
            )
            self.assertNotIn(
                "never-export-this", (root / "first/resolved-scenario.yml").read_text()
            )


class FreshnessTests(unittest.TestCase):
    def test_aoi_integral_quantile_violations_and_stale_updates(self):
        reference = age_process([(0, 0), (2, 1)], 0, 4, 2)
        self.assertAlmostEqual(reference["time_average_aoi_s"], 1.5)
        self.assertAlmostEqual(reference["initialized_time_p95_aoi_s"], 2.8)
        self.assertAlmostEqual(reference["freshness_violation_fraction"], 0.25)
        self.assertEqual(
            reference, age_process([(0, 0), (2, 1), (3, 0.5), (3, 1)], 0, 4, 2)
        )

    def test_initial_age_is_unknown_and_pre_window_history_initializes_it(self):
        unknown = age_process([(2, 1)], 0, 4, 2)
        self.assertIsNone(unknown["time_average_aoi_s"])
        self.assertEqual(unknown["uninitialized_fraction"], 0.5)
        self.assertEqual(age_process([(0, 0)], 2, 4, 2)["time_average_aoi_s"], 3)
        with self.assertRaises(ValueError):
            age_process([(0, 1)], 0, 4, 2)

    def fixture(self):
        utc = lambda value: datetime.fromtimestamp(
            1000 + value, timezone.utc
        ).isoformat()
        expected = [event(0, 1), event(1, 2)]
        published = [
            {
                "event_id": row["event_id"],
                "sent_utc": utc(row["time_offset_s"]),
                "planned_utc": utc(row["time_offset_s"]),
                "release_error_s": 0,
            }
            for row in expected
        ]
        receipts = [{"event_id": "0", "received_utc": utc(1.2)}]
        sessions = [{"start_epoch_ns": 1000 * 10**9}]
        manifest = {
            "duration_seconds": 4,
            "sensor_gateways": {"sensor": "gateway"},
            "transformation": {"generation_age_valid": True},
        }
        contract = {
            "deadline_seconds": 0.5,
            "clock_uncertainty_seconds": 0.001,
            "age_limit_seconds": 2,
        }
        return (
            expected,
            published,
            receipts,
            sessions,
            manifest,
            contract,
            [{"record_type": "collector_end", "time_utc": utc(5)}],
        )

    def test_missing_deliveries_count_in_deadline_denominator(self):
        rows = self.fixture()
        result = measurements(*rows)
        self.assertEqual(result["deadline_failure_fraction"], 0.5)
        self.assertEqual(result["cohort_events"], 2)
        self.assertAlmostEqual(result["conditional_receipt_delay_p50_s"], 0.2)
        self.assertTrue(result["physical_aoi_eligible"])
        rows[-1].clear()
        self.assertIsNone(measurements(*rows)["deadline_failure_fraction"])

    def test_negative_latency_clock_qualification_and_surrogate_aoi(self):
        rows = self.fixture()
        rows[2][0]["received_utc"] = datetime.fromtimestamp(
            1000.9, timezone.utc
        ).isoformat()
        result = measurements(*rows)
        self.assertFalse(result["clock_contract_satisfied"])
        self.assertFalse(result["physical_aoi_eligible"])
        self.assertEqual(result["negative_latency_event_ids"], ["0"])
        rows = self.fixture()
        rows[4]["transformation"]["generation_age_valid"] = False
        result = measurements(*rows)
        self.assertNotIn("application_aoi", result)
        self.assertFalse(result["physical_aoi_eligible"])

    def test_reconcile_counts_records_separately_and_checks_receipt_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = [event(0, 0.1), event(1, 0.2)]
            write_rows(root / "events.jsonl", expected)
            timestamp = datetime.now(timezone.utc).isoformat()
            write_rows(
                root / "publisher.jsonl",
                [
                    {
                        "record_type": "publish",
                        "event_id": "0",
                        "device": "sensor",
                        "accepted": True,
                        "sent_utc": timestamp,
                    },
                    {
                        "record_type": "ack",
                        "event_id": "0",
                        "device": "sensor",
                        "acknowledged": True,
                    },
                    {
                        "record_type": "publish",
                        "event_id": "1",
                        "device": "sensor",
                        "accepted": False,
                        "sent_utc": timestamp,
                    },
                ],
            )
            good = {
                "record_type": "receipt",
                "event_id": "0",
                "device": "sensor",
                "received_utc": timestamp,
                "topic": expected[0]["topic"],
                "payload_sha256": expected[0]["payload_sha256"],
            }
            write_rows(
                root / "broker.jsonl",
                [good, good, {**good, "event_id": "1", "payload_sha256": "wrong"}],
            )
            result = reconcile(
                root / "events.jsonl",
                root / "publisher.jsonl",
                root / "broker.jsonl",
                output=None,
            )
            self.assertEqual(result["five_g"]["published"], 1)
            self.assertEqual(result["five_g"]["acknowledged"], 1)
            self.assertEqual(result["five_g"]["received"], 1)
            self.assertEqual(result["five_g"]["duplicate_receipts"], 1)
            self.assertEqual(
                result["five_g"]["receipt_integrity_mismatch_event_ids"], ["1"]
            )


class ReplayTests(unittest.TestCase):
    def test_mqtt_runtime_import_needs_no_numerical_packages(self):
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "from synthran.workload.replay import replay, collect",
            ],
            cwd=Path(__file__).parents[1],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gateway_filter_release_order_early_callbacks_and_append_only_logs(self):
        import paho.mqtt.client as mqtt

        callbacks = []

        class Client:
            def __init__(self, *args, **kwargs):
                self.mid = 0

            def max_inflight_messages_set(self, count):
                pass

            def max_queued_messages_set(self, count):
                pass

            def connect(self, *args, **kwargs):
                self.on_connect(
                    self, None, None, SimpleNamespace(is_failure=False), None
                )

            def loop_start(self):
                pass

            def publish(self, topic, payload, qos, retain):
                self.mid += 1
                callbacks.append(json.loads(payload)["event_id"])
                self.on_publish(
                    self, None, self.mid, SimpleNamespace(is_failure=False), None
                )
                return SimpleNamespace(mid=self.mid, rc=mqtt.MQTT_ERR_SUCCESS)

            def disconnect(self):
                pass

            def loop_stop(self):
                pass

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(mqtt, "Client", Client),
        ):
            root = Path(directory)
            write_rows(
                root / "events.jsonl",
                [event(0, 0), event(1, 0, "sensor2"), event(2, 0, "sensor3", "other")],
            )
            rows = replay(
                root / "events.jsonl",
                "unused",
                gateway="gateway",
                output=root / "publisher.jsonl",
                drain_seconds=0,
            )
            self.assertEqual(callbacks, ["0", "1"])
            self.assertTrue(all(row["acknowledged"] for row in rows))
            records = [
                json.loads(line)
                for line in (root / "publisher.jsonl").read_text().splitlines()
            ]
            self.assertEqual(
                [row["record_type"] for row in records],
                ["session", "publish", "ack", "publish", "ack", "session_end"],
            )
            self.assertFalse(records[1]["acknowledged"])
            self.assertEqual(records[-1]["outstanding_event_ids"], [])
            with self.assertRaises(FileExistsError):
                replay(
                    root / "events.jsonl",
                    "unused",
                    output=root / "publisher.jsonl",
                    drain_seconds=0,
                )
            rows = replay(
                root / "events.jsonl",
                "unused",
                qos=0,
                output=root / "qos0.jsonl",
                drain_seconds=0,
            )
            self.assertTrue(all(not row["acknowledged"] for row in rows))


if __name__ == "__main__":
    unittest.main()
