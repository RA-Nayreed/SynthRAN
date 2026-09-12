"""Per-run MQTT credentials kept outside shareable result artifacts."""
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


def write_credentials(private_dir: Path) -> Path:
    """Create one write-only publisher and one read-only collector identity."""
    private_dir = Path(private_dir)
    private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_dir.chmod(0o700)
    output = private_dir / "experiment-secrets.yml"
    if output.exists():
        raise FileExistsError(f"refusing to replace existing MQTT secrets: {output}")

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
