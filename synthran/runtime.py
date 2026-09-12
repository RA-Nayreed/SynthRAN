"""Install an optional runtime once per interpreter and dependency declaration."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def ensure(extra: str, log: Path) -> None:
    declaration = (ROOT / "pyproject.toml").read_bytes()
    venv_config = Path(sys.prefix) / "pyvenv.cfg"
    generation = venv_config.stat().st_mtime_ns if venv_config.exists() else 0
    identity = f"{sys.executable}:{sys.version}:{generation}:{extra}".encode()
    stamp = (
        ROOT / ".synthran/runtime" / hashlib.sha256(identity + declaration).hexdigest()
    )
    if stamp.exists():
        return
    stamp.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as stream:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                "-e",
                f"{ROOT}[{extra}]",
            ],
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
    if result.returncode:
        raise SystemExit(f"Runtime installation failed; see {log}")
    stamp.touch()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("extra")
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    ensure(args.extra, args.log)
