from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from .scenario import load_scenario


SCHEMA_VERSION = 1
ACTIVE_ENDPOINT_SCHEMA_VERSION = 1


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def content_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: str | Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"deployment identity is missing: {path}") from error
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"deployment identity is unreadable: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"deployment identity must be a JSON object: {path}")
    return value


def resolve_scenario(source: str | Path, output: str | Path) -> dict:
    data = load_scenario(source)
    data.pop("_source_directory", None)
    _atomic_text(Path(output), yaml.safe_dump(data, sort_keys=False))
    return data


def _slice_map(profile: dict) -> dict[str, dict]:
    slices = profile.get("slices", [])
    if not isinstance(slices, list):
        raise ValueError("5G profile slices must be a list")
    result = {entry.get("name"): entry for entry in slices if isinstance(entry, dict)}
    if None in result or len(result) != len(slices):
        raise ValueError("5G profile slices must have unique names")
    return result


def _software_tunnel(ran: str, core: str, device: str, index: int) -> dict:
    if ran == "srsran":
        return {
            "namespace": core,
            "interface": f"tun_srsue{index}",
            "pod_labels": {"app": "srsran", "component": "ue"},
            "identity_file": f"/tmp/ue_{index}.conf",
        }
    if ran == "ueransim":
        match = re.fullmatch(r"uesim([0-9]+)", device)
        if not match or not 1 <= int(match.group(1)) <= 3:
            raise ValueError("the UERANSIM backend supports uesim01 through uesim03")
        return {
            "namespace": core,
            "interface": "uesimtun0",
            "pod_labels": {"component": "ue", "name": f"ue{int(match.group(1))}"},
        }
    if ran == "oai":
        release = "oai-nr-ue" if index == 1 else f"oai-nr-ue{index}"
        return {
            "namespace": core,
            "interface": "oaitun_ue1",
            "pod_name_prefix": release + "-",
        }
    raise ValueError(f"no software-tunnel identity rule for RAN {ran!r}")


def _r2lab_tunnel(device: str, profile: dict) -> dict:
    mode = profile.get("mode", "mbim")
    return {
        "host": device,
        "interface": profile.get("interface", "wwan0"),
        "mode": mode,
        "mbim_session": profile.get("mbim_session", 0) if mode == "mbim" else None,
    }


def _normalized_index(value: Any) -> Any:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return value


def _transport_value(item: dict, key: str) -> Any:
    if key in item:
        return item.get(key)
    tunnel = item.get("tunnel", {})
    return tunnel.get(key) if isinstance(tunnel, dict) else None


def binding_identity(item: dict) -> tuple:
    mode = _transport_value(item, "mode")
    session = _transport_value(item, "mbim_session")
    if mode != "mbim":
        session = None
    return (
        str(item.get("device")) if item.get("device") is not None else None,
        _normalized_index(item.get("index")),
        str(item.get("imsi")) if item.get("imsi") is not None else None,
        str(item.get("slice")) if item.get("slice") is not None else None,
        str(item.get("dnn")) if item.get("dnn") is not None else None,
        str(_transport_value(item, "host")) if _transport_value(item, "host") is not None else None,
        str(_transport_value(item, "namespace")) if _transport_value(item, "namespace") is not None else None,
        str(_transport_value(item, "interface")) if _transport_value(item, "interface") is not None else None,
        str(mode) if mode is not None else None,
        _normalized_index(session),
    )


def bindings_match_deployment(deployment: dict, bindings: list[dict]) -> bool:
    if deployment.get("platform") not in {"rfsim", "r2lab"}:
        return False
    expected = deployment.get("ues", [])
    if len(bindings) != len(expected):
        return False
    by_device = {
        str(item.get("device")): item
        for item in bindings
        if isinstance(item, dict) and item.get("device") is not None
    }
    if len(by_device) != len(bindings):
        return False
    for contract in expected:
        live = by_device.get(str(contract.get("device")))
        if live is None or binding_identity(live) != binding_identity(contract):
            return False
        if deployment.get("platform") == "r2lab" and live.get("modem_verified") is not True:
            return False
        cidr = contract.get("address_cidr")
        address = live.get("address")
        if cidr:
            if not address:
                return False
            try:
                if ipaddress.ip_address(str(address)) not in ipaddress.ip_network(str(cidr), strict=False):
                    return False
            except ValueError:
                return False
    return True


