#!/usr/bin/env python3
"""Verify the pinned 5g-Ansible machine-interface assumptions used by SynthRAN."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json"


class ContractError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise ContractError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stdout}{result.stderr}"
        )
    return result


def _run_json(command: list[str], *, cwd: Path) -> dict[str, Any]:
    result = _run(command, cwd=cwd)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError(f"command did not return JSON: {' '.join(command)}") from exc
    if not isinstance(value, dict):
        raise ContractError("machine interface returned a non-object JSON value")
    return value


def _import_machine(reference: Path):
    path = reference / "tools/fiveg_machine.py"
    spec = importlib.util.spec_from_file_location("synthran_pinned_fiveg_machine", path)
    if spec is None or spec.loader is None:
        raise ContractError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_spec(*, physical: bool) -> dict[str, Any]:
    return {
        "schema": "fiveg/deployment/v1",
        "id": "synthran-contract-probe",
        "provider": {"manage": False},
        "core": {"type": "open5gs", "node": "sopnode-f2"},
        "ran": {"type": "srsRAN", "node": "sopnode-f3"},
        "platform": {
            "type": "r2lab" if physical else "rfsim",
            "ru": "n320" if physical else "rfsim",
        },
        "ues": {
            "qhats": ["qhat01"] if physical else [],
            "qfits": ["qfit07"] if physical else [],
            "phones": [],
        },
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
            "selected_ues": [],
            "open5gs_webui_enabled": False,
            "open5gs_admin_account_enabled": False,
            "pos_manage_allocation": False,
            "cleanup_namespaces": [],
            "extra_vars": {},
        },
        "scenario": {"type": "none"},
        "r2lab": {
            "username": "contract-check" if physical else "",
            "known_hosts_file": "",
            "strict_host_key_checking": True,
        },
    }


def _expect_error(module, raw: dict[str, Any], needle: str) -> None:
    try:
        module.normalize(raw)
    except module.FiveGError as exc:
        if needle not in str(exc):
            raise ContractError(f"unexpected normalize error: {exc}") from exc
    else:
        raise ContractError(f"expected normalize failure containing {needle!r}")


def _verify_behavior(reference: Path, contract: dict[str, Any]) -> dict[str, Any]:
    machine = _import_machine(reference)
    physical = _base_spec(physical=True)
    normalized = machine.normalize(physical)
    inventory = machine.inventory(normalized)
    if "qhat01" not in inventory or "qfit07" not in inventory:
        raise ContractError("physical probe UEs are missing from generated inventory")
    if "sopnode-f2 ansible_user=root" not in inventory or "ip=172.28.2.77" not in inventory:
        raise ContractError("pinned sopnode-f2 NODE_FACTS behavior changed")
    if "sopnode-f3 ansible_user=root" not in inventory or "ip=172.28.2.95" not in inventory:
        raise ContractError("pinned sopnode-f3 NODE_FACTS behavior changed")

    with_host_vars = copy.deepcopy(physical)
    with_host_vars["host_vars"] = {"sopnode-f2": {"ip": "127.0.0.2"}}
    if machine.normalize(with_host_vars) != normalized:
        raise ContractError("host_vars behavior changed; re-audit mapping before migration")

    missing_profile = copy.deepcopy(physical)
    missing_profile["profile"] = "synthran_contract_missing"
    _expect_error(machine, missing_profile, "unknown 5G profile")

    qhat23 = copy.deepcopy(physical)
    qhat23["ues"]["qhats"] = ["qhat23"]
    _expect_error(machine, qhat23, "unsupported values: qhat23")

    entrypoint = reference / str(contract["entrypoint"])
    with tempfile.TemporaryDirectory(prefix="synthran-fiveg-contract-") as tmp:
        temporary = Path(tmp)
        spec_path = temporary / "physical.json"
        spec_path.write_text(json.dumps(physical), encoding="utf-8")
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
            cwd=reference,
        )
        commands = [" ".join(map(str, item)) for item in plan.get("commands", [])]
        joined = "\n".join(commands)
        if "playbooks/deploy_r2lab.yml" not in joined or "playbooks/deploy.yml" not in joined:
            raise ContractError("reference plan no longer contains the expected deployment playbooks")
        if "test-ue-connect.yml" in joined:
            raise ContractError("UE attachment moved into reference plan; re-audit acceptance semantics")

        runtime = temporary / "resume"
        initial = _base_spec(physical=False)
        initial_path = temporary / "initial.json"
        initial_path.write_text(json.dumps(initial), encoding="utf-8")
        machine.run = lambda command, log=None, check=True: subprocess.CompletedProcess(
            command, 0, "", ""
        )
        machine.emit = lambda value, as_json: None
        args = SimpleNamespace(
            spec=str(initial_path), state_root=str(runtime), resume=False, json=True
        )
        machine.up(args)

        changed = copy.deepcopy(initial)
        changed["ran"]["type"] = "oai"
        changed_path = temporary / "changed.json"
        changed_path.write_text(json.dumps(changed), encoding="utf-8")
        args.spec = str(changed_path)
        args.resume = True
        machine.up(args)

        directory = runtime / initial["id"]
        state = _load_json(directory / "state.json")
        saved_spec = _load_json(directory / "spec.json")
        if state.get("spec_sha256") == machine.digest(saved_spec):
            raise ContractError("resume spec-integrity behavior changed; re-audit caller guard")

    return {
        "inventory_probe": "passed",
        "host_vars_unmapped": True,
        "unknown_profile_rejected": True,
        "qhat23_rejected": True,
        "ue_attachment_outside_up": True,
        "resume_spec_drift_not_rejected": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference",
        required=True,
        type=Path,
        help="checkout of the pinned RA-Nayreed/5g-Ansible repository",
    )
    args = parser.parse_args()
    reference = args.reference.expanduser().resolve()
    contract = _load_json(CONTRACT)

    expected = str(contract["commit"])
    actual = _run(["git", "rev-parse", "HEAD"], cwd=reference).stdout.strip()
    if actual != expected:
        raise ContractError(f"reference commit mismatch: expected {expected}, got {actual}")

    entrypoint = reference / str(contract["entrypoint"])
    if not entrypoint.is_file():
        raise ContractError(f"missing machine entrypoint: {entrypoint}")

    capabilities = _run_json([str(entrypoint), "capabilities", "--json"], cwd=reference)
    required = contract["required_capabilities"]
    for key in ("cores", "rans", "platforms"):
        missing = sorted(set(required[key]).difference(capabilities.get(key, [])))
        if missing:
            raise ContractError(f"reference capabilities missing {key}: {', '.join(missing)}")
    missing_profiles = sorted(set(required["profiles"]).difference(capabilities.get("profiles", [])))
    if missing_profiles:
        raise ContractError(f"reference capabilities missing profiles: {', '.join(missing_profiles)}")

    behavior = _verify_behavior(reference, contract)
    print(
        json.dumps(
            {
                "schema": "synthran/5g-ansible-contract-check/v1",
                "reference_commit": actual,
                "capabilities_schema": capabilities.get("schema"),
                "behavior": behavior,
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
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"reference-contract: {exc}") from exc
