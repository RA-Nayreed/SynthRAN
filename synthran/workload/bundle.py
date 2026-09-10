"""Immutable workload bundles and event-identical timing interventions."""

from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
from pathlib import Path

MANIFEST = "source-manifest.json"


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_events(path):
    events, identifiers = [], set()
    previous = -math.inf
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            event = json.loads(line)
            for field in ("event_id", "device", "topic", "payload"):
                if not isinstance(event.get(field), str) or not event[field]:
                    raise ValueError(f"trace event requires {field}")
            offset = event.get("time_offset_s")
            if (
                not isinstance(offset, (float, int))
                or not math.isfinite(offset)
                or offset < 0
                or offset < previous
            ):
                raise ValueError(
                    "trace offsets must be finite, nonnegative and nondecreasing"
                )
            payload = json.loads(event["payload"])
            if (
                payload.get("event_id") != event["event_id"]
                or payload.get("device") != event["device"]
            ):
                raise ValueError(
                    "trace identity does not match the serialized MQTT payload"
                )
            if event["event_id"] in identifiers:
                raise ValueError("trace event IDs must be unique")
            if (
                "payload_sha256" in event
                and hashlib.sha256(event["payload"].encode()).hexdigest()
                != event["payload_sha256"]
            ):
                raise ValueError("trace payload checksum mismatch")
            identifiers.add(event["event_id"])
            previous = offset
            events.append(event)
    return events


def write_manifest(directory, metadata):
    directory = Path(directory)
    files = {
        str(path.relative_to(directory)): digest(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != MANIFEST
    }
    manifest = {**metadata, "schema_version": 1, "files": files}
    manifest["bundle_sha256"] = hashlib.sha256(canonical(manifest)).hexdigest()
    (directory / MANIFEST).write_bytes(canonical(manifest) + b"\n")
    return manifest


def validate_bundle(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    expected_digest = manifest.pop("bundle_sha256", None)
    if (
        manifest.get("schema_version") != 1
        or hashlib.sha256(canonical(manifest)).hexdigest() != expected_digest
    ):
        raise ValueError("workload manifest failed its integrity check")
    manifest["bundle_sha256"] = expected_digest
    if (
        "events.jsonl" not in manifest["files"]
        or "resolved-scenario.yml" not in manifest["files"]
    ):
        raise ValueError("workload bundle lacks required evidence")
    for name, checksum in manifest["files"].items():
        path = directory / name
        if (
            Path(name).is_absolute()
            or ".." in Path(name).parts
            or path.is_symlink()
            or not path.resolve().is_relative_to(directory)
        ):
            raise ValueError("bundle contains an unsafe artifact path")
        if not path.is_file() or digest(path) != checksum:
            raise ValueError(f"bundle artifact checksum mismatch: {name}")
    events = read_events(directory / "events.jsonl")
    horizon = manifest["duration_seconds"]
    if (
        not math.isfinite(horizon)
        or horizon <= 0
        or any(event["time_offset_s"] >= horizon for event in events)
    ):
        raise ValueError("bundle horizon does not cover its events")
    if len(events) != manifest["event_count"]:
        raise ValueError("bundle event count mismatch")
    for event in events:
        if manifest["sensor_gateways"].get(event["device"]) != event.get(
            "gateway", event["device"]
        ):
            raise ValueError("trace sensor/gateway mapping differs from its manifest")
    return manifest


def _copy_bundle(source, destination, manifest):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or destination.is_relative_to(source):
        raise ValueError("output must be outside the source bundle")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("refusing to overwrite an existing workload bundle")
    destination.mkdir(parents=True, exist_ok=True)
    for name in [*manifest["files"], MANIFEST]:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)


def import_bundle(source, destination, scenario):
    from synthran.scenario import load_scenario

    manifest = validate_bundle(source)
    configured = load_scenario(scenario)
    mapping = {
        name: device["gateway"] for name, device in configured["devices"].items()
    }
    if mapping != manifest["sensor_gateways"]:
        raise ValueError(
            "prepared workload sensor/gateway mapping differs from the requested scenario"
        )
    mqtt = configured["mqtt"]
    for field in ("qos", "payload_bytes", "topic_prefix"):
        if mqtt.get(field) != manifest["mqtt"].get(field):
            raise ValueError(
                f"prepared workload MQTT {field} differs from the requested scenario"
            )
    _copy_bundle(source, destination, manifest)
    return Path(destination) / "events.jsonl"


def transform_bundle(source, destination, variant, seed=1, warmup_seconds=0.0):
    manifest = validate_bundle(source)
    if manifest.get("transformation", {}).get("variant", "native") != "native":
        raise ValueError("timing interventions require a native source bundle")
    if variant not in {"native", "gap_permutation", "periodic"}:
        raise ValueError("unknown timing intervention")
    if (
        not math.isfinite(warmup_seconds)
        or not 0 <= warmup_seconds < manifest["duration_seconds"]
    ):
        raise ValueError("warm-up must lie within the source horizon")
    original = read_events(Path(source) / "events.jsonl")
    measurement = [
        event for event in original if event["time_offset_s"] >= warmup_seconds
    ]
    offsets = [event["time_offset_s"] for event in measurement]
    if len(offsets) > 1:
        if variant == "gap_permutation":
            gaps = [right - left for left, right in zip(offsets, offsets[1:])]
            random.Random(seed).shuffle(gaps)
            offsets = [offsets[0]]
            for gap in gaps:
                offsets.append(offsets[-1] + gap)
            offsets[-1] = measurement[-1]["time_offset_s"]
        elif variant == "periodic":
            first, last = offsets[0], offsets[-1]
            offsets = [
                first + index * (last - first) / (len(offsets) - 1)
                for index in range(len(offsets))
            ]
            offsets[-1] = last
    derived = [dict(event) for event in original]
    iterator = iter(offsets)
    for event in derived:
        if event["time_offset_s"] >= warmup_seconds:
            event["time_offset_s"] = next(iterator)
    _copy_bundle(source, destination, manifest)
    destination = Path(destination)
    (destination / "native-events.jsonl").write_bytes(
        (Path(source) / "events.jsonl").read_bytes()
    )
    (destination / "native-source-manifest.json").write_bytes(
        (Path(source) / MANIFEST).read_bytes()
    )
    with (destination / "events.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        for event in derived:
            stream.write(canonical(event).decode() + "\n")
    metadata = {
        key: value
        for key, value in manifest.items()
        if key not in {"files", "bundle_sha256"}
    }
    metadata["transformation"] = {
        "variant": variant,
        "seed": seed,
        "warmup_seconds": warmup_seconds,
        "source_bundle_sha256": manifest["bundle_sha256"],
        "native_trace_sha256": manifest["files"]["events.jsonl"],
        "generation_age_valid": variant == "native",
    }
    write_manifest(destination, metadata)
    validate_bundle(destination)
    return destination / "events.jsonl"
