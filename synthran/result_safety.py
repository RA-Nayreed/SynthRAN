"""Sanitize shareable run artifacts without mutating private execution inputs."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

import yaml

SENSITIVE_KEY = re.compile(
    r"password|secret|token|credential|private_key|full_key|(?:^|_)opc(?:$|_)",
    re.I,
)
PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?"
    r"-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
    re.S,
)
KUBEADM_TOKEN = re.compile(r"\b[a-z0-9]{6}\.[a-z0-9]{16}\b")
CLIENT_KEY_DATA = re.compile(r"(?m)^(\s*client-key-data\s*:\s*).+$")
SENSITIVE_YAML_LINE = re.compile(
    r"(?im)^(\s*(?:password|secret|token|credential|private_key|full_key|opc)\s*:\s*).+$"
)
SENSITIVE_JSON_VALUE = re.compile(
    r'(?i)("(?:password|secret|token|credential|private_key|full_key|opc)"\s*:\s*)'
    r'("(?:\\.|[^"])*"|[^,}\n]+)'
)
DANGEROUS_NAMES = {
    "admin.conf",
    ".kubeadm_join_command.txt",
    "kubeadm_join_command.txt",
}
TEXT_LIMIT = 32 * 1024 * 1024


def _walk_secret_values(value, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SENSITIVE_KEY.search(str(key)):
                if isinstance(child, (str, int, float)) and str(child):
                    found.add(str(child))
            else:
                _walk_secret_values(child, found)
    elif isinstance(value, list):
        for child in value:
            _walk_secret_values(child, found)


def _private_secret_values(private_dir: Path) -> set[str]:
    values: set[str] = set()
    for name in ("resolved-scenario.yml", "fiveg-profile.yml", "deployment-vars.yml"):
        path = private_dir / name
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        _walk_secret_values(data, values)
    # Avoid replacing trivial values that could occur naturally in diagnostics.
    return {value for value in values if len(value) >= 6 and value != "<redacted>"}


def _backup(private_dir: Path, run_dir: Path, source: Path) -> None:
    relative = source.relative_to(run_dir)
    target = private_dir / "raw-shareable-text" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    shutil.copy2(source, target)
    target.chmod(0o600)


def _sanitize_text(text: str, secrets: set[str]) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "<redacted>")
    text = PEM_PRIVATE_KEY.sub("<redacted-private-key>", text)
    text = CLIENT_KEY_DATA.sub(r"\1<redacted>", text)
    text = KUBEADM_TOKEN.sub("<redacted-kubeadm-token>", text)
    text = SENSITIVE_YAML_LINE.sub(r"\1<redacted>", text)
    text = SENSITIVE_JSON_VALUE.sub(r'\1"<redacted>"', text)
    return text


def _dangerous_text(text: str) -> bool:
    if PEM_PRIVATE_KEY.search(text) or KUBEADM_TOKEN.search(text):
        return True
    for line in text.splitlines():
        if re.match(r"^\s*client-key-data\s*:", line) and "<redacted>" not in line:
            return True
    return False


def sanitize_results(run_dir: Path, private_dir: Path) -> dict:
    run_dir = run_dir.resolve()
    private_dir = private_dir.resolve()
    private_dir.mkdir(parents=True, exist_ok=True)
    private_dir.chmod(0o700)
    secrets = _private_secret_values(private_dir)
    changed: list[str] = []
    removed: list[str] = []
    unresolved: list[str] = []

    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink():
            # Shareable results must never point back into the private execution tree.
            target = path.resolve(strict=False)
            try:
                target.relative_to(private_dir)
            except ValueError:
                continue
            path.unlink()
            removed.append(str(path.relative_to(run_dir)))
            continue
        if not path.is_file():
            continue
        relative = str(path.relative_to(run_dir))
        if path.name in DANGEROUS_NAMES:
            _backup(private_dir, run_dir, path)
            path.unlink()
            removed.append(relative)
            continue
        try:
            if path.stat().st_size > TEXT_LIMIT:
                continue
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        clean = _sanitize_text(raw, secrets)
        if clean != raw:
            _backup(private_dir, run_dir, path)
            path.write_text(clean, encoding="utf-8")
            changed.append(relative)
        if _dangerous_text(clean):
            unresolved.append(relative)

    if unresolved:
        raise ValueError(
            "shareable result safety check found unresolved credential material in: "
            + ", ".join(unresolved)
        )
    return {
        "sanitized_files": changed,
        "removed_files": removed,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m synthran.result_safety")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--private-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = sanitize_results(args.run_dir, args.private_dir)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
