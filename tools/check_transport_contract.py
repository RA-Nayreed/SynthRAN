#!/usr/bin/env python3
"""Static contract for issue #54 N2/N3/N4 transport ownership."""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / "third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json"
TOPOLOGY = ROOT / "deployment/topology.yml"


def fail(message: str) -> None:
    raise SystemExit(message)


def require(text: str, needle: str, context: str) -> None:
    if needle not in text:
        fail(f"{context}: missing required contract text: {needle!r}")


def forbid(text: str, needle: str, context: str) -> None:
    if needle in text:
        fail(f"{context}: forbidden duplicate/legacy transport text remains: {needle!r}")


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def validate_topology() -> dict:
    topology = yaml.safe_load(TOPOLOGY.read_text(encoding="utf-8"))
    if topology.get("schema_version") != 2:
        fail("deployment/topology.yml: issue #54 requires schema_version 2")

    profiles = topology.get("transport_profiles")
    if not isinstance(profiles, dict) or set(profiles) != {"open5gs", "free5gc", "oai"}:
        fail("deployment/topology.yml: expected open5gs/free5gc/oai transport profiles")

    managed_bridges = {"n2br", "n3br", "n4br"}
    for name, profile in profiles.items():
        for key in ("bridges", "workload_interfaces", "colocated", "split", "endpoints"):
            if not isinstance(profile.get(key), dict):
                fail(f"transport profile {name}: {key} must be a mapping")

        bridges = profile["bridges"]
        for role in ("core", "ran"):
            values = bridges.get(role)
            if not isinstance(values, list):
                fail(f"transport profile {name}: bridges.{role} must be a list")
            unknown = set(values) - managed_bridges
            if unknown:
                fail(f"transport profile {name}: unknown managed bridges: {sorted(unknown)}")

        for mode in ("colocated", "split"):
            addresses = profile[mode].get("addresses", {})
            if not isinstance(addresses, dict):
                fail(f"transport profile {name}: {mode}.addresses must be a mapping")
            for bridge, value in addresses.items():
                if bridge not in managed_bridges:
                    fail(f"transport profile {name}: address assigned to unknown bridge {bridge}")
                candidates = value.values() if isinstance(value, dict) else (value,)
                for candidate in candidates:
                    try:
                        ipaddress.ip_interface(str(candidate))
                    except ValueError as error:
                        fail(f"transport profile {name}: invalid interface {candidate!r}: {error}")

        split = profile["split"]
        gre = split.get("gre", [])
        patches = split.get("patches", [])
        if not isinstance(gre, list) or not isinstance(patches, list):
            fail(f"transport profile {name}: split.gre and split.patches must be lists")
        for bridge in gre:
            if bridge not in split.get("addresses", {}):
                fail(f"transport profile {name}: GRE bridge {bridge} lacks split addresses")
            address = split["addresses"][bridge]
            if not isinstance(address, dict) or set(address) != {"core", "ran"}:
                fail(f"transport profile {name}: GRE bridge {bridge} requires core/ran addresses")
            if bridge not in bridges["core"] or bridge not in bridges["ran"]:
                fail(f"transport profile {name}: GRE bridge {bridge} must exist on both hosts")
        for patch in patches:
            required = {"a", "b", "a_port", "b_port"}
            if not isinstance(patch, dict) or not required <= set(patch):
                fail(f"transport profile {name}: malformed patch contract: {patch!r}")
            if patch["a"] not in bridges["core"] or patch["b"] not in bridges["core"]:
                fail(f"transport profile {name}: patch references undeclared core bridge")

    rans = topology.get("rans")
    if not isinstance(rans, dict) or not rans:
        fail("deployment/topology.yml: rans mapping is missing")
    for ran_name, cores in rans.items():
        if not isinstance(cores, dict):
            fail(f"deployment/topology.yml: rans.{ran_name} must be a mapping")
        for core_name, selected in cores.items():
            if core_name not in profiles:
                fail(f"deployment/topology.yml: no transport profile for {core_name}")
            if selected.get("transport") != profiles[core_name]:
                fail(f"deployment/topology.yml: {ran_name}+{core_name} does not select its one transport profile")
            if not isinstance(selected.get("network"), dict) or not selected["network"]:
                fail(f"deployment/topology.yml: {ran_name}+{core_name} network mapping is empty")

    return topology


