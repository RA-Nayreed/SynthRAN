#!/usr/bin/env python3
"""Static contract for issue #55: OAI R2Lab N320 adaptation ownership."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

DEFAULTS = ROOT / "deployment/roles/5g/oai/common/defaults/main.yml"
SETUP = ROOT / "deployment/roles/5g/oai/setup/tasks/main.yml"
N320_SOURCE = ROOT / "deployment/roles/5g/oai/setup/tasks/r2lab_n320.yml"
RAN = ROOT / "deployment/roles/5g/oai/ran/tasks/main.yml"
N320_CHART = ROOT / "deployment/roles/5g/oai/ran/tasks/r2lab_n320_chart.yml"
N320_ATTEST = ROOT / "deployment/roles/5g/oai/ran/tasks/r2lab_n320_attest.yml"
N320_NAD = ROOT / "deployment/roles/5g/oai/ran/files/r2lab_n320_ipvlan_nad.yaml"
LEGACY_SWAP = ROOT / "deployment/roles/5g/oai/ran/n3xx_ip_swap"


def fail(message: str) -> None:
    raise SystemExit(message)


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require(haystack: str, needle: str, context: str) -> None:
    if needle not in haystack:
        fail(f"{context}: missing required contract text: {needle!r}")


def forbid(haystack: str, needle: str, context: str) -> None:
    if needle in haystack:
        fail(f"{context}: forbidden contract text remains: {needle!r}")


def helper_pin(defaults: str) -> str:
    match = re.search(r'^tag_oai5g_rru:\s*["\']([0-9a-fA-F]{40})["\']\s*$', defaults, re.M)
    if not match:
        fail("OAI defaults: immutable 40-hex tag_oai5g_rru pin is missing")
    return match.group(1).lower()


def git_head(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
        ).strip().lower()
    except (OSError, subprocess.CalledProcessError) as error:
        fail(f"cannot read helper Git revision at {path}: {error}")


def shell_function(script: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(name)}\(\)\s*\{{\s*$(.*?)^\}}\s*$",
        script,
    )
    if not match:
        fail(f"pinned helper: cannot locate shell function {name}()")
    return match.group(1)


def validate_helper(helper: Path, pin: str) -> None:
    if git_head(helper) != pin:
        fail(f"pinned helper drift: expected {pin}, found {git_head(helper)}")

    n320_env = text(helper / "rru/n320.env")
    require(n320_env, 'IP_GNB_RU="dhcp"', "pinned helper n320.env")
    require(n320_env, 'MTU_GNB_RU="9000"', "pinned helper n320.env")
    require(
        n320_env,
        "mgmt_addr=192.168.235.106,addr=192.168.235.106",
        "pinned helper n320.env",
    )

    for relative in (
        "demo_charts/templates/oai-gnb/nad.yaml",
        "demo_charts/templates/oai-du/nad.yaml",
    ):
        nad = text(helper / relative)
        require(nad, 'eq .type "macvlan"', f"pinned helper {relative}")
        require(nad, 'eq .type "vlan"', f"pinned helper {relative}")
        forbid(nad, 'eq .type "ipvlan"', f"pinned helper {relative}")

    prepare = text(helper / "testing/prepare-demo-oai.sh")
    require(
        prepare,
        "elif [[ \"$action\" = 'configure' ]]; then\n    configure_all_scripts",
        "pinned helper prepare-demo-oai.sh",
    )

    launch = shell_function(text(helper / "demo-oai.sh"), "start-gnb")
    require(launch, "helm -n $NS install oai-gnb", "pinned helper start-gnb")
    require(launch, "kubectl -n $NS wait pod", "pinned helper start-gnb")
    forbid(launch, "set -e", "pinned helper start-gnb")


def validate_local_contract(pin: str) -> None:
    defaults = text(DEFAULTS)
    setup = text(SETUP)
    source = text(N320_SOURCE)
    ran = text(RAN)
    chart = text(N320_CHART)
    attest = text(N320_ATTEST)
    nad = text(N320_NAD)

    expected_defaults = {
        'oai_r2lab_n320_ru_parent: "r2lab_usrp"',
        'oai_r2lab_n320_ru_ip: "192.168.235.120"',
        'oai_r2lab_n320_ru_prefix: "24"',
        'oai_r2lab_n320_ru_mtu: "9216"',
        'oai_r2lab_n320_sdr_ip: "192.168.235.105"',
        'oai_r2lab_n320_ru_cni_type: "ipvlan"',
        'oai_r2lab_n320_ru_cni_mode: "l2"',
    }
    for needle in expected_defaults:
        require(defaults, needle, "OAI defaults")
    if helper_pin(defaults) != pin:
        fail("OAI defaults helper pin changed during validation")

    require(setup, "ansible.builtin.include_tasks: r2lab_n320.yml", "OAI setup")
    for gate in (
        "platform == 'r2lab'",
        "ran == 'oai'",
        "rru == 'n320'",
    ):
        require(setup, gate, "OAI setup N320 gate")

    for needle in (
        "IF_NAME_GNB_RU=",
        "IP_GNB_RU=",
        "MTU_GNB_RU=",
        "mgmt_addr={{ oai_r2lab_n320_sdr_ip }},addr={{ oai_r2lab_n320_sdr_ip }}",
        "oai-du-cucpup.yaml",
        "oai-du.yaml",
        "oai-gnb.yaml",
    ):
        require(source, needle, "N320 source adapter")
    forbid(source, "n300", "N320 source adapter")

    require(chart, "r2lab_n320_ipvlan_nad.yaml", "N320 chart adapter")
    require(chart, "helm template", "N320 chart adapter")
    require(chart, "test \"$count\" -eq 1", "N320 chart adapter")
    forbid(chart, "kubectl apply", "N320 chart adapter")
    require(nad, 'eq .type "ipvlan"', "N320 Helm NAD")
    forbid(nad, "macvlan", "N320 Helm NAD")
    forbid(nad, "vlanId", "N320 Helm NAD")

    for needle in (
        "oai_expected_ran_releases",
        "Prove the R2Lab N320 Helm lifecycle starts clean",
        "Reject explicit Helm installation failures",
        "'INSTALLATION FAILED'",
        "platform == 'r2lab' and",
        "rru == 'n320' and",
        "oai_start_wait_timeout | bool",
        "Verify N3xx gNB RF-device readiness",
        "r2lab_n320_attest.yml",
    ):
        require(ran, needle, "OAI RAN lifecycle")
    require(
        ran,
        "A nonzero result is tolerated only for the\n      evidence-backed R2Lab N320 readiness timeout",
        "OAI RAN lifecycle",
    )

    for needle in (
        "time.sleep(10)",
        "pod identity changed during stability window",
        "restart counters changed during stability window",
        "N320 radio container restarted during startup",
        "RU [0-9]+ rf device ready",
        "Received NGSetupResponse from AMF",
        "sha256:",
        "helper_revision': tag_oai5g_rru",
        "charts_revision': synthran_oai_charts_revision",
        "selected_transport': synthran_topology.transport",
        "selected_network': synthran_topology.network",
    ):
        require(attest, needle, "N320 runtime attestation")

    if LEGACY_SWAP.exists():
        fail("legacy generic n3xx_ip_swap role must not exist on the #55 branch")
    oai_tree = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (ROOT / "deployment/roles/5g/oai").rglob("*")
        if path.is_file()
    )
    forbid(oai_tree, "n3xx_ip_swap", "OAI role tree")
    forbid(oai_tree, "deploy_nr_ue", "OAI role tree")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--helper",
        type=Path,
        required=True,
        help="Exact checkout of the pinned sopnode/oai5g-rru helper",
    )
    args = parser.parse_args()

    defaults = text(DEFAULTS)
    pin = helper_pin(defaults)
    validate_helper(args.helper.resolve(), pin)
    validate_local_contract(pin)
    print(f"OAI N320 contract OK: helper={pin}")


if __name__ == "__main__":
    main()
