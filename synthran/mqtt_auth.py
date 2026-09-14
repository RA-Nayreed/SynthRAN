"""Private MQTT credentials kept outside shareable result artifacts."""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import secrets

import yaml

PBKDF2_ITERATIONS = 1000
PBKDF2_HASH_BYTES = 64
PBKDF2_SALT_BYTES = 12
_REQUIRED_FIELDS = {
    "mqtt_publisher_username",
    "mqtt_publisher_password",
    "mqtt_publisher_password_hash",
    "mqtt_collector_username",
    "mqtt_collector_password",
    "mqtt_collector_password_hash",
}


def _mosquitto_hash(password: str) -> str:
    """Return Mosquitto SHA512-PBKDF2 password-file encoding (scheme 7)."""
    salt = os.urandom(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha512", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, PBKDF2_HASH_BYTES
    )
    return "$7${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def _validate_existing(output: Path) -> Path:
    """Reuse a complete private credential file without rotating it on retries."""
    if output.is_symlink() or not output.is_file():
        raise ValueError(f"existing MQTT secrets path is not a regular file: {output}")
    value = yaml.safe_load(output.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not _REQUIRED_FIELDS.issubset(value):
        raise ValueError(f"existing MQTT secrets are incomplete: {output}")
    if any(not isinstance(value[field], str) or not value[field] for field in _REQUIRED_FIELDS):
        raise ValueError(f"existing MQTT secrets contain invalid values: {output}")
    output.chmod(0o600)
    return output


def write_credentials(private_dir: Path) -> Path:
    """Create credentials once for an accepted deployment, then reuse them on retries."""
    private_dir = Path(private_dir)
    private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_dir.chmod(0o700)
    output = private_dir / "experiment-secrets.yml"
    if output.exists() or output.is_symlink():
        return _validate_existing(output)

    publisher_password = secrets.token_urlsafe(32)
    collector_password = secrets.token_urlsafe(32)
    value = {
        "mqtt_publisher_username": "synthran-publisher",
        "mqtt_publisher_password": publisher_password,
        "mqtt_publisher_password_hash": _mosquitto_hash(publisher_password),
        "mqtt_collector_username": "synthran-collector",
        "mqtt_collector_password": collector_password,
        "mqtt_collector_password_hash": _mosquitto_hash(collector_password),
    }
    output.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    output.chmod(0o600)
    return output
