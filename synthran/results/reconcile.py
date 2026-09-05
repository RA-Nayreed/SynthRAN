"""Reconcile Ambient-IoT model output with 5G/MQTT delivery evidence."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml


def _read(path: str | Path) -> list[dict]:
    source = Path(path)
    if not source.exists():
        return []
    return [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]


def _configured_devices(expected: str | Path, scenario: str | Path | None) -> list[str]:
    """Return the scenario device order, including devices with no decoded events."""
    source = Path(scenario) if scenario else Path(expected).parent / "resolved-scenario.yml"
    if not source.exists():
        return []
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    deployment_devices = data.get("deployment", {}).get("ues", [])
    if deployment_devices:
        return list(dict.fromkeys(str(device) for device in deployment_devices))
    return list(dict.fromkeys(str(device) for device in data.get("devices", {})))


def _binding_identity(item: dict) -> tuple:
    """Normalize transport evidence before comparing it with the deployment contract."""
    raw_index = item.get("index")
    try:
        index = int(raw_index) if raw_index is not None else None
    except (TypeError, ValueError):
        index = raw_index
    return (
        str(item.get("device")) if item.get("device") is not None else None,
        index,
        str(item.get("imsi")) if item.get("imsi") is not None else None,
        str(item.get("slice")) if item.get("slice") is not None else None,
        str(item.get("dnn")) if item.get("dnn") is not None else None,
    )


def _deployment_evidence(expected: str | Path) -> dict:
    run = Path(expected).parent.parent
    identity_path = run / "deployment-fingerprint.json"
    evidence_path = run / "live-deployment-evidence.json"
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"verified": False, "reason": "deployment identity evidence is missing or unreadable"}
    matches = identity.get("deployment_hash") == evidence.get("deployment_hash")
    cluster_verified = evidence.get("cluster_identity_verified") is True
    deployment = identity.get("deployment", {})
    bindings = evidence.get("bindings", [])
    binding_verified = (
        [_binding_identity(item) for item in bindings]
        == [_binding_identity(item) for item in deployment.get("ues", [])]
        if deployment.get("platform") in {"rfsim", "r2lab", "physical"}
        else True
    )
    status_valid = identity.get("status") in {"active", "reused"}
    verified = matches and cluster_verified and binding_verified and status_valid
    return {
        "verified": verified,
        "status": identity.get("status"),
        "deployment_hash": identity.get("deployment_hash"),
        "scenario_hash": identity.get("scenario_hash"),
        "cluster_identity_verified": cluster_verified,
        "bindings": bindings,
        "reason": None if verified else "live evidence does not completely match the deployment identity",
    }


def reconcile(expected, publisher, broker, output="summary.json", scenario=None, require_deployment_identity=False) -> dict:
    expected_rows = _read(expected)
    publisher_rows = _read(publisher)
    broker_rows = _read(broker)
    expected_ids = {row["event_id"] for row in expected_rows}
    published_ids = {row["event_id"] for row in publisher_rows}
    received_counts = Counter(row["event_id"] for row in broker_rows)
    received_ids = set(received_counts)
    acknowledged_ids = {row["event_id"] for row in publisher_rows if row.get("acknowledged")}
    configured_devices = _configured_devices(expected, scenario)
    observed_devices = {
        row.get("device", "unknown")
        for row in expected_rows + publisher_rows + broker_rows
    }
    if not configured_devices:
        configured_devices = sorted(observed_devices)
    devices = configured_devices + sorted(observed_devices - set(configured_devices))
    per_device = {}
    for device in devices:
        model_ids = {row["event_id"] for row in expected_rows if row.get("device") == device}
        per_device[device] = {
            "ambient_iot_decoded": len(model_ids),
            "published": len(model_ids & published_ids),
            "broker_received": len(model_ids & received_ids),
            "transport_lost": len((model_ids & published_ids) - received_ids),
        }
    ambient_summary_path = Path(expected).parent / "ambient_iot" / "summary.json"
    ambient = json.loads(ambient_summary_path.read_text(encoding="utf-8")) if ambient_summary_path.exists() else {"decoded": len(expected_ids)}
    suppression_count = int(ambient.get("energy_or_protocol_suppressed", 0))
    opportunity_count = int(ambient.get("opportunities", 0))
    rf_loss_count = int(ambient.get("radio_collision_loss", 0)) + int(
        ambient.get("below_sensitivity_or_unheard", 0)
    )
    summary = {
        "deployment_identity": _deployment_evidence(expected),
        "ambient_iot": ambient,
        "five_g": {
            "input": len(expected_ids),
            "published": len(expected_ids & published_ids),
            "acknowledged": len(expected_ids & acknowledged_ids),
            "received": len(expected_ids & received_ids),
            "publisher_missing": sorted(expected_ids - published_ids),
            "transport_lost": sorted((expected_ids & published_ids) - received_ids),
            "unexpected_received": sorted(received_ids - expected_ids),
            "duplicate_receipts": sum(max(0, count - 1) for count in received_counts.values()),
        },
        "per_device": per_device,
        "experimental_coverage": {
            "configured_devices": configured_devices,
            "devices_with_decoded_events": [
                device
                for device in configured_devices
                if per_device[device]["ambient_iot_decoded"] > 0
            ],
            "all_configured_devices_exercised": all(
                per_device[device]["ambient_iot_decoded"] > 0
                for device in configured_devices
            ),
            "rf_loss_observed": rf_loss_count > 0,
            "transport_loss_observed": bool((expected_ids & published_ids) - received_ids),
            "suppression_fraction": (
                suppression_count / opportunity_count if opportunity_count else 0.0
            ),
        },
    }
    if require_deployment_identity and not summary["deployment_identity"]["verified"]:
        raise ValueError(
            "result reconciliation refused: "
            + summary["deployment_identity"].get("reason", "deployment identity was not proved")
        )
    if output is not None:
        Path(output).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
