"""Durable desired/live identity contract for SynthRAN deployments."""
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
            # OAI gives the primary PDU-session interface this name inside
            # every NR-UE pod. The numbered Helm release/pod, rather than the
            # interface name, distinguishes UE2 and UE3 from UE1.
            "interface": "oaitun_ue1",
            "pod_name_prefix": release + "-",
        }
    raise ValueError(f"no software-tunnel identity rule for RAN {ran!r}")


def _physical_tunnel(device: str, profile: dict) -> dict:
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
    """Normalize desired/live UE transport identity into one comparable tuple."""
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
    """Require complete UE identity, interface/session, and slice-address evidence."""
    if deployment.get("platform") not in {"rfsim", "r2lab", "physical"}:
        return True

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
        if deployment.get("platform") in {"r2lab", "physical"} and live.get("modem_verified") is not True:
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


def _normalize_legacy_oai_deployment(deployment: dict) -> dict | None:
    """Return the supported legacy OAI tunnel correction, if applicable."""
    normalized = copy.deepcopy(deployment)
    source_ues = normalized.get("ues", [])
    if (
        normalized.get("platform") == "rfsim"
        and normalized.get("ran") == "oai"
        and source_ues
        and all(
            ue.get("tunnel", {}).get("interface") == f"oaitun_ue{ue.get('index')}"
            for ue in source_ues
        )
    ):
        for ue in source_ues:
            ue["tunnel"]["interface"] = "oaitun_ue1"
        return normalized
    return None


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
        else:
            entry["tunnel"] = _physical_tunnel(device, ue)
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
    selection = clean_scenario.get('experiment', {})
    if selection.get('config'):
        selection['config'] = 'sha256:' + hashlib.sha256(Path(selection['config']).read_bytes()).hexdigest()
    deployment = clean_scenario["deployment"]
    selected = {
        "core": str(deployment["core"]).lower(),
        "ran": str(deployment["ran"]).lower(),
        "platform": str(deployment["platform"]).lower(),
        "radio_unit": "rfsim" if deployment["platform"] == "rfsim" else deployment.get("ru", deployment["platform"]),
        "radio": copy.deepcopy(deployment.get("radio", {})),
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


def _flatten(value: Any, prefix: str = "deployment") -> dict[str, Any]:
    if isinstance(value, dict):
        result = {}
        for key in sorted(value):
            result.update(_flatten(value[key], f"{prefix}.{key}"))
        return result
    if isinstance(value, list):
        result = {}
        for index, item in enumerate(value):
            result.update(_flatten(item, f"{prefix}[{index}]"))
        return result
    return {prefix: value}


def assert_reusable(candidate: dict, active: dict) -> None:
    if candidate.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("requested deployment identity has an unsupported schema")
    if candidate.get("deployment_hash") != content_hash(candidate.get("deployment", {})):
        raise ValueError("requested deployment identity failed its integrity check")
    if active.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"active deployment identity schema is {active.get('schema_version')!r}; "
            f"expected {SCHEMA_VERSION}"
        )
    if active.get("status") != "active":
        raise ValueError(f"deployment identity is not active (status={active.get('status')!r})")
    if active.get("deployment_hash") != content_hash(active.get("deployment", {})):
        raise ValueError("active deployment identity failed its integrity check")
    if candidate.get("deployment_hash") == active.get("deployment_hash"):
        return
    wanted = _flatten(candidate.get("deployment", {}))
    running = _flatten(active.get("deployment", {}))
    differences = []
    for key in sorted(set(wanted) | set(running)):
        if wanted.get(key) != running.get(key):
            differences.append(f"  {key}: requested={wanted.get(key)!r}, active={running.get(key)!r}")
    detail = "\n".join(differences[:20]) or "  deployment hash differs"
    raise ValueError(
        "--workload-only refused: the requested 5G deployment does not match the active identity:\n"
        + detail
    )


def verify_reuse(candidate_path: str | Path, active_path: str | Path) -> None:
    candidate = read_json(candidate_path)
    active = read_json(active_path)
    assert_reusable(candidate, active)