def validate_reference(reference: Path) -> None:
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    expected = pin["commit"]
    actual = subprocess.run(
        ["git", "-C", str(reference), "rev-parse", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    if actual != expected:
        fail(f"reference checkout mismatch: expected {expected}, found {actual}")

    reference_gre = (reference / "roles/setup/gre_tunnel/tasks/gre_loop.yml").read_text(
        encoding="utf-8"
    )
    require(reference_gre, "type=gre", "pinned reference GRE role")
    forbid(reference_gre, "options:key", "pinned reference GRE role")

    reference_free5gc = (
        reference / "roles/5g/free5gc/config/templates/free5gc-values-override.yaml.j2"
    ).read_text(encoding="utf-8")
    require(reference_free5gc, "'n3br' if multinode", "pinned reference Free5GC adapter")

    reference_srsran = (
        reference / "roles/5g/srsRAN/common/defaults/main.yml"
    ).read_text(encoding="utf-8")
    for marker in ("10.10.3.200", "10.10.3.234", "10.100.50.250", "192.168.3.201"):
        require(reference_srsran, marker, "pinned reference srsRAN network contract")


def validate_consumers() -> None:
    inventory = read("synthran/inventory.py")
    require(inventory, '"synthran_topology": topology', "inventory.py")
    require(inventory, 'topology["contract_version"]', "inventory.py")

    ovs = read("deployment/roles/setup/ovs/tasks/main.yml")
    require(ovs, "synthran_topology.transport.bridges", "setup/ovs")
    forbid(ovs, "core == 'free5gc'", "setup/ovs")
    forbid(ovs, "legacy", "setup/ovs")
    forbid(ovs, "['n2br', 'n3br']", "setup/ovs")

    cni = read("deployment/roles/setup/cni/tasks/main.yml")
    forbid(cni, "ovs-vsctl", "setup/cni")
    forbid(cni, "openvswitch-switch", "setup/cni")

    gre_main = read("deployment/roles/setup/gre_tunnel/tasks/main.yml")
    gre_loop = read("deployment/roles/setup/gre_tunnel/tasks/gre_loop.yml")
    gre = gre_main + "\n" + gre_loop
    for marker in (
        "synthran_topology.transport",
        "synthran_transport_mode",
        "synthran_transport_gre_bridges",
        "options:remote_ip",
    ):
        require(gre, marker, "setup/gre_tunnel")
    for marker in (
        "options:key",
        "core == 'open5gs'",
        "core == 'free5gc'",
        "core == 'oai'",
        "10.10.3.254/24",
        "192.168.3.254/24",
        "10.100.50.238/29",
        "192.168.4.254/24",
        "legacy",
    ):
        forbid(gre, marker, "setup/gre_tunnel")

    network = read("deployment/playbooks/network.yml")
    if network.count("setup/gre_tunnel") != 1:
        fail("network.yml: transport role must have one orchestration owner")
    require(network, "Configure authoritative N2/N3/N4 host transport", "network.yml")

    open5gs_deploy = read("deployment/roles/5g/open5gs/deploy/tasks/main.yml")
    require(open5gs_deploy, "synthran_topology.transport.bridges.core", "Open5GS deploy")
    require(open5gs_deploy, "synthran_topology.transport.endpoints.amf_ngap_ip", "Open5GS deploy")
    forbid(open5gs_deploy, "ip addr add 10.10.", "Open5GS deploy")
    forbid(open5gs_deploy, 'grep -q "inet 10.10.3.200"', "Open5GS deploy")

    open5gs_amf = read("deployment/roles/5g/open5gs/config/templates/amf-configmap.yaml.j2")
    require(open5gs_amf, "synthran_topology.transport.endpoints.amf_ngap_ip", "Open5GS AMF")
    forbid(open5gs_amf, "10.10.3.200", "Open5GS AMF")

    oai = read("deployment/roles/5g/oai/setup/tasks/main.yml")
    require(oai, "synthran_topology.transport.workload_interfaces.core.n3", "OAI setup")
    require(oai, "synthran_topology.transport.workload_interfaces.ran.n3", "OAI setup")
    forbid(oai, "multus_core_if: n3br", "OAI setup")
    forbid(oai, "multus_ran_if: n3br", "OAI setup")

    free5gc = read("deployment/roles/5g/free5gc/config/templates/free5gc-values-override.yaml.j2")
    require(free5gc, "synthran_topology.transport.workload_interfaces.core", "Free5GC adapter")
    require(free5gc, "synthran_topology.transport.endpoints.amf_ngap_ip", "Free5GC adapter")
    require(free5gc, "synthran_topology.transport.endpoints.branching_upf_n3_ip", "Free5GC adapter")
    forbid(free5gc, 'ipAddress: "10.100.50.234"', "Free5GC adapter")
    forbid(free5gc, "- 10.100.50.233", "Free5GC adapter")

    ueransim_free5gc = read(
        "deployment/roles/5g/ueransim/config/templates/ueransim-gnb-values.yaml.j2"
    )
    require(
        ueransim_free5gc,
        "synthran_topology.transport.workload_interfaces.ran.n3",
        "UERANSIM Free5GC adapter",
    )
    ueransim_oai = read(
        "deployment/roles/5g/ueransim/shared/templates/ueransim-gnb-values-oai.yaml.j2"
    )
    forbid(ueransim_oai, "gnb_n2_ip", "UERANSIM OAI adapter")
    forbid(ueransim_oai, "gnb_n3_ip", "UERANSIM OAI adapter")
    require(ueransim_oai, "net.gnb_ip", "UERANSIM OAI adapter")
    nad = read("deployment/roles/5g/ueransim/shared/templates/nad-ovs-gnb.yaml.j2")
    require(nad, "synthran_topology.transport.workload_interfaces.ran.n3", "UERANSIM NAD")

    site = read("deployment/playbooks/site.yml")
    if site.index("network.yml") >= site.index("attest_transport.yml"):
        fail("site.yml: transport evidence must be captured after network deployment")
    if site.index("attest_transport.yml") >= site.index("attest_deployment.yml"):
        fail("site.yml: transport evidence must precede generic deployment attestation")

    evidence = read("deployment/playbooks/attest_transport.yml")
    for marker in (
        "ovs-vsctl show",
        "ip, -j, address, show",
        "ip, -j, route, show, table, all",
        "network-attachment-definitions.k8s.cni.cncf.io",
        "synthran_commit",
        "deployment_hash",
        "selected_topology",
        "transport-evidence.json",
    ):
        require(evidence, marker, "attest_transport.yml")

    documentation = read("docs/transport-contract.md")
    for marker in (
        "Open5GS",
        "Free5GC",
        "OAI",
        "10.10.3.254/24",
        "10.100.50.238/29",
        "192.168.3.254/24",
        "transport-evidence.json",
    ):
        require(documentation, marker, "transport-contract.md")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True, type=Path)
    args = parser.parse_args()

    validate_topology()
    validate_reference(args.reference)
    validate_consumers()
    print("issue #54 N2/N3/N4 transport ownership contract OK")


if __name__ == "__main__":
    main()
