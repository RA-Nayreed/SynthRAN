from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from .deployment_state import bindings_match_deployment, content_hash, read_json

ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_SCHEMA_VERSION = 1
ACCEPTED_ENDPOINT_SCHEMA_VERSION = 2
_ACCEPTED_STATUS = "accepted-testbed"
_PROVISIONED_STATUS = "provisioning-complete"
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _atomic_json(path: str | Path, value: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _json_object(path: str | Path, label: str) -> dict[str, Any]:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"{label} is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _yaml_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"{label} is unreadable: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a YAML mapping: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iter_files(entries: Iterable[Path]) -> list[Path]:
    files: set[Path] = set()
    for entry in entries:
        if entry.is_file():
            files.add(entry.resolve())
        elif entry.is_dir():
            for path in entry.rglob("*"):
                if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
                    files.add(path.resolve())
    return sorted(files, key=lambda path: str(path.relative_to(ROOT)))


def _selected_adapter_identity(deployment: dict[str, Any]) -> dict[str, Any]:
    core = str(deployment.get("core", "")).lower()
    ran = str(deployment.get("ran", "")).lower()
    platform = str(deployment.get("platform", "")).lower()
    ran_path = "srsRAN" if ran == "srsran" else ran
    entries = [
        ROOT / "deploy.sh",
        ROOT / "deployment/scripts",
        ROOT / "deployment/playbooks/site.yml",
        ROOT / "deployment/playbooks/network.yml",
        ROOT / "deployment/playbooks/attest_transport.yml",
        ROOT / "deployment/playbooks/attest_deployment.yml",
        ROOT / "deployment/playbooks/connect_ues.yml",
        ROOT / "deployment/playbooks/provenance.yml",
        ROOT / "deployment/topology.yml",
        ROOT / "deployment/group_vars/all/all.yml",
        ROOT / "deployment/roles/setup",
        ROOT / "deployment/roles/5g" / core,
        ROOT / "deployment/roles/5g" / ran_path,
    ]
    if platform == "r2lab":
        entries.extend(
            [
                ROOT / "deployment/roles/r2lab",
                ROOT / "deployment/roles/synthran/r2lab_ue_verify",
            ]
        )
    files = _iter_files(entries)
    if not files:
        raise ValueError("selected deployment adapter identity contains no files")
    records = [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256_file(path),
        }
        for path in files
    ]
    return {
        "sha256": content_hash(records),
        "file_count": len(records),
    }


def _execution_reference() -> dict[str, str]:
    path = ROOT / "third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json"
    value = _json_object(path, "reviewed execution reference")
    repository = str(value.get("repository", ""))
    commit = str(value.get("commit", "")).lower()
    if repository != "https://github.com/sopnode/5g_ansible" or not _GIT_SHA_RE.fullmatch(commit):
        raise ValueError("reviewed 5g-Ansible execution reference is not immutable")
    return {"repository": repository, "commit": commit}


def _source_pin(repository: Any, revision: Any, label: str) -> dict[str, str]:
    repository = str(repository or "")
    revision = str(revision or "").lower()
    if not repository or not _GIT_SHA_RE.fullmatch(revision):
        raise ValueError(f"{label} source identity is not an immutable Git revision")
    return {"repository": repository, "revision": revision}


