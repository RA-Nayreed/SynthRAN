#!/usr/bin/env python3
"""Prove selected software UE identity, tunnel and source-bound user plane."""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import re
import subprocess
from pathlib import Path


TUNNEL_PATTERN = re.compile(r"^(tun_srsue\d+|uesimtun\d*|oaitun_[A-Za-z0-9_.-]+)$")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def discover(namespace: str) -> list[dict]:
    pods = json.loads(
        subprocess.check_output(
            [
                "kubectl",
                "get",
                "pods",
                "-n",
                namespace,
                "--field-selector=status.phase=Running",
                "-o",
                "json",
            ],
            text=True,
        )
    )
    found: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for pod in pods.get("items", []):
        metadata = pod.get("metadata", {})
        name = str(metadata.get("name", ""))
        labels = metadata.get("labels", {}) or {}
        for container in pod.get("spec", {}).get("containers", []) or []:
            cname = str(container.get("name", ""))
            result = _run(
                [
                    "kubectl",
                    "exec",
                    "-n",
                    namespace,
                    name,
                    "-c",
                    cname,
                    "--",
                    "ip",
                    "-o",
                    "link",
                    "show",
                ]
            )
            if result.returncode:
                continue
            for line in result.stdout.splitlines():
                parts = line.split(":", 2)
                if len(parts) < 2:
                    continue
                interface = parts[1].strip().split("@", 1)[0]
                identity = (namespace, name, interface)
                if not TUNNEL_PATTERN.fullmatch(interface) or identity in seen:
                    continue
                address_result = _run(
                    [
                        "kubectl",
                        "exec",
                        "-n",
                        namespace,
                        name,
                        "-c",
                        cname,
                        "--",
                        "ip",
                        "-4",
                        "-o",
                        "addr",
                        "show",
                        "dev",
                        interface,
                    ]
                )
                addresses = re.findall(r"\binet\s+([0-9.]+)/", address_result.stdout)
                if len(addresses) == 1:
                    seen.add(identity)
                    found.append(
                        {
                            "namespace": namespace,
                            "pod": name,
                            "container": cname,
                            "interface": interface,
                            "address": addresses[0],
                            "pod_labels": labels,
                        }
                    )
    return found


def _matches(candidate: dict, selector: dict) -> bool:
    if candidate["namespace"] != selector.get("namespace"):
        return False
    if candidate["interface"] != selector.get("interface"):
        return False
    prefix = selector.get("pod_name_prefix")
    if prefix and not candidate["pod"].startswith(prefix):
        return False
    labels = selector.get("pod_labels", {})
    return all(candidate.get("pod_labels", {}).get(key) == value for key, value in labels.items())


def _owned_by_ran(candidate: dict, ran: str) -> bool:
    labels = candidate.get("pod_labels", {})
    if ran == "srsran":
        return labels.get("app") == "srsran" and labels.get("component") == "ue"
    if ran == "ueransim":
        return labels.get("component") == "ue"
    if ran == "oai":
        return candidate["pod"].startswith("oai-nr-ue")
    return False