def _parse_observed_at(value: object) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("live deployment evidence has no observation timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("live deployment evidence has an invalid observation timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("live deployment evidence observation timestamp has no timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_live_evidence(
    candidate_path: str | Path,
    evidence_path: str | Path,
    *,
    max_age_seconds: int | None = 300,
) -> dict:
    candidate = read_json(candidate_path)
    evidence = read_json(evidence_path)
    deployment = candidate.get("deployment", {})
    if candidate.get("deployment_hash") != content_hash(deployment):
        raise ValueError("candidate deployment identity failed its integrity check")
    if evidence.get("deployment_hash") != candidate.get("deployment_hash"):
        raise ValueError("live deployment evidence does not match the requested deployment")
    if evidence.get("cluster_identity_verified") is not True:
        raise ValueError("live deployment evidence does not prove the cluster identity")
    if deployment.get("platform") == "r2lab":
        bindings = evidence.get("bindings")
        if not isinstance(bindings, list) or not bindings_match_deployment(deployment, bindings):
            raise ValueError("live deployment evidence does not contain complete matching UE bindings")
        observed_at = _parse_observed_at(evidence.get("observed_at"))
        if max_age_seconds is not None:
            if max_age_seconds < 0:
                raise ValueError("maximum evidence age cannot be negative")
            age = (dt.datetime.now(dt.timezone.utc) - observed_at).total_seconds()
            if age < -30:
                raise ValueError("live deployment evidence is timestamped in the future")
            if age > max_age_seconds:
                raise ValueError(
                    f"live deployment evidence is stale ({age:.0f}s old; maximum {max_age_seconds}s)"
                )
    return evidence


def build_ue_map(scenario: dict, profile: dict) -> list[dict]:
    deployment = scenario["deployment"]
    platform = str(deployment["platform"]).lower()
    ran = str(deployment["ran"]).lower()
    core = str(deployment["core"]).lower()
    plmn = profile["plmn"]
    slices = _slice_map(profile)
    result = []
    for index, device in enumerate(deployment["ues"], 1):
        ue = profile["ues"][device]
        selected_slice = slices[ue["slice"]]
        entry = {
            "device": device,
            "index": index,
            "imsi": f"{plmn['mcc']}{plmn['mnc']}{ue['imsi_suffix']}",
            "imsi_suffix": str(ue["imsi_suffix"]),
            "slice": ue["slice"],
            "sst": str(selected_slice["sst"]),
            "sd": str(selected_slice["sd"]),
            "dnn": selected_slice["dnn"],
            "address_cidr": f"{selected_slice['ip_prefix']}.0/16",
        }
        if platform == "rfsim":
            entry["tunnel"] = _software_tunnel(ran, core, device, index)
        elif platform == "r2lab":
            entry["tunnel"] = _r2lab_tunnel(device, ue)
        else:
            raise ValueError(f"unsupported platform: {platform}")
        result.append(entry)
    return result


def build_manifest(
    scenario: dict,
    profile: dict,
    ue_map: list[dict],
    topology: dict | None = None,
) -> dict:
    clean_scenario = copy.deepcopy(scenario)
    clean_scenario.pop("_source_directory", None)
    deployment = clean_scenario["deployment"]
    selected = {
        "core": str(deployment["core"]).lower(),
        "ran": str(deployment["ran"]).lower(),
        "platform": str(deployment["platform"]).lower(),
        "radio_unit": "rfsim" if deployment["platform"] == "rfsim" else deployment.get("ru", deployment["platform"]),
        "ansible_vars": copy.deepcopy(deployment.get("ansible_vars", {})),
        "host_vars": copy.deepcopy(deployment.get("host_vars", {})),
        "nodes": copy.deepcopy(deployment["nodes"]),
        "bridge_enabled": bool(deployment.get("bridge_enabled", True)),
        "profile": deployment.get("profile", "default"),
        "profile_hash": content_hash(profile),
        "plmn": copy.deepcopy(profile["plmn"]),
        "slices": copy.deepcopy(profile.get("slices", [])),
        "ues": copy.deepcopy(ue_map),
        "topology": copy.deepcopy(topology or {"namespace": str(deployment["core"]).lower()}),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "candidate",
        "scenario_hash": content_hash(clean_scenario),
        "deployment_hash": content_hash(selected),
        "deployment": selected,
    }


def invalidate(active_path: str | Path, endpoint_path: str | Path | None = None) -> None:
    value = {
        "schema_version": SCHEMA_VERSION,
        "status": "invalidated",
        "invalidated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _atomic_text(Path(active_path), json.dumps(value, indent=2, sort_keys=True) + "\n")
    if endpoint_path is not None:
        try:
            Path(endpoint_path).unlink()
        except FileNotFoundError:
            pass


def _active_endpoint(
    candidate_path: Path,
    active_path: Path,
    evidence_path: Path,
    private_dir: Path,
    deployment_hash: str,
) -> dict:
    return {
        "schema_version": ACTIVE_ENDPOINT_SCHEMA_VERSION,
        "status": "active",
        "deployment_hash": deployment_hash,
        "run_id": candidate_path.parent.name,
        "identity_file": str(active_path.resolve()),
        "evidence_file": str(evidence_path.resolve()),
        "private_execution_dir": str(private_dir.resolve()),
        "result_dir": str(candidate_path.parent.resolve()),
        "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def activate(
    candidate_path: str | Path,
    active_path: str | Path,
    evidence_path: str | Path,
    endpoint_path: str | Path,
    private_dir: str | Path,
) -> dict:
    candidate_path = Path(candidate_path)
    active_path = Path(active_path)
    evidence_path = Path(evidence_path)
    private_dir = Path(private_dir)
    validate_live_evidence(candidate_path, evidence_path)
    value = read_json(candidate_path)
    if value.get("schema_version") != SCHEMA_VERSION or value.get("deployment_hash") != content_hash(value.get("deployment", {})):
        raise ValueError("candidate deployment identity failed its integrity check")
    required_private = [private_dir / "inventory.yml", private_dir / "deployment-vars.yml"]
    missing = [str(path) for path in required_private if not path.is_file()]
    if missing:
        raise ValueError("cannot publish active deployment endpoint; missing private execution files: " + ", ".join(missing))
    value["status"] = "active"
    value["attested_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    _atomic_text(candidate_path, text)
    _atomic_text(active_path, text)
    endpoint = _active_endpoint(
        candidate_path,
        active_path,
        evidence_path,
        private_dir,
        value["deployment_hash"],
    )
    _atomic_text(Path(endpoint_path), json.dumps(endpoint, indent=2, sort_keys=True) + "\n")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m synthran.deployment_state")
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--source", required=True)
    resolve.add_argument("--output", required=True)
    invalid = commands.add_parser("invalidate")
    invalid.add_argument("--active", required=True)
    invalid.add_argument("--endpoint")
    active = commands.add_parser("activate")
    active.add_argument("--candidate", required=True)
    active.add_argument("--active", required=True)
    active.add_argument("--evidence", required=True)
    active.add_argument("--endpoint", required=True)
    active.add_argument("--private-dir", required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        if args.command == "resolve":
            resolve_scenario(args.source, args.output)
        elif args.command == "invalidate":
            invalidate(args.active, args.endpoint)
        else:
            activate(
                args.candidate,
                args.active,
                args.evidence,
                args.endpoint,
                args.private_dir,
            )
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
