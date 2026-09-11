"""Monotonic MQTT releases and append-only publication/receipt evidence."""

from __future__ import annotations

import json
import hashlib
import math
import os
import queue
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _utc(epoch_ns=None):
    return datetime.fromtimestamp(
        (time.time_ns() if epoch_ns is None else epoch_ns) / 1e9, timezone.utc
    ).isoformat()


def _mqtt_auth(username, password_file):
    if bool(username) != bool(password_file):
        raise ValueError("MQTT username and password file must be provided together")
    if not username:
        return None
    source = Path(password_file)
    if not source.is_file():
        raise ValueError("MQTT password file is missing")
    if source.stat().st_mode & 0o077:
        raise PermissionError("MQTT password file must not be accessible by group or other")
    password = source.read_text(encoding="utf-8").rstrip("\r\n")
    if not password:
        raise ValueError("MQTT password file is empty")
    return str(username), password


class JsonlLog:
    def __init__(self, path, mode="x"):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open(mode, encoding="utf-8", newline="\n", buffering=1)
        self.lock = threading.RLock()

    def write(self, row):
        with self.lock:
            self.stream.write(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            )

    def close(self):
        with self.lock:
            self.stream.flush()
            self.stream.close()


def _bind_address(interface, address):
    if not interface:
        return address or ""
    result = subprocess.run(
        ["ip", "-j", "-4", "addr", "show", "dev", interface],
        check=True,
        capture_output=True,
        text=True,
    )
    addresses = [
        item["local"]
        for device in json.loads(result.stdout)
        for item in device.get("addr_info", [])
    ]
    if address:
        if address not in addresses:
            raise ValueError(
                "the attested bind address is absent from the selected interface"
            )
        return address
    if len(addresses) != 1:
        raise ValueError(
            "interface must have exactly one IPv4 address or an explicit --bind-address"
        )
    return addresses[0]