def _declared_source_pins(deployment: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    core = str(deployment.get("core", "")).lower()
    ran = str(deployment.get("ran", "")).lower()
    pins: dict[str, Any] = {"lifecycle": _execution_reference()}

    if core == "open5gs":
        defaults = _yaml_object(
            ROOT / "deployment/roles/5g/open5gs/config/defaults/main.yml",
            "Open5GS source defaults",
        )
        pins["open5gs"] = _source_pin(
            defaults.get("repo_url"), defaults.get("repo_branch"), "Open5GS"
        )

    if core == "free5gc" or (ran == "ueransim" and core != "open5gs"):
        defaults = _yaml_object(
            ROOT / "deployment/roles/5g/free5gc/config/defaults/main.yml",
            "Free5GC source defaults",
        )
        pins["free5gc"] = _source_pin(
            defaults.get("free5gc_repo_url"),
            defaults.get("free5gc_repo_branch"),
            "Free5GC",
        )

    if ran == "srsran":
        defaults = _yaml_object(
            ROOT / "deployment/roles/5g/srsRAN/common/defaults/main.yml",
            "srsRAN source defaults",
        )
        pins["srsran_chart"] = _source_pin(
            defaults.get("repo_url"), defaults.get("version"), "srsRAN chart"
        )

    if core == "oai" or ran == "oai":
        observed = _json_object(run_dir / "provenance/oai-sources.json", "OAI source provenance")
        pins["oai_helper"] = _source_pin(
            "https://github.com/sopnode/oai5g-rru.git",
            observed.get("oai5g_rru_revision"),
            "OAI helper",
        )
        pins["oai_charts"] = _source_pin(
            "https://gitlab.eurecom.fr/turletti/charts.git",
            observed.get("oai_charts_revision"),
            "OAI charts",
        )

    return pins


def _controller_identity(run_dir: Path) -> dict[str, Any]:
    value = _json_object(run_dir / "provenance/controller.json", "controller provenance")
    source = value.get("source")
    if not isinstance(source, dict):
        raise ValueError("controller provenance has no source identity")
    revision = str(source.get("revision", ""))
    return {
        "revision": revision,
        "dirty_worktree": bool(source.get("dirty_worktree")),
        "worktree_status_sha256": source.get("worktree_status_sha256"),
    }


def _cluster_runtime_identity(deployment: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    value = _json_object(run_dir / "provenance/cluster.json", "cluster runtime provenance")
    topology = deployment.get("topology", {})
    namespace = str(topology.get("namespace", "")) if isinstance(topology, dict) else ""
    if not namespace:
        raise ValueError("deployment identity has no selected Kubernetes namespace")

    images = value.get("images", [])
    if not isinstance(images, list):
        raise ValueError("cluster runtime provenance images must be a list")
    selected_images: set[tuple[str, str]] = set()
    incomplete = 0
    for item in images:
        if not isinstance(item, dict) or str(item.get("namespace", "")) != namespace:
            continue
        configured = str(item.get("image", ""))
        image_id = str(item.get("imageID", ""))
        if not configured or _DIGEST_RE.search(image_id) is None:
            incomplete += 1
            continue
        selected_images.add((configured, image_id))
    if not selected_images:
        raise ValueError(
            f"cluster runtime provenance has no digest-qualified image identity in namespace {namespace}"
        )

    releases = value.get("helm_releases", [])
    selected_releases = []
    if isinstance(releases, list):
        for item in releases:
            if isinstance(item, dict) and str(item.get("namespace", "")) == namespace:
                selected_releases.append(
                    {
                        key: item.get(key)
                        for key in ("name", "chart", "app_version", "values_sha256")
                    }
                )
    selected_releases.sort(key=lambda item: str(item.get("name", "")))

    return {
        "namespace": namespace,
        "configured_and_runtime_images": [
            {"configured_image": configured, "runtime_image_id": image_id}
            for configured, image_id in sorted(selected_images)
        ],
        "incomplete_image_status_count": incomplete,
        "helm_releases": selected_releases,
    }


def _selected_runtime_refs(deployment: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    ran = str(deployment.get("ran", "")).lower()
    platform = str(deployment.get("platform", "")).lower()
    result: dict[str, Any] = {}
    if ran == "srsran":
        value = _json_object(run_dir / "provenance/srsran-runtime.json", "srsRAN runtime provenance")
        resolved_image = str(value.get("resolved_image", ""))
        sidecar_image = str(value.get("log_sidecar_image", ""))
        chart_revision = str(value.get("chart_revision", "")).lower()
        lifecycle_commit = str(value.get("lifecycle_reference_commit", "")).lower()
        if "@sha256:" not in resolved_image or "@sha256:" not in sidecar_image:
            raise ValueError("srsRAN configured runtime images are not immutable digest references")
        if not _GIT_SHA_RE.fullmatch(chart_revision) or not _GIT_SHA_RE.fullmatch(lifecycle_commit):
            raise ValueError("srsRAN runtime provenance does not contain immutable source revisions")
        result["srsran"] = {
            "chart_repository": value.get("chart_repository"),
            "chart_revision": chart_revision,
            "configured_image": resolved_image,
            "log_sidecar_image": sidecar_image,
            "lifecycle_reference_repository": value.get("lifecycle_reference_repository"),
            "lifecycle_reference_commit": lifecycle_commit,
        }
        if platform == "rfsim":
            ue_value = _json_object(
                run_dir / "provenance/srsran-rfsim-ue-runtime.json",
                "srsRAN RFSIM UE runtime provenance",
            )
            configured = str(ue_value.get("configured_image", ""))
            live_image_id = str(ue_value.get("live_image_id", ""))
            if "@sha256:" not in configured or _DIGEST_RE.search(live_image_id) is None:
                raise ValueError("srsRAN RFSIM UE image identity is incomplete")
            result["srsran_rfsim_ue"] = {
                "configured_image": configured,
                "runtime_image_id": live_image_id,
                "pod_spec_image": ue_value.get("pod_spec_image"),
            }
    return result


def build_implementation_identity(candidate: dict[str, Any], run_dir: str | Path) -> dict[str, Any]:
    deployment = candidate.get("deployment")
    if not isinstance(deployment, dict):
        raise ValueError("candidate deployment identity has no deployment mapping")
    run_dir = Path(run_dir).resolve()
    return {
        "schema_version": 1,
        "reviewed_sources": _declared_source_pins(deployment, run_dir),
        "selected_adapter": _selected_adapter_identity(deployment),
        "controller_source": _controller_identity(run_dir),
        "selected_runtime": _selected_runtime_refs(deployment, run_dir),
        "cluster_runtime": _cluster_runtime_identity(deployment, run_dir),
    }


def _initial_configuration_hash(candidate: dict[str, Any]) -> str:
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
    candidate = read_json(candidate_path)
    if candidate.get("status") != "candidate":
        raise ValueError("only a candidate deployment can become provisioning-complete")
    configuration_hash = _initial_configuration_hash(candidate)
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
        else:
            if binding.get("software_verified") is not True:
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
    expected_hash = accepted_deployment_hash(identity)
    if identity.get("deployment_hash") != expected_hash:
        raise ValueError("accepted deployment identity failed its integrity check")
    if evidence.get("deployment_hash") != expected_hash:
        raise ValueError("live deployment evidence does not match the executable deployment identity")
    if evidence.get("configuration_hash") != identity.get("configuration_hash"):
        raise ValueError("live deployment evidence does not match the configuration identity")
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
        "implementation_identity_sha256": evidence.get("implementation_identity_sha256"),
    }
    text = json.dumps(identity, indent=2, sort_keys=True) + "\n"
    candidate_path.write_text(text, encoding="utf-8")
    active_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = active_path.with_name(active_path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, active_path)
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
