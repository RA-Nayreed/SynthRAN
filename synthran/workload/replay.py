from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


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
):
    import paho.mqtt.client as mqtt

    events = [
        json.loads(line)
        for line in Path(trace).read_text(encoding="utf-8").splitlines()
        if line
    ]
    if device:
        events = [event for event in events if event["device"] == device]
    records, acknowledgements = [], set()
    bind_address = bind_address or ""
    if interface:
        output_ip = subprocess.run(
            ["ip", "-j", "-4", "address", "show", "dev", interface],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        links = json.loads(output_ip)
        if (
            len(links) != 1
            or links[0].get("ifname") != interface
            or "UP" not in links[0].get("flags", [])
        ):
            raise ValueError(f"Publisher interface {interface} is missing or down")
        addresses = [
            entry["local"]
            for entry in links[0].get("addr_info", [])
            if entry.get("family") == "inet" and entry.get("scope") == "global"
        ]
        if len(addresses) != 1 or (bind_address and bind_address != addresses[0]):
            raise ValueError(
                f"Publisher address on {interface} differs from the proved binding"
            )
        bind_address = addresses[0]
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_publish = lambda _c, _u, mid, _reason, _props: acknowledgements.add(mid)
    client.connect(broker, int(port), bind_address=bind_address)
    client.loop_start()
    start = (
        datetime.fromisoformat(start_utc.replace("Z", "+00:00")).timestamp()
        if start_utc
        else time.time()
    )
    for event in events:
        wait = start + float(event["time_offset_s"]) - time.time()
        if wait > 0:
            time.sleep(wait)
        info = client.publish(event["topic"], event["payload"], qos=int(qos))
        info.wait_for_publish()
        records.append(
            {
                "event_id": event["event_id"],
                "device": event["device"],
                "mid": info.mid,
                "sent_utc": datetime.now(timezone.utc).isoformat(),
                "acknowledged": info.mid in acknowledgements or info.is_published(),
                "bind_address": bind_address,
                "interface": interface,
            }
        )
    client.disconnect()
    client.loop_stop()
    with Path(output).open("w", encoding="utf-8", newline="\n") as stream:
        for row in records:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    return records


def collect(broker, topic="synthran/#", port=1883, output="broker.jsonl"):
    import paho.mqtt.client as mqtt

    destination = Path(output)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def received(_client, _userdata, message):
        payload = json.loads(message.payload)
        row = {
            "event_id": payload["event_id"],
            "device": payload["device"],
            "topic": message.topic,
            "received_utc": datetime.now(timezone.utc).isoformat(),
        }
        with destination.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")

    client.on_message = received
    client.connect(broker, int(port))
    client.subscribe(topic, qos=1)
    client.loop_forever()
