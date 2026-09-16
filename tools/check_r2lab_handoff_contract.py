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
    rru = (ROOT / "deployment/roles/r2lab/rru/tasks/main.yml").read_text(
        encoding="utf-8"
    )
    connect_playbook = (ROOT / "deployment/playbooks/connect_ues.yml").read_text(
        encoding="utf-8"
    )
    connect_role = (
        ROOT / "deployment/roles/r2lab/ue/connect/tasks/main.yml"
    ).read_text(encoding="utf-8")
    verify_role = (
        ROOT / "deployment/roles/synthran/r2lab_ue_verify/tasks/main.yml"
    ).read_text(encoding="utf-8")

    require("all-off" not in cleanup, "cleanup still contains global all-off mutation")
    require("r2lab/ue/stop" in cleanup, "cleanup no longer stops only selected UEs")
    require(
        "groups['qhats']" in cleanup and "groups['qfits']" in cleanup,
        "cleanup no longer derives the selected physical UE groups",
    )
    require(
        'rhubarbe-pdu off "{{ rru }}"' in cleanup,
        "selected N3xx RRU cleanup no longer uses the maintained SophiaNode helper",
    )
    require(
        'rhubarbe pdu off "{{ rru }}"' not in cleanup,
        "obsolete pinned-reference N3xx RRU power-off command returned",
    )
    require(
        "seconds: 20" in cleanup,
        "N3xx power-off settle interval was removed",
    )
    require(
        'rhubarbe-pdu on "{{ rru }}"' in rru,
        "selected N3xx RRU power-on no longer uses the maintained SophiaNode helper",
    )
    require(
        'rhubarbe pdu on "{{ rru }}"' not in rru,
        "obsolete pinned-reference N3xx RRU power-on command returned",
    )
    require(
        "seconds: 60" in rru,
        "N3xx cold-boot interval was removed",
    )

    require(
        "r2lab_stop_target: \"{{ ue_item if ue_item is defined else ue }}\"" in stop,
        "UE stop role no longer resolves each include-loop item deterministically",
    )
    require(
        'ue: "{{ ue | default(ue_item) }}"' not in stop,
        "sticky UE fact can cause a second selected UE to reuse the first UE identity",
    )
    require(
        "root@{{ r2lab_stop_target }} 'stop.sh'" in stop,
        "selected MBIM UE stop behavior is missing",
    )
    require("ue_mode == 'qmi'" in stop, "selected QMI UE detach behavior is missing")

    # The mutating connect role is the authoritative owner of attachment. A
    # failed start, missing wwan0 address, bad link, or route failure must stop
    # there instead of being swallowed and rediscovered by the read-only gate.
    require(
        "ignore_task_errors: false" in connect_playbook,
        "SynthRAN no longer requires the R2Lab connect owner to fail closed",
    )
    require(
        "ignore_task_errors: true" not in connect_playbook,
        "SynthRAN R2Lab handoff returned to best-effort attachment",
    )
    for task_name in (
        "Retrieve wwan0 IP for {{ ue_item }}",
        "Wait until wwan0 interface is fully up",
        "Add route to UPF IP when wwan0 is ready",
    ):
        require(task_name in connect_role, f"required UE connect task disappeared: {task_name}")
    require(
        connect_role.count("ignore_errors: true") == 1
        and "Check wwan0 connectivity on {{ ue_item }} by pinging UPF" in connect_role,
        "required UE attachment tasks can silently ignore failure",
    )
    require(
        connect_role.count(
            'ignore_errors: "{{ ignore_task_errors | default(true) }}"'
        ) >= 8,
        "R2Lab connect role no longer exposes strict failure control to SynthRAN",
    )
    require(
        "that: synthran_r2lab_probe.rc == 0" in verify_role
        and "verification does not repair or reattach modem state" in verify_role,
        "read-only R2Lab UE acceptance gate was weakened or made mutating",
    )

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
