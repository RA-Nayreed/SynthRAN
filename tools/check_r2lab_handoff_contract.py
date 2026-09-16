#!/usr/bin/env python3
"""No-hardware regression checks for the R2Lab Ansible handoff."""

from __future__ import annotations

from pathlib import Path

from synthran.inventory import render_inventory
from synthran.r2lab import ssh_options


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"r2lab-handoff-contract: {message}")


def main() -> int:
    controller_known_hosts = Path("/tmp/synthran-controller-known-hosts")
    faraday_known_hosts = Path("/tmp/synthran-faraday-known-hosts")
    identity = "/tmp/r2lab-identity"

    deployment = {
        "platform": "r2lab",
        "nodes": {
            "core": "sopnode-f2",
            "ran": "sopnode-f3",
            "broker": "sopnode-f2",
        },
        "host_vars": {
            "sopnode-f2": {"ip": "192.0.2.2"},
            "sopnode-f3": {"ip": "192.0.2.3"},
        },
        "r2lab_ssh": {
            "host": "faraday.inria.fr",
            "username": "ci-slice",
            "identity_file": identity,
        },
    }
    ue_map = [
        {"device": "qhat01", "tunnel": {"mode": "mbim"}},
        {"device": "qhat03", "tunnel": {"mode": "mbim"}},
    ]

    options = ssh_options(
        "faraday.inria.fr", faraday_known_hosts, identity
    )
    option_text = " ".join(options)
    for token in (
        "-F /dev/null",
        f"UserKnownHostsFile={faraday_known_hosts}",
        "StrictHostKeyChecking=accept-new",
        "BatchMode=yes",
        "ConnectTimeout=15",
        f"-i {identity}",
        "IdentitiesOnly=yes",
    ):
        require(token in option_text, f"canonical Faraday SSH options lost {token!r}")

    inventory = render_inventory(
        deployment,
        ue_map,
        controller_known_hosts,
        faraday_known_hosts,
    )
    children = inventory["all"]["children"]
    faraday = children["faraday"]["hosts"]["faraday.inria.fr"]
    direct = faraday["ansible_ssh_common_args"]
    require("-F /dev/null" in direct, "Ansible Faraday connection inherits local ssh config")
    require("BatchMode=yes" in direct, "Ansible Faraday connection is not non-interactive")
    require("IdentitiesOnly=yes" in direct, "Ansible Faraday connection can try unrelated identities")
    require(
        faraday.get("ansible_ssh_private_key_file") == identity,
        "Ansible Faraday identity differs from reservation identity",
    )

    for ue in ("qhat01", "qhat03"):
        host = children["qhats"]["hosts"][ue]
        proxy = host["ansible_ssh_common_args"]
        require("ProxyCommand=" in proxy, f"{ue} lost the Faraday jump path")
        require("-F /dev/null" in proxy, f"{ue} ProxyCommand inherits controller ssh config")
        require("BatchMode=yes" in proxy, f"{ue} ProxyCommand is not non-interactive")
        require("IdentitiesOnly=yes" in proxy, f"{ue} ProxyCommand can try unrelated identities")
        require(
            "ci-slice@faraday.inria.fr" in proxy,
            f"{ue} ProxyCommand lost the selected R2Lab slice identity",
        )
        require(
            host.get("ansible_ssh_private_key_file") == identity,
            f"{ue} lost the configured SSH identity",
        )

    cleanup = (ROOT / "deployment/roles/r2lab/cleanup/tasks/main.yml").read_text(
        encoding="utf-8"
    )
    stop = (ROOT / "deployment/roles/r2lab/ue/stop/tasks/main.yml").read_text(
        encoding="utf-8"
    )
    require("all-off" not in cleanup, "cleanup still contains global all-off mutation")
    require("r2lab/ue/stop" in cleanup, "cleanup no longer stops only selected UEs")
    require(
        'rhubarbe pdu off "{{ rru }}"' in cleanup,
        "cleanup no longer targets only the selected RRU",
    )
    require(
        "groups['qhats']" in cleanup and "groups['qfits']" in cleanup,
        "cleanup no longer derives the selected physical UE groups",
    )
    require("root@{{ ue }} 'stop.sh'" in stop, "selected MBIM UE stop behavior is missing")
    require("ue_mode == 'qmi'" in stop, "selected QMI UE detach behavior is missing")

    reserve = (ROOT / "deployment/scripts/reserve_r2lab.py").read_text(encoding="utf-8")
    require(
        'if args.host == "faraday.inria.fr"' in reserve
        and '["-F", "/dev/null"]' in reserve,
        "provider lease verifier no longer bypasses local ssh config",
    )
    require(
        '"IdentitiesOnly=yes"' in reserve,
        "provider lease verifier no longer pins the selected identity",
    )

    print("R2Lab Ansible handoff contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
