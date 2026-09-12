"""Render deployment inventory and the upstream Ansible execution context."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shlex
import shutil
import socket

import yaml

from .deployment_state import build_manifest, build_ue_map, content_hash
from .profile_validation import validate_network_profile, validate_ue_catalog
from .r2lab import access
from .scenario import redacted


def resolve_network_profile(d: dict) -> tuple[dict, str]:
    """Build the effective network profile for only the selected UEs.

    Network policy (PLMN/DNN/slices/QoS/security) is independent of UE identity.
    Stable UE identity/transport metadata comes from the UE catalog, while the
    scenario explicitly assigns one slice from the selected network profile to
    every selected UE.
    """
    profile_name = d["network_profile"]
    profile_source = Path(
        d.get("network_profile_file")
        or Path("deployment/group_vars/all", f"network_profile_{profile_name}.yaml")
    )
    catalog_source = Path(
        d.get("ue_catalog_file") or "deployment/group_vars/all/ue_catalog.yaml"
    )
    if not profile_source.is_file():
        raise SystemExit(f"network profile not found: {profile_source}")
    if not catalog_source.is_file():
        raise SystemExit(f"UE catalog not found: {catalog_source}")

    profile = yaml.safe_load(profile_source.read_text())
    catalog = yaml.safe_load(catalog_source.read_text())
    validate_network_profile(profile)
    validate_ue_catalog(catalog)

    selected_ues = {}
    assignments = d["ue_slices"]
    for name in d["ues"]:
        if name not in catalog["ues"]:
            raise SystemExit(f"selected UE {name!r} is absent from {catalog_source}")
        ue_profile = copy.deepcopy(catalog["ues"][name])
        ue_platform = ue_profile.pop("platform")
        if ue_platform != d["platform"]:
            raise SystemExit(
                f"selected UE {name!r} belongs to platform {ue_platform!r}, "
                f"not {d['platform']!r}"
            )
        ue_profile["slice"] = assignments[name]
        selected_ues[name] = ue_profile

    effective = copy.deepcopy(profile)
    effective["ues"] = selected_ues
    return effective, profile_name


def _ssh_common_args(known_hosts: Path, extra: str = "") -> str:
    parts = [
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]
    rendered = shlex.join(parts)
    return rendered + (f" {extra.strip()}" if extra.strip() else "")


def render_inventory(
    d: dict,
    ue_map: list[dict],
    controller_known_hosts: Path,
    faraday_known_hosts: Path,
) -> dict:
    nodes = d["nodes"]
    children = {}
    for group, name in [
        ("core_node", nodes["core"]),
        ("ran_node", nodes["ran"]),
        ("broker_node", nodes.get("broker", nodes["core"])),
    ]:
        host_vars = copy.deepcopy(d.get("host_vars", {}).get(name, {}))
        extra_ssh = str(host_vars.pop("ansible_ssh_common_args", "") or "")
        address = host_vars.get("ip") or socket.gethostbyname(
            host_vars.get("ansible_host", name)
        )
        children[group] = {
            "hosts": {
                name: {
                    "ip": address,
                    "ansible_python_interpreter": "/usr/bin/python3",
                    "ansible_ssh_common_args": _ssh_common_args(
                        controller_known_hosts, extra_ssh
                    ),
                    **host_vars,
                }
            }
        }
    children["sopnodes"] = {"children": {"core_node": {}, "ran_node": {}}}
    children["k8s_workers"] = {"children": {"ran_node": {}}}
    children["physical_ues"] = {"hosts": {}}
    children["faraday"] = {"hosts": {}}
    if d["platform"] == "r2lab":
        settings = access(d)
        ssh = [
            "ssh",
            "-o",
            f"UserKnownHostsFile={faraday_known_hosts}",
            "-o",
            "StrictHostKeyChecking=accept-new",
        ]
        if settings["identity_file"]:
            ssh += ["-i", settings["identity_file"]]
        target = (
            settings["username"] + "@" if settings["username"] else ""
        ) + settings["host"]
        proxy = shlex.join(ssh + ["-W", "%h:%p", target])
        faraday_vars = {
            "ansible_host": settings["host"],
            "ansible_python_interpreter": "/usr/bin/python3",
            "ansible_ssh_common_args": _ssh_common_args(faraday_known_hosts),
        }
        if settings["username"]:
            faraday_vars["ansible_user"] = settings["username"]
        if settings["identity_file"]:
            faraday_vars["ansible_ssh_private_key_file"] = settings["identity_file"]
        children["faraday"]["hosts"]["faraday.inria.fr"] = faraday_vars
        for group in ("qhats", "qfits"):
            children[group] = {"hosts": {}}
        for ue in ue_map:
            name = ue["device"]
            group = (
                "qhats"
                if name.startswith("qhat")
                else "qfits" if name.startswith("qfit") else None
            )
            if group is None:
                raise SystemExit(
                    f"Upstream R2Lab modem workflow requires a qhat or qfit host: {name}"
                )
            host_vars = copy.deepcopy(d.get("host_vars", {}).get(name, {}))
            extra_ssh = str(host_vars.pop("ansible_ssh_common_args", "") or "")
            proxy_arg = "-o " + shlex.quote("ProxyCommand=" + proxy)
            host = {
                "ansible_user": "root",
                "ansible_python_interpreter": "/usr/bin/python3",
                "ansible_ssh_common_args": _ssh_common_args(
                    controller_known_hosts,
                    f"{proxy_arg} {extra_ssh}".strip(),
                ),
                "mode": ue["tunnel"]["mode"],
            }
            if settings["identity_file"]:
                host["ansible_ssh_private_key_file"] = settings["identity_file"]
            host.update(host_vars)
            children[group]["hosts"][name] = host
        children["physical_ues"] = {"children": {"qhats": {}, "qfits": {}}}
    return {"all": {"children": children}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    c = yaml.safe_load(args.config.read_text())
    d = c["deployment"]
    nodes, ues = d["nodes"], d["ues"]
    if d["ran"].lower() == "srsran" and d["platform"] == "rfsim" and len(ues) > 635:
        raise ValueError("srsRAN RFSIM exceeds the available TCP port range")
    if d["platform"] == "r2lab" and d["ran"].lower() == "ueransim":
        raise ValueError("UERANSIM cannot drive an R2Lab physical radio")

    profile, profile_name = resolve_network_profile(d)
    ue_map = build_ue_map(c, profile)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    private_dir = Path(".synthran/execution") / args.run_dir.name
    private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_dir.chmod(0o700)

    controller_known_hosts = private_dir / "ssh-known-hosts"
    controller_known_hosts.touch(exist_ok=True)
    controller_known_hosts.chmod(0o600)
    faraday_known_hosts = Path(
        os.environ.get(
            "R2LAB_FARADAY_KNOWN_HOSTS",
            ".synthran/r2lab/faraday_known_hosts",
        )
    ).expanduser().resolve()
    faraday_known_hosts.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    faraday_known_hosts.touch(exist_ok=True)
    faraday_known_hosts.chmod(0o600)

    raw_inventory = render_inventory(
        d,
        ue_map,
        controller_known_hosts.resolve(),
        faraday_known_hosts,
    )
    private_inventory_path = private_dir / "inventory.yml"
    private_inventory_path.write_text(yaml.safe_dump(raw_inventory, sort_keys=False))
    private_inventory_path.chmod(0o600)
    (args.run_dir / "inventory.yml").write_text(
        yaml.safe_dump(redacted(raw_inventory), sort_keys=False)
    )

    effective_profile_path = private_dir / "network-profile.yml"
    effective_profile_path.write_text(yaml.safe_dump(profile, sort_keys=False))
    effective_profile_path.chmod(0o600)
    (args.run_dir / "network-profile.yml").write_text(
        yaml.safe_dump(redacted(profile), sort_keys=False)
    )

    topology_source = Path(d.get("topology_file", "deployment/topology.yml"))
    topologies = yaml.safe_load(topology_source.read_text())
    try:
        topology = copy.deepcopy(
            topologies["rans"][d["ran"].lower()][d["core"].lower()]
        )
    except KeyError as error:
        raise SystemExit(
            f"No asserted topology contract for {d['ran']} + {d['core']}"
        ) from error
    if d["ran"].lower() == "srsran" and d["core"].lower() == "free5gc":
        n2 = topology["network"]["n2"]
        endpoint = (
            "amf_ip_colocated" if nodes["core"] == nodes["ran"] else "amf_ip_split"
        )
        n2["amf_ip"] = n2[endpoint]
        n2.pop("amf_ip_colocated")
        n2.pop("amf_ip_split")

    topology["contract_version"] = topologies["schema_version"]
    manifest = build_manifest(c, profile, ue_map, topology)
    selected = manifest["deployment"]
    for key in ("ansible_vars", "host_vars"):
        raw = selected.pop(key, {})
        selected[f"{key}_hash"] = content_hash(raw)
    manifest["deployment_hash"] = content_hash(selected)
    manifest_path = Path(args.run_dir, "deployment-fingerprint.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    variables = {
        **d.get("ansible_vars", {}),
        "synthran_root": str(Path.cwd()),
        "core": d["core"],
        "ran": "srsRAN" if d["ran"].lower() == "srsran" else d["ran"],
        "rru": "rfsim" if d["platform"] == "rfsim" else d.get("ru", d["platform"]),
        "platform": d["platform"],
        "network_profile": profile_name,
        "network_profile_file": str(effective_profile_path.resolve()),
        "core_node_name": nodes["core"],
        "ran_node_name": nodes["ran"],
        "broker_node_name": nodes.get("broker", nodes["core"]),
        "bridge_enabled": d.get("bridge_enabled", True),
        "open5gs_webui_enabled": d.get("open5gs_webui_enabled", False),
        "run_dir": str(Path(args.run_dir).resolve()),
        "scenario_file": str(Path(args.config).resolve()),
        "ue_count": len(ues),
        "synthran_ue_map": ue_map,
        "synthran_topology": topology,
        "synthran_deployment_contract": manifest,
        "synthran_deployment_contract_file": str(manifest_path.resolve()),
        "synthran_private_dir": str(private_dir.resolve()),
    }
    private_vars_path = private_dir / "deployment-vars.yml"
    private_vars_path.write_text(yaml.safe_dump(variables, sort_keys=False))
    private_vars_path.chmod(0o600)
    Path(args.run_dir, "deployment-vars.yml").write_text(
        yaml.safe_dump(redacted(variables), sort_keys=False)
    )

    context = private_dir / "ansible"
    shutil.copytree("deployment/playbooks", context / "playbooks", dirs_exist_ok=True)
    shutil.copytree("deployment/group_vars", context / "group_vars", dirs_exist_ok=True)
    shutil.copyfile(
        effective_profile_path, context / "group_vars/all/network_profile_resolved.yaml"
    )
    if not (context / "roles").exists():
        (context / "roles").symlink_to(
            Path("deployment/roles").resolve(), target_is_directory=True
        )


if __name__ == "__main__":
    main()
