from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from .deployment_identity import (
    build_implementation_identity,
    controller_source_provenance,
)
from .deployment_state import bindings_match_deployment, content_hash, read_json

ACCEPTANCE_SCHEMA_VERSION = 1
ACCEPTED_ENDPOINT_SCHEMA_VERSION = 2
_ACCEPTED_STATUS = "accepted-testbed"
_PROVISIONED_STATUS = "provisioning-complete"


def _atomic_json(path: str | Path, value: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _configuration_hash(candidate: dict[str, Any]) -> str:
    deployment = candidate.get("deployment")
    if not isinstance(deployment, dict):
        raise ValueError("candidate deployment identity has no deployment mapping")
    expected = content_hash(deployment)
    observed = candidate.get("configuration_hash", candidate.get("deployment_hash"))
    if observed != expected:
        raise ValueError("candidate configuration identity failed its integrity check")
    return expected


def accepted_deployment_hash(identity: dict[str, Any]) -> str:
    deployment = identity.get("deployment")
    implementation = identity.get("implementation")
    if not isinstance(deployment, dict) or not isinstance(implementation, dict):
        raise ValueError("accepted deployment identity is missing implementation identity")
    return content_hash({"deployment": deployment, "implementation": implementation})


def seal_provisioning(
    candidate_path: str | Path,
    evidence_path: str | Path,
    run_dir: str | Path,
) -> dict[str, Any]:
    candidate_path = Path(candidate_path)
    evidence_path = Path(evidence_path)
    run_dir = Path(run_dir).resolve()
    candidate = read_json(candidate_path)
    if candidate.get("status") != "candidate":
        raise ValueError("only a candidate deployment can become provisioning-complete")

    configuration_hash = _configuration_hash(candidate)
    evidence = read_json(evidence_path)
    if evidence.get("deployment_hash") != configuration_hash:
        raise ValueError("live evidence does not match the provisioned configuration identity")

    implementation = build_implementation_identity(candidate, run_dir)
    deployment_hash = content_hash(
        {"deployment": candidate["deployment"], "implementation": implementation}
    )

    candidate["acceptance_schema_version"] = ACCEPTANCE_SCHEMA_VERSION
    candidate["configuration_hash"] = configuration_hash
    candidate["implementation"] = implementation
    candidate["provenance"] = {
        "controller_source": controller_source_provenance(run_dir),
    }
    candidate["deployment_hash"] = deployment_hash
    candidate["status"] = _PROVISIONED_STATUS
    candidate["provisioning_completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()

    evidence["configuration_hash"] = configuration_hash
    evidence["deployment_hash"] = deployment_hash
    evidence["implementation_identity_sha256"] = content_hash(implementation)

    _atomic_json(candidate_path, candidate)
    _atomic_json(evidence_path, evidence)
    return candidate


def _transport_value(binding: dict[str, Any], key: str) -> Any:
    if key in binding:
        return binding.get(key)
    tunnel = binding.get("tunnel", {})
    return tunnel.get(key) if isinstance(tunnel, dict) else None


def _parse_observed_at(value: object) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("live deployment evidence has no observation timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("live deployment evidence has an invalid observation timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("live deployment evidence observation timestamp has no timezone")
    return parsed.astimezone(dt.timezone.utc)


def _expected_upf_target(contract: dict[str, Any]) -> str:
    cidr = str(contract.get("address_cidr", ""))
    address = cidr.split("/", 1)[0]
    octets = address.split(".")
    if len(octets) != 4:
        raise ValueError("deployment UE address contract is malformed")
    return ".".join(octets[:3] + ["1"])


def _validate_user_plane(deployment: dict[str, Any], bindings: list[dict[str, Any]]) -> None:
    by_device = {str(item.get("device")): item for item in bindings}
    for contract in deployment.get("ues", []):
        device = str(contract.get("device"))
        binding = by_device.get(device)
        if binding is None:
            raise ValueError(f"live deployment evidence has no binding for {device}")

        if deployment.get("platform") == "r2lab":
            if binding.get("modem_verified") is not True:
                raise ValueError(f"physical UE {device} has no verified modem identity")
        elif binding.get("software_verified") is not True:
            raise ValueError(f"software UE {device} has no verified live software binding")

        user_plane = binding.get("user_plane")
        if not isinstance(user_plane, dict) or user_plane.get("verified") is not True:
            raise ValueError(f"UE {device} has no verified source-bound user plane")
        if user_plane.get("method") != "icmp_echo":
            raise ValueError(f"UE {device} user-plane evidence uses an unsupported method")
        if user_plane.get("source_interface") != _transport_value(contract, "interface"):
            raise ValueError(f"UE {device} user-plane interface differs from the deployment contract")
        if user_plane.get("source_address") != binding.get("address"):
            raise ValueError(f"UE {device} user-plane source address differs from its live binding")
        if user_plane.get("target_address") != _expected_upf_target(contract):
            raise ValueError(f"UE {device} user-plane target is not the selected UPF address")
        _parse_observed_at(user_plane.get("observed_at"))


def validate_live_evidence(
    identity_path: str | Path,
    evidence_path: str | Path,
    *,
    max_age_seconds: int | None = 300,
) -> dict[str, Any]:
    identity = read_json(identity_path)
    evidence = read_json(evidence_path)
    if identity.get("acceptance_schema_version") != ACCEPTANCE_SCHEMA_VERSION:
        raise ValueError("deployment acceptance schema is unsupported")
    if identity.get("status") not in {_PROVISIONED_STATUS, _ACCEPTED_STATUS}:
        raise ValueError("deployment has not reached provisioning-complete state")

    configuration_hash = _configuration_hash(identity)
    if identity.get("configuration_hash") != configuration_hash:
        raise ValueError("deployment configuration identity failed its integrity check")
    expected_hash = accepted_deployment_hash(identity)
    if identity.get("deployment_hash") != expected_hash:
        raise ValueError("accepted deployment identity failed its integrity check")
    if evidence.get("deployment_hash") != expected_hash:
        raise ValueError("live deployment evidence does not match the executable deployment identity")
    if evidence.get("configuration_hash") != configuration_hash:
        raise ValueError("live deployment evidence does not match the configuration identity")
    if evidence.get("implementation_identity_sha256") != content_hash(identity["implementation"]):
        raise ValueError("live deployment evidence does not match the implementation identity")
    if evidence.get("cluster_identity_verified") is not True:
        raise ValueError("live deployment evidence does not prove the cluster identity")

    deployment = identity.get("deployment", {})
    bindings = evidence.get("bindings")
    if not isinstance(bindings, list) or not bindings_match_deployment(deployment, bindings):
        raise ValueError("live deployment evidence does not contain complete matching UE bindings")
    _validate_user_plane(deployment, bindings)

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


def _endpoint(
    candidate_path: Path,
    active_path: Path,
    evidence_path: Path,
    private_dir: Path,
    identity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": ACCEPTED_ENDPOINT_SCHEMA_VERSION,
        "status": _ACCEPTED_STATUS,
        "configuration_hash": identity["configuration_hash"],
        "deployment_hash": identity["deployment_hash"],
        "run_id": candidate_path.parent.name,
        "identity_file": str(active_path.resolve()),
        "evidence_file": str(evidence_path.resolve()),
        "private_execution_dir": str(private_dir.resolve()),
        "result_dir": str(candidate_path.parent.resolve()),
        "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def accept(
    candidate_path: str | Path,
    active_path: str | Path,
    evidence_path: str | Path,
    endpoint_path: str | Path,
    private_dir: str | Path,
) -> dict[str, Any]:
    candidate_path = Path(candidate_path)
    active_path = Path(active_path)
    evidence_path = Path(evidence_path)
    private_dir = Path(private_dir)
    identity = read_json(candidate_path)
    if identity.get("status") != _PROVISIONED_STATUS:
        raise ValueError("deployment must be provisioning-complete before acceptance")

    evidence = validate_live_evidence(candidate_path, evidence_path, max_age_seconds=300)
    required_private = [private_dir / "inventory.yml", private_dir / "deployment-vars.yml"]
    missing = [str(path) for path in required_private if not path.is_file()]
    if missing:
        raise ValueError(
            "cannot publish accepted deployment endpoint; missing private execution files: "
            + ", ".join(missing)
        )

    identity["status"] = _ACCEPTED_STATUS
    identity["accepted_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    identity["acceptance_evidence"] = {
        "observed_at": evidence.get("observed_at"),
        "implementation_identity_sha256": content_hash(identity["implementation"]),
    }
    _atomic_json(candidate_path, identity)
    _atomic_json(active_path, identity)
    _atomic_json(
        endpoint_path,
        _endpoint(candidate_path, active_path, evidence_path, private_dir, identity),
    )
    return identity


def fail(
    candidate_path: str | Path,
    *,
    phase: str,
    exit_code: int,
    reason: str,
) -> None:
    path = Path(candidate_path)
    if not path.is_file():
        return
    try:
        value = read_json(path)
    except ValueError:
        return
    if value.get("status") == _ACCEPTED_STATUS:
        return
    value["status"] = "failed"
    value["failed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    value["failure"] = {
        "phase": phase,
        "exit_code": int(exit_code),
        "reason": str(reason),
    }
    _atomic_json(path, value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m synthran.acceptance")
    commands = parser.add_subparsers(dest="command", required=True)

    provisioned = commands.add_parser("provisioning-complete")
    provisioned.add_argument("--candidate", required=True)
    provisioned.add_argument("--evidence", required=True)
    provisioned.add_argument("--run-dir", required=True)

    accepted = commands.add_parser("accept")
    accepted.add_argument("--candidate", required=True)
    accepted.add_argument("--active", required=True)
    accepted.add_argument("--evidence", required=True)
    accepted.add_argument("--endpoint", required=True)
    accepted.add_argument("--private-dir", required=True)

    failed = commands.add_parser("fail")
    failed.add_argument("--candidate", required=True)
    failed.add_argument("--phase", required=True)
    failed.add_argument("--exit-code", required=True, type=int)
    failed.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        if args.command == "provisioning-complete":
            seal_provisioning(args.candidate, args.evidence, args.run_dir)
        elif args.command == "accept":
            accept(
                args.candidate,
                args.active,
                args.evidence,
                args.endpoint,
                args.private_dir,
            )
        else:
            fail(
                args.candidate,
                phase=args.phase,
                exit_code=args.exit_code,
                reason=args.reason,
            )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
