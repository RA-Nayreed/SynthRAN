from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from synthran.workload.replay import replay
from test_workload_contract import event, write_rows


class LocalBroker:
    def __enter__(self):
        from amqtt.broker import Broker

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

        async def start():
            self.broker = Broker(
                {
                    "listeners": {
                        "default": {"type": "tcp", "bind": f"127.0.0.1:{self.port}"}
                    },
                    "plugins": {
                        "amqtt.plugins.authentication.AnonymousAuthPlugin": {
                            "allow_anonymous": True
                        }
                    },
                }
            )
            await self.broker.start()

        asyncio.run_coroutine_threadsafe(start(), self.loop).result(timeout=10)
        return self

    def __exit__(self, *_):
        try:
            asyncio.run_coroutine_threadsafe(self.broker.shutdown(), self.loop).result(
                timeout=10
            )
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=5)
            self.loop.close()


@unittest.skipUnless(
    importlib.util.find_spec("amqtt"),
    "install SynthRAN[test] for the local MQTT integration test",
)
class MQTTIntegrationTests(unittest.TestCase):
    def exchange(self, qos):
        import paho.mqtt.client as mqtt

        with tempfile.TemporaryDirectory() as directory, LocalBroker() as broker:
            root = Path(directory)
            ready = root / "ready.json"
            trace = [event(index, 0, f"sensor-{index % 2}") for index in range(40)]
            write_rows(
                root / "events.jsonl", [*trace, event(40, 0, "unselected", "other")]
            )
            with (root / "collector-process.log").open("w+") as process_log:
                collector = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "synthran.cli",
                        "workload",
                        "collect",
                        "--broker",
                        "127.0.0.1",
                        "--port",
                        str(broker.port),
                        "--ready-file",
                        str(ready),
                        "--output",
                        str(root / "receipts.jsonl"),
                    ],
                    cwd=Path(__file__).parents[1],
                    env=os.environ.copy(),
                    stdout=process_log,
                    stderr=subprocess.STDOUT,
                )
                try:
                    deadline = time.monotonic() + 5
                    while (
                        not ready.exists()
                        and collector.poll() is None
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.01)
                    process_log.flush()
                    self.assertTrue(
                        ready.exists(), (root / "collector-process.log").read_text()
                    )
                    rows = replay(
                        root / "events.jsonl",
                        "127.0.0.1",
                        port=broker.port,
                        qos=qos,
                        gateway="gateway",
                        output=root / "publisher.jsonl",
                        max_inflight=10,
                        max_queued=100,
                        horizon_seconds=0.05,
                        drain_seconds=0.5,
                    )
                    self.assertEqual(len(rows), 40)
                    self.assertTrue(all(row["accepted"] for row in rows))
                    self.assertEqual(
                        sum(row["acknowledged"] for row in rows), 40 if qos == 1 else 0
                    )
                    injector = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
                    injector.connect("127.0.0.1", broker.port)
                    injector.loop_start()
                    try:
                        injector.publish(
                            "synthran/invalid", "not json", qos=1
                        ).wait_for_publish(timeout=2)
                        deadline = time.monotonic() + 2
                        while (
                            "invalid_receipt"
                            not in (root / "receipts.jsonl").read_text()
                            and time.monotonic() < deadline
                        ):
                            time.sleep(0.01)
                    finally:
                        injector.disconnect()
                        injector.loop_stop()
                finally:
                    collector.terminate()
                    try:
                        collector.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        collector.kill()
                        collector.wait(timeout=5)
            self.assertEqual(
                collector.returncode, 0, (root / "collector-process.log").read_text()
            )
            self.assertFalse(ready.exists())
            records = [
                json.loads(line)
                for line in (root / "receipts.jsonl").read_text().splitlines()
            ]
            receipts = [row for row in records if row["record_type"] == "receipt"]
            self.assertEqual(
                {row["event_id"] for row in receipts},
                {row["event_id"] for row in trace},
            )
            self.assertEqual(
                {row["payload_sha256"] for row in receipts},
                {row["payload_sha256"] for row in trace},
            )
            self.assertEqual(
                sum(row["record_type"] == "invalid_receipt" for row in records), 1
            )
            self.assertEqual(records[-1]["record_type"], "collector_end")

    def test_qos1_burst_multiple_sensors_one_gateway(self):
        self.exchange(1)

    def test_qos0_completion_is_not_a_puback(self):
        self.exchange(0)


if __name__ == "__main__":
    unittest.main()