def verify_resume(
    source_path: str | Path,
    candidate_path: str | Path,
    evidence_path: str | Path,
) -> None:
    source = read_json(source_path)
    candidate = read_json(candidate_path)
    evidence = read_json(evidence_path)
    for label, value in (("source", source), ("candidate", candidate)):
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"resume {label} identity has an unsupported schema")
        if value.get("deployment_hash") != content_hash(value.get("deployment", {})):
            raise ValueError(f"resume {label} identity failed its integrity check")
    if not evidence.get("cluster_identity_verified"):
        raise ValueError("--resume refused: the failed run has no successful cluster attestation")
    if evidence.get("deployment_hash") != source.get("deployment_hash"):
        raise ValueError("--resume refused: the failed run's attestation evidence does not match its identity")
    source_deployment = source.get("deployment", {})
    normalized_source = _normalize_legacy_oai_deployment(source_deployment)
    source_bindings = evidence.get("bindings", [])
    if source_bindings:
        evidence_matches = bindings_match_deployment(
            source_deployment, source_bindings
        )
        if not evidence_matches and normalized_source is not None:
            evidence_matches = bindings_match_deployment(
                normalized_source, source_bindings
            )
        if not evidence_matches:
            raise ValueError(
                "--resume refused: the failed run's recorded UE bindings do not "
                "match its deployment contract"
            )
    if candidate.get("scenario_hash") != source.get("scenario_hash"):
        raise ValueError("--resume refused: the resolved scenario has changed")
    if candidate.get("deployment") == source_deployment:
        return

    # Allow the narrowly scoped correction from numbered OAI interfaces to the
    # actual per-pod interface name. No deployed infrastructure field changes.
    if normalized_source is not None and candidate.get("deployment") == normalized_source:
        return
    raise ValueError(
        "--resume refused: current code would change the failed run's deployment "
        "identity beyond the supported OAI per-pod tunnel correction"
    )


def invalidate(active_path: str | Path, run_id: str) -> None:
    value = {
        "schema_version": SCHEMA_VERSION,
        "status": "invalidated",
        "invalidated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "invalidated_by_run": run_id,
    }
    _atomic_text(Path(active_path), json.dumps(value, indent=2, sort_keys=True) + "\n")


def activate(candidate_path: str | Path, active_path: str | Path) -> dict:
    value = read_json(candidate_path)
    if value.get("schema_version") != SCHEMA_VERSION or value.get("deployment_hash") != content_hash(value.get("deployment", {})):
        raise ValueError("candidate deployment identity failed its integrity check")
    value["status"] = "active"
    value["attested_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    _atomic_text(Path(candidate_path), text)
    _atomic_text(Path(active_path), text)
    return value


def record_reuse(candidate_path: str | Path, active_path: str | Path) -> dict:
    candidate = read_json(candidate_path)
    active = read_json(active_path)
    assert_reusable(candidate, active)
    candidate["status"] = "reused"
    candidate["live_identity_hash"] = active["deployment_hash"]
    candidate["attested_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _atomic_text(Path(candidate_path), json.dumps(candidate, indent=2, sort_keys=True) + "\n")
    return candidate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m synthran.deployment_state")
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--source", required=True)
    resolve.add_argument("--output", required=True)
    verify = commands.add_parser("verify-reuse")
    verify.add_argument("--candidate", required=True)
    verify.add_argument("--active", required=True)
    resume = commands.add_parser("verify-resume")
    resume.add_argument("--source", required=True)
    resume.add_argument("--candidate", required=True)
    resume.add_argument("--evidence", required=True)
    invalid = commands.add_parser("invalidate")
    invalid.add_argument("--active", required=True)
    invalid.add_argument("--run-id", required=True)
    active = commands.add_parser("activate")
    active.add_argument("--candidate", required=True)
    active.add_argument("--active", required=True)
    reused = commands.add_parser("record-reuse")
    reused.add_argument("--candidate", required=True)
    reused.add_argument("--active", required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        if args.command == "resolve":
            resolve_scenario(args.source, args.output)
        elif args.command == "verify-reuse":
            verify_reuse(args.candidate, args.active)
        elif args.command == "verify-resume":
            verify_resume(args.source, args.candidate, args.evidence)
        elif args.command == "invalidate":
            invalidate(args.active, args.run_id)
        elif args.command == "activate":
            activate(args.candidate, args.active)
        else:
            record_reuse(args.candidate, args.active)
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
