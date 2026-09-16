#!/usr/bin/env python3
"""Validate the Sub 07 srsRAN ownership and rendered-source contract."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXECUTION_REFERENCE = ROOT / "third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json"
COMMON_DEFAULTS = ROOT / "deployment/roles/5g/srsRAN/common/defaults/main.yml"
CONFIG_MAIN = ROOT / "deployment/roles/5g/srsRAN/config/tasks/main.yml"
APPLY_PROFILE = ROOT / "deployment/roles/5g/srsRAN/config/tasks/apply_network_profile.yaml"
HARDEN = ROOT / "deployment/roles/5g/srsRAN/config/tasks/harden_runtime.yml"
DEPLOY_MAIN = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/main.yml"
DEPLOY_GNB = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/deploy_gnb.yml"
MATERIALIZE = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/materialize_reference.yml"
HEALTH = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/verify_ran_health.yml"
START_BROKER = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/start_broker.yml"
LOCAL_DEPLOY_WITH_CHECK = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/deploy_with_check.yml"
LOCAL_DEPLOY_SRSUES = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/deploy_srsues.yml"

IMAGE_SOURCE = 'image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"'
IMAGE_HARDENED = 'image: "{{ .Values.image.repository }}"'
SIDECAR_HARDENED = 'image: "{{ .Values.logSidecarImage }}"'
REFERENCE_FATAL_MARKERS = (
    "Unable to create radio session",
    "Failure to create rfnoc_graph",
    "RFNOC::MGMT",
    "Connection refused",
    "Failed to open device",
)
TIMING_FAILURE_MARKERS = (
    "Real-time failure in RF",
    "DL task queue is full",
    "DL_TTI",
    "UL_TTI",
    "Downlink data late",
)


def fail(message: str) -> None:
    raise SystemExit(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def text(path: Path) -> str:
    require(path.is_file(), f"missing required file: {path}")
    return path.read_text(encoding="utf-8")


def git_head(path: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()


def pin_from_defaults() -> str:
    match = re.search(r"^version:\s*([0-9a-f]{40})\s*$", text(COMMON_DEFAULTS), re.M)
    require(match is not None, "srsRAN downstream chart version is not an immutable 40-hex pin")
    return match.group(1)


def harden_chart_template(source: str) -> str:
    result = source.replace(IMAGE_SOURCE, IMAGE_HARDENED)
    result = re.sub(
        r"(?m)^(\s*)image:\s*busybox\s*$",
        rf'\1{SIDECAR_HARDENED}',
        result,
    )
    return result


def hardened_template_valid(source: str) -> bool:
    return (
        source.count(IMAGE_HARDENED) == 1
        and source.count(SIDECAR_HARDENED) == 1
        and IMAGE_SOURCE not in source
    )


def check_reference(reference: Path) -> None:
    contract = json.loads(EXECUTION_REFERENCE.read_text(encoding="utf-8"))
    expected = contract["commit"]
    require(
        git_head(reference) == expected,
        "5g-Ansible checkout does not match EXECUTION_REFERENCE.json",
    )

    physical = text(reference / "roles/5g/srsRAN/deploy/tasks/deploy_with_check.yml")
    require(
        "Read gNB logs after the stability window" in physical,
        "pinned physical lifecycle lost its post-stability radio-log read",
    )
    require(
        "register: gnb_runtime_log" in physical and "--tail=400" in physical,
        "pinned physical lifecycle no longer classifies a bounded post-stability gNB log",
    )
    for marker in REFERENCE_FATAL_MARKERS:
        require(marker in physical, f"pinned physical lifecycle lost fatal marker: {marker}")
    require(
        "rru == 'n320'" in physical,
        "pinned alternate-address recovery is no longer N320-scoped",
    )
    require(
        "192.168.235.105" in physical and "192.168.235.106" in physical,
        "pinned N320 alternate-address pair changed",
    )
    require(
        "192.168.235.103" not in physical and "192.168.235.104" not in physical,
        "pinned lifecycle unexpectedly gained N300 address swapping",
    )

    rfsim_ues = text(reference / "roles/5g/srsRAN/deploy/tasks/deploy_srsues.yml")
    require(
        "ue_list is defined" in rfsim_ues,
        "reference RFSIM UE pod task lost prepared-UE contract",
    )
    require(
        "values-rfsim.yaml" in rfsim_ues,
        "reference RFSIM UE pod task lost prepared values input",
    )


def check_chart(chart: Path) -> None:
    expected = pin_from_defaults()
    require(
        git_head(chart) == expected,
        "srsran-helm checkout does not match SynthRAN's immutable chart pin",
    )

    deployment = text(chart / "charts/srsran-gnb/templates/deployment.yaml")
    require(
        ".Values.n3networkName" in deployment,
        "pinned chart no longer owns parameterized N3 attachment naming",
    )
    require(
        IMAGE_SOURCE in deployment,
        "pinned chart gNB image source shape changed; re-audit hardening",
    )
    require(
        re.search(r"(?m)^\s*image:\s*busybox\s*$", deployment) is not None,
        "pinned chart log-sidecar image source shape changed",
    )
    require(
        "tail -f /var/log/gnb.log" in deployment,
        "pinned chart log collector no longer reads /var/log/gnb.log",
    )

    n320 = yaml.safe_load(text(chart / "charts/srsran-gnb/values-n320-n78-20MHz.yaml"))
    require(
        n320["gnbConfig"]["log"]["filename"] == "/tmp/gnb.log",
        "N320 upstream log default changed; re-audit local log adapter",
    )
    require(
        n320["gnbConfig"]["remote_control"]["enabled"] is True,
        "N320 upstream remote-control default changed",
    )
    require(
        n320["gnbConfig"]["remote_control"]["bind_addr"] == "0.0.0.0",
        "N320 upstream remote-control bind changed",
    )
    require(
        "addr=192.168.235.105" in n320["gnbConfig"]["ru_sdr"]["device_args"],
        "N320 upstream RF endpoint changed",
    )
    require(
        str(n320["ruPodIp"]) == "192.168.235.240",
        "N320 upstream RU pod address changed",
    )

    n300 = yaml.safe_load(text(chart / "charts/srsran-gnb/values-n300-n78-20MHz.yaml"))
    require(
        "addr=192.168.235.103" in n300["gnbConfig"]["ru_sdr"]["device_args"],
        "N300 upstream endpoint changed",
    )

    once = harden_chart_template(deployment)
    twice = harden_chart_template(once)
    require(
        hardened_template_valid(once),
        "pristine pinned chart does not harden to the expected final template",
    )
    require(
        once == twice,
        "chart hardening is not idempotent on an already-hardened template",
    )
    malformed = deployment.replace(IMAGE_SOURCE, 'image: "unexpected:latest"', 1)
    require(
        not hardened_template_valid(harden_chart_template(malformed)),
        "malformed gNB image site was silently accepted by fixture contract",
    )


def check_local() -> None:
    require(
        not LOCAL_DEPLOY_WITH_CHECK.exists(),
        "local copied deploy_with_check.yml must stay deleted",
    )
    require(
        not LOCAL_DEPLOY_SRSUES.exists(),
        "reference-equivalent local deploy_srsues.yml must stay deleted",
    )

    materialize = text(MATERIALIZE)
    for needle in (
        "EXECUTION_REFERENCE.json",
        "synthran.reference_checkout",
        "rev-parse",
        "synthran_srsran_reference_deploy_with_check",
        "synthran_srsran_reference_deploy_srsues",
    ):
        require(
            needle in materialize,
            f"reference materialization lost contract surface: {needle}",
        )
    require(
        "ansible.builtin.git" not in materialize,
        "srsRAN reintroduced a second pinned-reference checkout implementation",
    )

    deploy_main = text(DEPLOY_MAIN)
    require(
        "synthran_srsran_reference_deploy_srsues" in deploy_main,
        "RFSIM pod lifecycle is no longer delegated",
    )
    require(
        "verify_ran_health.yml" in deploy_main,
        "physical RAN-local acceptance is no longer invoked",
    )

    deploy_gnb = text(DEPLOY_GNB)
    require(
        "synthran_srsran_reference_deploy_with_check" in deploy_gnb,
        "physical retry lifecycle is no longer reference-owned",
    )
    for address in (
        "192.168.235.103",
        "192.168.235.104",
        "192.168.235.105",
        "192.168.235.106",
    ):
        require(
            address not in deploy_gnb,
            f"local deploy wrapper reintroduced address recovery: {address}",
        )

    config = text(CONFIG_MAIN)
    require(
        "synthran_topology.transport.workload_interfaces.ran.n3" in config,
        "srsRAN config no longer consumes #54 transport authority",
    )
    require(
        "synthran_ue_map" in config and "zmqTxPort" in config and "zmqRxPort" in config,
        "selected RFSIM UE mapping was lost",
    )
    require(
        'regexp: \'"name":\\s*"n3network"\'' not in config,
        "obsolete N3 template rewrite was reintroduced",
    )

    profile = text(APPLY_PROFILE)
    require(
        "remote_control.enabled = false" in profile,
        "remote-control hardening was lost",
    )
    require(
        "when: rru == 'rfsim'" in profile,
        "physical node placement is no longer exclusively reference-owned",
    )

    harden = text(HARDEN)
    require(
        "synthran_gnb_image_template_patch.changed" not in harden,
        "hardening again depends on a mutation occurring",
    )
    require(
        "synthran_log_sidecar_template_patch.changed" not in harden,
        "sidecar hardening again depends on a mutation occurring",
    )
    for needle in (
        "/var/log/gnb.log",
        "helm template",
        "lifecycle_reference_commit",
        "chart_revision",
        "@sha256:",
    ):
        require(
            needle in harden,
            f"runtime hardening/provenance lost contract surface: {needle}",
        )

    health = text(HEALTH)
    for marker in REFERENCE_FATAL_MARKERS + TIMING_FAILURE_MARKERS:
        require(
            marker in health,
            f"RAN-local health gate lost failure surface: {marker}",
        )
    for needle in (
        "/proc/[0-9]*/comm",
        "N2: Connection to AMF",
        "synthran_srsran_persistent_rf_failures",
        "srsran-ran-health.json",
    ):
        require(
            needle in health,
            f"RAN-local health gate lost evidence surface: {needle}",
        )
    require(
        health.count("seconds: 10") == 2,
        "RF-health persistence must be measured across two post-stability windows",
    )

    broker = text(START_BROKER)
    for needle in (
        "Require the gNB cell to activate",
        "Require the GNU Radio broker to start",
        "Require the gNB to establish NGAP with the AMF",
        "Require every configured UE to establish a PDU-session tunnel",
    ):
        require(
            needle in broker,
            f"RFSIM startup regressed to warning-only behavior: {needle}",
        )


def prepare_render_fixture(chart: Path) -> Path:
    deployment_path = chart / "charts/srsran-gnb/templates/deployment.yaml"
    deployment = harden_chart_template(text(deployment_path))
    require(
        hardened_template_valid(deployment),
        "cannot prepare render fixture from unexpected chart template",
    )
    deployment_path.write_text(deployment, encoding="utf-8")

    values_path = chart / "charts/srsran-gnb/values-n320-n78-20MHz.yaml"
    values = yaml.safe_load(values_path.read_text(encoding="utf-8"))
    values["image"]["repository"] = "r2labuser/srsran-gnb-uhd@sha256:" + "a" * 64
    values["image"]["tag"] = ""
    values["logSidecarImage"] = "busybox@sha256:" + "b" * 64
    values["gnbConfig"]["log"]["filename"] = "/var/log/gnb.log"
    values["gnbConfig"]["remote_control"]["enabled"] = False
    values["gnbConfig"]["remote_control"]["bind_addr"] = "127.0.0.1"
    fixture = chart / "synthran-values-n320.yaml"
    fixture.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    return fixture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--chart", type=Path)
    parser.add_argument(
        "--section",
        choices=("all", "reference", "chart", "local"),
        default="all",
    )
    parser.add_argument("--prepare-render-fixture", action="store_true")
    args = parser.parse_args()

    if args.prepare_render_fixture:
        require(args.chart is not None, "--prepare-render-fixture requires --chart")
        print(prepare_render_fixture(args.chart.resolve()))
        return

    if args.section in ("all", "reference"):
        require(args.reference is not None, "reference section requires --reference")
        check_reference(args.reference.resolve())
    if args.section in ("all", "chart"):
        require(args.chart is not None, "chart section requires --chart")
        check_chart(args.chart.resolve())
    if args.section in ("all", "local"):
        check_local()
    print(f"srsRAN Sub 07 contract OK ({args.section})")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"srsRAN Sub 07 contract failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
