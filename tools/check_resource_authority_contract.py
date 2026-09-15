#!/usr/bin/env python3
"""Prove the pinned 5g-Ansible plan cannot reacquire or reprepare SynthRAN resources."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json"
EXPECTED_OVERLAY = {
    "provider.manage": False,
    "reservation.enabled": False,
    "reservation.r2lab_mode": "none",
    "deployment.pos_manage_allocation": False,
    "deployment.extra_vars.no_boot": True,
}


class ContractError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _import_machine(reference: Path):
    path = reference / "tools/fiveg_machine.py"
    spec = importlib.util.spec_from_file_location("synthran_resource_authority_reference", path)
    if spec is None or spec.loader is None:
        raise ContractError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_json(command: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise ContractError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}{result.stderr}"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("reference plan did not return JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("reference plan returned a non-object JSON value")
    return value


def _spec() -> dict[str, Any]:
    return {
        "schema": "fiveg/deployment/v1",
        "id": "synthran-resource-authority-probe",
        "provider": {"manage": False},
        "core": {"type": "open5gs", "node": "sopnode-f2"},
        "ran": {"type": "srsRAN", "node": "sopnode-f3"},
        "platform": {"type": "r2lab", "ru": "n320"},
        "ues": {"qhats": ["qhat01"], "qfits": [], "phones": []},
        "monitoring": {"enabled": False},
        "profile": "default",
        "reservation": {
            "enabled": False,
            "duration_minutes": 120,
            "r2lab_mode": "none",
        },
        "deployment": {
            "prepare_only": False,
            "allow_live_installs": True,
            "manage_os_dependencies": True,
            "manage_python_dependencies": True,
            "disruptive_cluster_ops_enabled": True,
            "k8s_env_enabled": True,
            "python_interpreter": "",
            "selected_slices": [],
            "selected_ues": ["qhat01"],
            "open5gs_webui_enabled": False,
            "open5gs_admin_account_enabled": False,
            "pos_manage_allocation": False,
            "cleanup_namespaces": [],
            "extra_vars": {"no_boot": True},
        },
        "scenario": {"type": "none"},
        "r2lab": {
            "username": "contract-check",
            "known_hosts_file": "",
            "strict_host_key_checking": True,
        },
    }


def _assert_overlay(spec: dict[str, Any]) -> None:
    actual = {
        "provider.manage": spec["provider"]["manage"],
        "reservation.enabled": spec["reservation"]["enabled"],
        "reservation.r2lab_mode": spec["reservation"]["r2lab_mode"],
        "deployment.pos_manage_allocation": spec["deployment"]["pos_manage_allocation"],
        "deployment.extra_vars.no_boot": spec["deployment"]["extra_vars"].get("no_boot"),
    }
    if actual != EXPECTED_OVERLAY:
        raise ContractError(f"resource-authority overlay changed: {actual!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True, type=Path)
    args = parser.parse_args()
    reference = args.reference.expanduser().resolve()
    contract = _json(CONTRACT)

    configured = contract.get("external_resource_authority", {})
    if configured.get("owner") != "synthran":
        raise ContractError("execution contract no longer names SynthRAN as resource authority")
    if configured.get("reference_spec_overlay") != EXPECTED_OVERLAY:
        raise ContractError("machine-readable external resource overlay changed")

    expected_commit = str(contract["commit"])
    actual_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=reference, text=True, capture_output=True, check=True
    ).stdout.strip()
    if actual_commit != expected_commit:
        raise ContractError(
            f"reference commit mismatch: expected {expected_commit}, got {actual_commit}"
        )

    machine = _import_machine(reference)
    raw = _spec()
    normalized = machine.normalize(raw)
    _assert_overlay(normalized)
    extra = machine.extra_vars(normalized)
    if extra.get("pos_manage_allocation") is not False:
        raise ContractError("reference extra vars re-enabled POS allocation ownership")
    if extra.get("no_boot") is not True:
        raise ContractError("reference extra vars did not preserve no_boot=true")

    role = (reference / "roles/pos/tasks/main.yml").read_text(encoding="utf-8")
    required_role_contract = (
        'should_boot: "{{ not (no_boot | default(false) | bool) }}"',
        "when: pos_manage_allocation | default(true) | bool",
        "when: should_boot",
    )
    for needle in required_role_contract:
        if needle not in role:
            raise ContractError(
                f"pinned POS role no longer honors the expected suppression surface: {needle}"
            )

    with tempfile.TemporaryDirectory(prefix="synthran-resource-authority-") as tmp:
        temporary = Path(tmp)
        spec_path = temporary / "spec.json"
        spec_path.write_text(json.dumps(raw), encoding="utf-8")
        entrypoint = reference / str(contract["entrypoint"])
        plan = _run_json(
            [
                str(entrypoint),
                "plan",
                "--spec",
                str(spec_path),
                "--state-root",
                str(temporary / "state"),
                "--json",
            ],
            reference,
        )
        planned = plan.get("spec")
        if not isinstance(planned, dict):
            raise ContractError("reference plan omitted normalized spec")
        _assert_overlay(planned)
        if planned != normalized:
            raise ContractError("reference plan changed the normalized authority overlay")

    print(
        json.dumps(
            {
                "schema": "synthran/resource-authority-contract-check/v1",
                "reference_commit": actual_commit,
                "owner": "synthran",
                "overlay": EXPECTED_OVERLAY,
                "reference_pos_role_suppression": "verified",
                "plan": "verified",
                "result": "pass",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, OSError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"resource-authority-contract: {exc}") from exc