def replay(
    trace,
    broker,
    port=1883,
    qos=1,
    interface=None,
    start_utc=None,
    output="publisher.jsonl",
    device=None,
    bind_address=None,
    *,
    gateway=None,
    max_inflight=20,
    max_queued=10000,
    drain_seconds=60.0,
    connect_timeout=15.0,
    horizon_seconds=None,
    username=None,
    password_file=None,
):
    import paho.mqtt.client as mqtt
    from .bundle import read_events

    all_events = read_events(trace)
    if (Path(trace).parent / "source-manifest.json").exists():
        from .bundle import validate_bundle

        manifest = validate_bundle(Path(trace).parent)
        if horizon_seconds is None:
            horizon_seconds = manifest["duration_seconds"]
    if device and gateway:
        raise ValueError("choose a sensor filter or a gateway filter, not both")
    events = [
        event
        for event in all_events
        if (not device or event["device"] == device)
        and (not gateway or event.get("gateway", event["device"]) == gateway)
    ]
    horizon = max((event["time_offset_s"] for event in all_events), default=0.0)
    if horizon_seconds is not None:
        if not math.isfinite(horizon_seconds) or horizon_seconds < horizon:
            raise ValueError("replay horizon must cover every event")
        horizon = horizon_seconds
    if qos not in {0, 1} or max_inflight < 1 or max_queued < max_inflight:
        raise ValueError(
            "replay requires QoS 0/1 and positive, consistent queue limits"
        )
    if not math.isfinite(drain_seconds) or drain_seconds < 0 or connect_timeout <= 0:
        raise ValueError("invalid replay timeouts")
    address = _bind_address(interface, bind_address)
    auth = _mqtt_auth(username, password_file)
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311, clean_session=True
    )
    if auth:
        client.username_pw_set(*auth)
    client.max_inflight_messages_set(max_inflight)
    client.max_queued_messages_set(max_queued)
    connected = threading.Event()
    pending, early_acks, records = {}, {}, []
    acknowledgements = queue.SimpleQueue()
    errors = []
    run_id = uuid.uuid4().hex
    log = JsonlLog(output)

    def on_connect(_client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            errors.append(f"MQTT connection refused: {reason}")
        connected.set()

    def record_ack(mid, timestamp, monotonic, reason):
        record = pending.pop(mid)
        record["acknowledged"] = qos == 1 and not reason.is_failure
        record["ack_utc"] = timestamp
        log.write(
            {
                "record_type": "ack" if qos == 1 else "publish_complete",
                "run_id": run_id,
                "event_id": record["event_id"],
                "device": record["device"],
                "gateway": record["gateway"],
                "mid": mid,
                "ack_utc": timestamp,
                "ack_monotonic_ns": monotonic,
                "acknowledged": record["acknowledged"],
                "reason": str(reason),
                "completion_kind": "PUBACK" if qos == 1 else "client_send_complete",
            }
        )

    def on_publish(_client, _userdata, mid, reason, _properties):
        timestamp, monotonic = _utc(), time.monotonic_ns()
        acknowledgements.put((mid, timestamp, monotonic, reason))

    def process_ack(message):
        mid, timestamp, monotonic, reason = message
        if mid in pending:
            record_ack(mid, timestamp, monotonic, reason)
        else:
            early_acks[mid] = (timestamp, monotonic, reason)

    def flush_acks():
        while True:
            try:
                process_ack(acknowledgements.get_nowait())
            except queue.Empty:
                return

    def wait_until(deadline_ns):
        while True:
            remaining = (deadline_ns - time.monotonic_ns()) / 1e9
            if remaining <= 0:
                flush_acks()
                return
            try:
                process_ack(acknowledgements.get(timeout=remaining))
            except queue.Empty:
                return

    client.on_connect = on_connect
    client.on_publish = on_publish
    started = False
    try:
        client.connect(broker, int(port), bind_address=address)
        client.loop_start()
        started = True
        if not connected.wait(connect_timeout):
            raise TimeoutError(
                "MQTT CONNACK did not arrive before the connection deadline"
            )
        if errors:
            raise ConnectionError(errors[0])
        anchor_epoch_ns, anchor_monotonic_ns = time.time_ns(), time.monotonic_ns()
        if start_utc:
            parsed = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("--start-utc must contain a timezone")
            start_epoch_ns = round(parsed.timestamp() * 1e9)
            if start_epoch_ns < anchor_epoch_ns:
                raise ValueError(
                    "replay start has passed; refusing to compress overdue releases"
                )
        else:
            start_epoch_ns = anchor_epoch_ns
        start_monotonic_ns = anchor_monotonic_ns + start_epoch_ns - anchor_epoch_ns
        log.write(
            {
                "record_type": "session",
                "run_id": run_id,
                "anchor_epoch_ns": anchor_epoch_ns,
                "anchor_monotonic_ns": anchor_monotonic_ns,
                "start_epoch_ns": start_epoch_ns,
                "bind_address": address,
                "interface": interface,
                "qos": qos,
                "max_inflight": max_inflight,
                "max_queued": max_queued,
                "horizon_seconds": horizon,
                "drain_seconds": drain_seconds,
                "expected_events": len(events),
            }
        )
        for event in events:
            planned = start_monotonic_ns + round(event["time_offset_s"] * 1e9)
            wait_until(planned)
            published_ns, published_mono = time.time_ns(), time.monotonic_ns()
            if len(pending) >= max_queued:
                mid, rc = None, mqtt.MQTT_ERR_QUEUE_SIZE
            else:
                info = client.publish(
                    event["topic"], event["payload"], qos=qos, retain=False
                )
                mid, rc = info.mid, info.rc
            accepted = rc == mqtt.MQTT_ERR_SUCCESS or (
                qos == 1 and rc == mqtt.MQTT_ERR_NO_CONN
            )
            record = {
                "record_type": "publish",
                "run_id": run_id,
                "event_id": event["event_id"],
                "device": event["device"],
                "gateway": event.get("gateway", event["device"]),
                "mid": mid,
                "sent_utc": _utc(published_ns),
                "publish_monotonic_ns": published_mono,
                "planned_utc": _utc(
                    start_epoch_ns + round(event["time_offset_s"] * 1e9)
                ),
                "planned_monotonic_ns": planned,
                "release_error_s": (published_mono - planned) / 1e9,
                "publish_rc": int(rc),
                "accepted": accepted,
                "acknowledged": False,
            }
            records.append(record)
            log.write(record)
            if accepted:
                pending[mid] = record
                if mid in early_acks:
                    record_ack(mid, *early_acks.pop(mid))
            flush_acks()
        end_ns = start_monotonic_ns + round((horizon + drain_seconds) * 1e9)
        wait_until(end_ns)
        log.write(
            {
                "record_type": "session_end",
                "run_id": run_id,
                "ended_utc": _utc(),
                "outstanding_event_ids": [
                    record["event_id"] for record in pending.values()
                ],
            }
        )
    except BaseException as error:
        log.write(
            {
                "record_type": "session_failure",
                "run_id": run_id,
                "time_utc": _utc(),
                "error": str(error),
            }
        )
        raise
    finally:
        if started:
            client.disconnect()
            client.loop_stop()
            flush_acks()
        log.close()
    return records


def collect(
    broker,
    topic="synthran/#",
    port=1883,
    output="broker.jsonl",
    ready_file=None,
    *,
    username=None,
    password_file=None,
):
    import paho.mqtt.client as mqtt

    destination = Path(ready_file) if ready_file else None
    if destination:
        destination.unlink(missing_ok=True)
    log = JsonlLog(output, "a")
    auth = _mqtt_auth(username, password_file)
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311, clean_session=True
    )
    if auth:
        client.username_pw_set(*auth)

    def connected(active_client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            raise ConnectionError(f"collector connection refused: {reason}")
        active_client.subscribe(topic, qos=1)

    def subscribed(_client, _userdata, _mid, reasons, _properties):
        if any(reason.is_failure for reason in reasons):
            raise ConnectionError("collector subscription was refused")
        log.write(
            {"record_type": "collector_ready", "time_utc": _utc(), "topic": topic}
        )
        if destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "ready_utc": _utc(),
                        "topic": topic,
                        "broker": broker,
                        "port": int(port),
                    }
                ),
                encoding="utf-8",
            )
            os.replace(temporary, destination)

    def disconnected(_client, _userdata, _flags, _reason, _properties):
        log.write(
            {
                "record_type": "collector_disconnected",
                "time_utc": _utc(),
                "reason": str(_reason),
            }
        )
        if destination:
            destination.unlink(missing_ok=True)

    def received(_client, _userdata, message):
        timestamp, monotonic = _utc(), time.monotonic_ns()
        try:
            payload = json.loads(message.payload)
            if not isinstance(payload.get("event_id"), str) or not isinstance(
                payload.get("device"), str
            ):
                raise ValueError("missing event identity")
            row = {
                "record_type": "receipt",
                "event_id": payload["event_id"],
                "device": payload["device"],
                "topic": message.topic,
                "received_utc": timestamp,
                "received_monotonic_ns": monotonic,
                "generated_time_s": payload.get("generated_time_s"),
                "retained": bool(message.retain),
                "payload_sha256": hashlib.sha256(message.payload).hexdigest(),
                "payload_bytes": len(message.payload),
                "mqtt_duplicate": bool(message.dup),
            }
        except (ValueError, TypeError, AttributeError, UnicodeDecodeError) as error:
            row = {
                "record_type": "invalid_receipt",
                "received_utc": timestamp,
                "topic": message.topic,
                "error": str(error),
            }
        log.write(row)

    client.on_connect, client.on_subscribe = connected, subscribed
    client.on_disconnect, client.on_message = disconnected, received
    previous_signal = None
    if threading.current_thread() is threading.main_thread():
        previous_signal = signal.signal(signal.SIGTERM, lambda *_: client.disconnect())
    try:
        client.connect(broker, int(port))
        client.loop_forever()
    finally:
        client.disconnect()
        log.write({"record_type": "collector_end", "time_utc": _utc()})
        if destination:
            destination.unlink(missing_ok=True)
        if previous_signal is not None:
            signal.signal(signal.SIGTERM, previous_signal)
        log.close()
