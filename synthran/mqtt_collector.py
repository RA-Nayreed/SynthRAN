"""MQTT telemetry collector for the integrated IoT-to-5G experiment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
from typing import Any

from synthran.experiment import (
    ExperimentError,
    ExperimentScenario,
    TelemetryEvent,
    append_jsonl,
    append_rejected,
    load_jsonl,
    validate_sequence_integrity,
)


@dataclass(frozen=True)
class CollectionResult:
    records: int
    sensors: int
    completed: bool


def _mqtt_reason_succeeded(reason_code: Any) -> bool:
    """Return whether a Paho v1/v2 connect reason represents success.

    Callback API v2 passes a ReasonCode object.  It is intentionally not
    coerced with int(): some Paho versions do not implement integer coercion,
    which previously turned the literal Success reason into a refusal.
    """
    marker = getattr(reason_code, "is_failure", None)
    if marker is not None:
        try:
            marker = marker() if callable(marker) else marker
            return not bool(marker)
        except Exception:
            return False
    try:
        return int(reason_code) == 0
    except (TypeError, ValueError):
        return reason_code == 0


def collect_mqtt(
    scenario: ExperimentScenario,
    *,
    host: str,
    port: int,
    jsonl_path: Path,
    rejected_path: Path,
    minimum_per_sensor: int = 3,
    timeout_seconds: int = 180,
) -> CollectionResult:
    """Collect until every deterministic sensor has a contiguous sequence window."""

    if minimum_per_sensor < 1:
        raise ExperimentError("minimum_per_sensor must be positive")
    if timeout_seconds < 1:
        raise ExperimentError("collector timeout must be positive")
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise ExperimentError("paho-mqtt is required for live telemetry collection") from exc

    condition = threading.Condition()
    last_error: list[str] = []
    connected = False

    def on_connect(client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        nonlocal connected
        with condition:
            connected = _mqtt_reason_succeeded(reason_code)
            if connected:
                client.subscribe(scenario.sensor_topic, qos=0)
            else:
                last_error[:] = [f"central MQTT connection refused ({reason_code})"]
            condition.notify_all()

    def on_message(client: Any, userdata: Any, message: Any) -> None:
        del client, userdata
        topic = str(message.topic)
        try:
            event = TelemetryEvent.from_payload(message.payload, scenario.run_id)
            expected_topic = f"{scenario.topic_root}/sensor/{event.sensor_id}"
            if topic != expected_topic:
                raise ExperimentError("MQTT topic does not match telemetry sensor ID")
            append_jsonl(
                jsonl_path,
                event.to_record(received_at_utc=datetime.now(timezone.utc)),
            )
        except ExperimentError as exc:
            append_rejected(rejected_path, reason=str(exc), topic=topic)
        with condition:
            condition.notify_all()

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"synthran-collector-{scenario.run_id}",
        protocol=mqtt.MQTTv311,
        clean_session=True,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    deadline = time.monotonic() + timeout_seconds
    try:
        client.connect(host, port, keepalive=30)
        client.loop_start()
        with condition:
            while not connected and not last_error:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ExperimentError("central MQTT collector connection timed out")
                condition.wait(timeout=min(1.0, remaining))
        if last_error:
            raise ExperimentError(last_error[0])

        while True:
            if jsonl_path.is_file():
                records = load_jsonl(jsonl_path, expected_run_id=scenario.run_id)
                failures = validate_sequence_integrity(
                    records,
                    minimum_per_sensor=minimum_per_sensor,
                )
                sensors = {str(record["sensor_id"]) for record in records}
                if len(sensors) == scenario.sensor_count and not failures:
                    return CollectionResult(len(records), len(sensors), True)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                records = (
                    load_jsonl(jsonl_path, expected_run_id=scenario.run_id)
                    if jsonl_path.is_file()
                    else []
                )
                sensors = {str(record["sensor_id"]) for record in records}
                return CollectionResult(len(records), len(sensors), False)
            with condition:
                condition.wait(timeout=min(1.0, remaining))
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
        client.loop_stop()
