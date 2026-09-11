"""Record sanitized local runtime provenance for a SynthRAN run."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _command(argv: list[str]) -> dict:
    result = subprocess.run(
        argv,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def collect(run_dir: Path) -> Path:
    git_head = _command(["git", "rev-parse", "HEAD"])
    git_status = _command(["git", "status", "--porcelain=v1", "--untracked-files=no"])
    pip_freeze = _command([sys.executable, "-m", "pip", "freeze", "--all"])
    ansible = _command([str(Path(sys.executable).with_name("ansible")), "--version"])
    galaxy = _command(
        [str(Path(sys.executable).with_name("ansible-galaxy")), "collection", "list", "--format", "json"]
    )
    try:
        collections = json.loads(galaxy["stdout"]) if galaxy["returncode"] == 0 else None
    except json.JSONDecodeError:
        collections = None

    status_bytes = git_status["stdout"].encode()
    value = {
        "schema_version": 1,
        "source": {
            "revision": git_head["stdout"] if git_head["returncode"] == 0 else "unknown",
            "dirty_worktree": bool(git_status["stdout"]),
            "worktree_status_sha256": hashlib.sha256(status_bytes).hexdigest(),
        },
        "controller": {
            "python": sys.version,
            "executable": str(Path(sys.executable).name),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "pip_freeze": sorted(line for line in pip_freeze["stdout"].splitlines() if line),
            "ansible_version": ansible["stdout"],
            "galaxy_collections": collections,
        },
        "declarations": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in (
                ROOT / "pyproject.toml",
                ROOT / "deployment/collections/requirements.yml",
                ROOT / "deployment/group_vars/all/all.yml",
            )
        },
    }
    output = run_dir / "provenance" / "controller.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    print(collect(args.run_dir.resolve()))


if __name__ == "__main__":
    main()