def _read_remote_config(candidate: dict, path: str) -> str:
    result = _run(
        [
            "kubectl",
            "exec",
            "-n",
            candidate["namespace"],
            candidate["pod"],
            "-c",
            candidate["container"],
            "--",
            "cat",
            path,
        ]
    )
    if result.returncode:
        raise ValueError(
            f"cannot read {path} from {candidate['namespace']}/{candidate['pod']}: "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def _check_config(ue: dict, candidate: dict) -> None:
    path = ue["tunnel"].get("identity_file")
    if not path:
        return
    content = _read_remote_config(candidate, path)
    checks = {
        "IMSI": rf"(?m)^\s*imsi\s*=\s*{re.escape(ue['imsi'])}\s*$",
        "DNN": rf"(?m)^\s*apn\s*=\s*{re.escape(ue['dnn'])}\s*$",
        "interface": rf"(?m)^\s*ip_devname\s*=\s*{re.escape(ue['tunnel']['interface'])}\s*$",
    }
    missing = [label for label, pattern in checks.items() if not re.search(pattern, content)]
    if missing:
        raise ValueError(
            f"{ue['device']} tunnel exists in {candidate['pod']}, but {path} "
            f"does not match its expected {', '.join(missing)}"
        )


def _upf_target(ue: dict) -> str:
    literal = str(ue["address_cidr"]).split("/", 1)[0]
    octets = literal.split(".")
    if len(octets) != 4:
        raise ValueError(f"invalid UE address contract for {ue['device']}: {literal}")
    return ".".join(octets[:3] + ["1"])


def _probe_user_plane(candidate: dict, ue: dict) -> dict:
    target = _upf_target(ue)
    command = [
        "kubectl",
        "exec",
        "-n",
        candidate["namespace"],
        candidate["pod"],
        "-c",
        candidate["container"],
        "--",
        "ping",
        "-I",
        candidate["interface"],
        "-c",
        "1",
        "-W",
        "3",
        target,
    ]
    result = _run(command)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(
            f"{ue['device']} cannot reach selected UPF {target} from "
            f"{candidate['interface']}: {detail}"
        )
    return {
        "verified": True,
        "method": "icmp_echo",
        "source_interface": candidate["interface"],
        "source_address": candidate["address"],
        "target_address": target,
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def resolve_bindings(manifest: dict, discovered: list[dict]) -> list[dict]:
    deployment = manifest.get("deployment", {})
    if deployment.get("platform") != "rfsim":
        raise ValueError("software UE validation requires an rfsim deployment")
    expected = deployment.get("ues", [])
    if not expected:
        raise ValueError("deployment identity contains no UEs")
    ran = str(deployment.get("ran", ""))
    bindings: list[dict] = []
    used: set[tuple[str, str, str]] = set()

    for ue in expected:
        matches = [candidate for candidate in discovered if _matches(candidate, ue["tunnel"])]
        if len(matches) != 1:
            locations = [
                f"{item['namespace']}/{item['pod']}:{item['interface']}" for item in matches
            ]
            raise ValueError(
                f"expected exactly one live tunnel for {ue['device']} "
                f"({ue['tunnel']}), found {len(matches)}: {locations}"
            )
        candidate = matches[0]
        identity = (candidate["namespace"], candidate["pod"], candidate["interface"])
        if identity in used:
            raise ValueError(f"multiple devices resolve to the same live tunnel: {identity}")
        try:
            network = ipaddress.ip_network(ue["address_cidr"], strict=False)
            address = ipaddress.ip_address(candidate["address"])
        except ValueError as exc:
            raise ValueError(f"invalid tunnel address contract for {ue['device']}: {exc}") from exc
        if address not in network:
            raise ValueError(
                f"{ue['device']} has {address} on {candidate['interface']}, "
                f"outside its expected slice network {network}"
            )
        _check_config(ue, candidate)
        user_plane = _probe_user_plane(candidate, ue)
        used.add(identity)
        bindings.append(
            {
                "device": ue["device"],
                "index": ue["index"],
                "imsi": ue["imsi"],
                "slice": ue["slice"],
                "sst": str(ue["sst"]),
                "sd": str(ue["sd"]),
                "dnn": ue["dnn"],
                "namespace": candidate["namespace"],
                "pod": candidate["pod"],
                "container": candidate["container"],
                "interface": candidate["interface"],
                "address": candidate["address"],
                "software_verified": True,
                "user_plane": user_plane,
            }
        )

    extras = [
        item
        for item in discovered
        if _owned_by_ran(item, ran)
        and (item["namespace"], item["pod"], item["interface"]) not in used
    ]
    if extras:
        detail = [f"{item['namespace']}/{item['pod']}:{item['interface']}" for item in extras]
        raise ValueError(f"unexpected live {ran} UE tunnels are present: {detail}")
    return bindings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    namespace = manifest["deployment"]["topology"]["namespace"]
    try:
        bindings = resolve_bindings(manifest, discover(namespace))
    except (KeyError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise SystemExit(f"live software UE acceptance check failed: {exc}") from exc
    print(json.dumps(bindings, sort_keys=True))


if __name__ == "__main__":
    main()
