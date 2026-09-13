"""Shared internal helpers for Experiment 2."""
from __future__ import annotations
import hashlib, json, shlex, subprocess
from pathlib import Path
from typing import Any
from . import source as source_cohort
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNTIME = ROOT / "synthran/experiment_runtime/runner.py"

def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _run(command: list[str | Path], *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    rendered = [str(value) for value in command]
    print("$ " + " ".join(shlex.quote(value) for value in rendered), flush=True)
    process = subprocess.run(
        rendered,
        cwd=ROOT,
        text=True,
        capture_output=capture,
        check=False,
    )
    if capture and process.stdout:
        print(process.stdout, end="" if process.stdout.endswith("\n") else "\n")
    if process.returncode and check:
        detail = (process.stderr or process.stdout or "").strip()
        raise RuntimeError(
            f"command failed with exit {process.returncode}: {rendered[0]}"
            + (f"\n{detail}" if detail else "")
        )
    return process


def _prepared() -> tuple[Path, dict[str, Any]]:
    return source_cohort.discover_prepared()


def _deployment_roles(environment: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    bindings = environment.get("bindings", [])
    if len(bindings) < 2:
        raise RuntimeError("Experiment 2 needs two verified UE bindings: one workload gateway and one competitor")
    return bindings[0], bindings[1]
