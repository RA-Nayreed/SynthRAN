"""Experiment-2 control adapter used only by ``experiment.sh``."""
from __future__ import annotations

import argparse
import importlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from synthran.experiment_environment import inspect_active_deployment

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "Experiments/Ex2_Flagship_Causal_5G_Transport/experiment.yml"
RESULTS = ROOT / "results/experiments/ex2"
ACTIVE = ROOT / ".synthran/active-ex2.json"
PHASES = {
    "prepare": ("Experiments.Ex2_Flagship_Causal_5G_Transport.campaign", "prepare"),
    "qualification": ("Experiments.Ex2_Flagship_Causal_5G_Transport.campaign", "qualification"),
    "calibration": ("Experiments.Ex2_Flagship_Causal_5G_Transport.campaign", "calibration"),
    "freeze": ("Experiments.Ex2_Flagship_Causal_5G_Transport.campaign", "freeze"),
    "confirmation": ("Experiments.Ex2_Flagship_Causal_5G_Transport.campaign", "confirmation"),
    "analysis": ("Experiments.Ex2_Flagship_Causal_5G_Transport.analysis", "analysis"),
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _manifest() -> dict[str, Any]:
    value = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("id") != "ex2":
        raise ValueError("Experiment-2 manifest is invalid")
    return value


def _selected(manifest: dict[str, Any], phase: str) -> list[dict[str, Any]]:
    phases = manifest["phases"]
    if phase == "all":
        return phases
    for item in phases:
        if item["id"] == phase:
            return [item]
    valid = ", ".join(item["id"] for item in phases) + ", all"
    raise ValueError(f"unknown Experiment-2 phase {phase!r}; expected one of: {valid}")


def _handler(phase: str):
    module, name = PHASES[phase]
    function = getattr(importlib.import_module(module), name, None)
    if not callable(function):
        raise ValueError(f"Experiment-2 phase {phase!r} is not implemented")
    return function


def _section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def _display(env: dict[str, Any]) -> None:
    deployment, reservation = env["deployment"], env["reservation"]
    _section("Active testbed")
    print(f"Deployment hash   {env['deployment_hash']}")
    print(f"Platform          {deployment.get('platform')}")
    print(f"Core              {deployment.get('core')}")
    print(f"RAN               {deployment.get('ran')}")
    print(f"Radio             {deployment.get('radio_unit')}")
    print("Nodes             " + ", ".join(f"{key}={value}" for key, value in deployment.get("nodes", {}).items()))
    for index, binding in enumerate(env.get("bindings", []), 1):
        print(
            f"UE {index:<2}             {binding.get('device')} · "
            f"slice={binding.get('slice')} · dnn={binding.get('dnn')} · "
            f"address={binding.get('address', 'unreported')}"
        )
    print(f"SOP reservation   {reservation['sop'].get('status')}")
    if deployment.get("platform") == "r2lab":
        print(f"R2Lab reservation {reservation['r2lab'].get('status')}")
    if reservation.get("coverage_end"):
        remaining = reservation.get("remaining_seconds")
        suffix = f" · {float(remaining) / 60:.1f} min remaining" if remaining is not None else ""
        print(f"Coverage until    {reservation['coverage_end']}{suffix}")
    for warning in env.get("warnings", []):
        print(f"Warning           {warning}")


def _approve(env: dict[str, Any], no_input: bool) -> None:
    if len(env.get("bindings", [])) < 2:
        raise ValueError("Experiment 2 needs at least two verified UE bindings")
    reservation = env.get("reservation", {})
    if reservation.get("sop", {}).get("status") != "active":
        raise ValueError(
            "the accepted testbed has no active SOP reservation coverage; extend or reacquire it with deploy.sh"
        )
    if (
        env["deployment"].get("platform") == "r2lab"
        and reservation.get("r2lab", {}).get("status") != "active"
    ):
        raise ValueError(
            "the accepted physical testbed has no active R2Lab reservation coverage; extend or reacquire it with deploy.sh"
        )
    if no_input:
        return
    if input("\nRun Experiment 2 on this active testbed? [y/N]: ").strip().lower() not in {"y", "yes"}:
        raise ValueError("Experiment 2 cancelled")


def _new_campaign(manifest: dict[str, Any], env: dict[str, Any]) -> Path:
    campaign_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = RESULTS / campaign_id
    root.mkdir(parents=True, exist_ok=False)
    git = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip() or "unknown"
    campaign = {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "experiment": "ex2",
        "design_version": manifest["design_version"],
        "status": "active",
        "source_revision": git,
        "deployment_hash": env["deployment_hash"],
        "deployment_run_id": env["attachment"].get("deployment_run_id"),
        "completed_phases": [],
    }
    _write(root / "campaign.json", campaign)
    _write(
        ACTIVE,
        {
            "schema_version": 1,
            "status": "active",
            "experiment": "ex2",
            "campaign_id": campaign_id,
            "campaign_root": str(root),
            "campaign_file": str(root / "campaign.json"),
        },
    )
    return root


def _active_campaign() -> Path:
    if not ACTIVE.is_file():
        raise ValueError("no active Experiment-2 campaign; run qualification or the full experiment first")
    endpoint = _read(ACTIVE)
    if endpoint.get("status") != "active" or endpoint.get("experiment") != "ex2":
        raise ValueError("no active Experiment-2 campaign; run qualification or the full experiment first")
    root = Path(str(endpoint.get("campaign_root", ""))).resolve()
    campaign = _read(root / "campaign.json")
    if campaign.get("status") != "active" or campaign.get("campaign_id") != endpoint.get("campaign_id"):
        raise ValueError("active Experiment-2 campaign state is inconsistent")
    return root


def _mark(root: Path, phase: str, complete: bool = False) -> None:
    path = root / "campaign.json"
    campaign = _read(path)
    done = list(campaign.get("completed_phases", []))
    if phase not in done:
        done.append(phase)
    campaign["completed_phases"] = done
    if complete:
        campaign["status"] = "complete"
        campaign["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write(path, campaign)
    if complete and ACTIVE.is_file():
        endpoint = _read(ACTIVE)
        if endpoint.get("campaign_id") == campaign["campaign_id"]:
            endpoint["status"] = "complete"
            _write(ACTIVE, endpoint)


def _dependencies(root: Path, item: dict[str, Any]) -> None:
    done = set(_read(root / "campaign.json").get("completed_phases", []))
    missing = [name for name in item.get("requires", []) if name not in done]
    if missing:
        raise ValueError(f"phase {item['id']} requires completed phase(s): {', '.join(missing)}")


def plan(phase: str, verbose: bool) -> None:
    manifest = _manifest()
    chosen = _selected(manifest, phase)
    _section(f"Planning {manifest['display_name']}")
    print(f"Requested phase   {phase}")
    _section("Execution order")
    for index, item in enumerate(chosen, 1):
        print(f"  {index}. {item['id']:<16} {item['name']}")
    if any(item.get("resource") == "active_testbed" for item in chosen):
        try:
            _display(inspect_active_deployment())
        except Exception as exc:
            _section("Active testbed")
            print(f"Not available     {exc}")
    if verbose:
        _section("Manifest")
        print(yaml.safe_dump(manifest, sort_keys=False).rstrip())


def run(phase: str, verbose: bool, no_input: bool) -> None:
    manifest = _manifest()
    chosen = _selected(manifest, phase)
    campaign_items: list[dict[str, Any]] = []
    for item in chosen:
        if item.get("campaign", True) is False:
            _section(item["name"])
            result = _handler(item["id"])(None, manifest=manifest, environment=None)
            print(f"Phase status      {str((result or {}).get('status', 'complete')).upper()}")
        else:
            campaign_items.append(item)
    if not campaign_items:
        return

    env = None
    if any(item.get("resource") == "active_testbed" for item in campaign_items):
        env = inspect_active_deployment()
        _display(env)
        _approve(env, no_input)

    first = campaign_items[0]["id"]
    if first == "qualification":
        root = None
        try:
            candidate = _active_campaign()
            if env is not None and _read(candidate / "campaign.json").get("deployment_hash") == env["deployment_hash"]:
                root = candidate
        except (OSError, ValueError):
            pass
        if root is None:
            if env is None:
                raise ValueError("qualification requires an active testbed")
            root = _new_campaign(manifest, env)
    else:
        root = _active_campaign()
        if env is not None and _read(root / "campaign.json").get("deployment_hash") != env["deployment_hash"]:
            raise ValueError(
                "the active Experiment-2 campaign belongs to a different testbed; "
                "run qualification or the full experiment to start a new campaign"
            )

    _section("Campaign")
    print(f"ID                {root.name}")
    print(f"Results           {root.relative_to(ROOT)}")
    for item in campaign_items:
        _dependencies(root, item)
        _section(item["name"])
        result = _handler(item["id"])(root, manifest=manifest, environment=env)
        status = str((result or {}).get("status", "complete")).lower()
        if status in {"paused", "partial"}:
            print(f"Phase status      {status.upper()}")
            if (result or {}).get("runs_complete") is not None:
                print(f"Progress          {result['runs_complete']}/{result.get('runs_expected', '?')} replays")
            print("Resume            rerun experiment.sh after extending the same deployment reservation")
            break
        _mark(root, item["id"], complete=item["id"] == "analysis")
        print(f"Phase status      {status.upper()}")
    if verbose:
        _section("Campaign state")
        print(json.dumps(_read(root / "campaign.json"), indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "run"))
    parser.add_argument("--phase", required=True)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-input", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            plan(args.phase, args.verbose)
        else:
            run(args.phase, args.verbose, args.no_input)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, yaml.YAMLError) as exc:
        print(f"Experiment error: {exc}", file=__import__("sys").stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
