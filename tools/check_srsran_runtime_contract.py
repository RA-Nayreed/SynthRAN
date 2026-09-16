#!/usr/bin/env python3
"""Validate Sub 07 runtime-image, log, N2, and RFSIM ownership invariants."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_MAIN = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/main.yml"
RFSIM_HARDEN = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/harden_rfsim_ue_runtime.yml"
VERIFY_LOGGING = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/verify_logging.yml"
HEALTH = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/verify_ran_health.yml"
IMAGE_DIGEST = ROOT / "synthran/image_digest.py"
RFSIM_RENDER = ROOT / "tools/check_srsran_rfsim_render.py"
CHART_DEFAULTS = ROOT / "deployment/roles/5g/srsRAN/common/defaults/main.yml"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def text(path: Path) -> str:
    require(path.is_file(), f"missing required file: {path}")
    return path.read_text(encoding="utf-8")


def main() -> None:
    deploy = text(DEPLOY_MAIN)
    harden_marker = "harden_rfsim_ue_runtime.yml"
    reference_marker = "synthran_srsran_reference_deploy_srsues"
    require(harden_marker in deploy, "RFSIM UE image hardening is no longer invoked")
    require(reference_marker in deploy, "reference-owned RFSIM UE lifecycle is no longer invoked")
    require(
        deploy.index(harden_marker) < deploy.index(reference_marker),
        "RFSIM UE image/render hardening must occur before reference-owned UE deployment",
    )

    rfsim = text(RFSIM_HARDEN)
    for needle in (
        "synthran.image_digest",
        "synthran_srsue_image_reference",
        ".image.repository = strenv(SYNTHRAN_SRSUE_IMAGE)",
        '.image.tag = ""',
        "helm template synthran-srsue",
        "srsran-rfsim-ue-runtime.json",
        "selected_ues",
        "@sha256:",
    ):
        require(needle in rfsim, f"RFSIM immutable-image contract lost: {needle}")
    require(
        "synthran_srsue_runtime_policy.ues | length == ue_count | int" in rfsim,
        "RFSIM hardening no longer verifies selected-UE cardinality",
    )

    logging = text(VERIFY_LOGGING)
    for needle in (
        "/proc/[0-9]*/comm",
        "/usr/local/bin/gnb",
        "/srsran/config/srsran-gnb.yaml",
        "/var/log/gnb.log",
        "synthran_gnb_logging_config",
        "synthran_gnb_logging_cmdline",
    ):
        require(needle in logging, f"live log-ownership proof lost: {needle}")
    require(
        "filename:[[:space:]]*/var/log/gnb\\.log" in logging,
        "live mounted gNB config is no longer checked for the authoritative log path",
    )

    health = text(HEALTH)
    for needle in (
        "ss -H -n -A sctp state established",
        "synthran_srsran_live_n2",
        "imageID",
        "synthran_srsran_live_image_digest",
        "synthran_srsran_expected_image_digest",
        "configured_image_digest",
        "live_image_digest",
        "synthran_gnb_logging_pod",
        "synthran_gnb_logging_config",
        "synthran_gnb_logging_cmdline",
    ):
        require(needle in health, f"physical live-state evidence lost: {needle}")
    require(
        "synthran_srsran_live_image_digest == synthran_srsran_expected_image_digest" in health,
        "physical acceptance no longer compares configured and live image digests",
    )
    require(
        "synthran_srsran_live_n2.rc == 0" in health,
        "physical acceptance no longer requires live N2 SCTP state",
    )

    resolver = text(IMAGE_DIGEST)
    for needle in (
        "resolve_public_image",
        '"ghcr.io"',
        "_SUPPORTED_REGISTRIES",
        "WWW-Authenticate",
        "Docker-Content-Digest",
        "_SUPPORTED_AUTH_HOSTS",
    ):
        require(needle in resolver, f"public OCI resolver lost constrained behavior: {needle}")
    require(
        'if "." in first or ":" in first or first == "localhost"' in resolver,
        "public OCI resolver no longer rejects unapproved registry-like hosts",
    )

    render = text(RFSIM_RENDER)
    for needle in (
        "PATCH_CHARTS",
        "CONFIGMAP_TEMPLATE",
        '"helm"',
        '"template"',
        "_render_case(chart, args.ue_image.strip(), 1)",
        "_render_case(chart, args.ue_image.strip(), 3)",
        "zmqTxPort",
        "zmqRxPort",
        "imsi",
        "apn",
    ):
        require(needle in render, f"RFSIM rendered-fixture coverage lost: {needle}")

    defaults = yaml.safe_load(text(CHART_DEFAULTS))
    version = str(defaults.get("version", ""))
    require(
        len(version) == 40 and all(character in "0123456789abcdef" for character in version.lower()),
        "srsRAN downstream chart pin is no longer immutable",
    )

    print("srsRAN Sub 07 runtime contract OK")


if __name__ == "__main__":
    main()
