#!/usr/bin/env python3
"""Render the production RFSIM srsUE chart for one and multiple selected UEs."""
from __future__ import annotations

import argparse
import copy
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
PATCH_CHARTS = ROOT / "deployment/roles/5g/srsRAN/deploy/tasks/patch_charts.yml"
CONFIGMAP_TEMPLATE = (
    ROOT / "deployment/roles/5g/srsRAN/deploy/templates/srsue_configmap.yaml.j2"
)
IMAGE_SOURCE = 'image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"'
IMAGE_HARDENED = 'image: "{{ .Values.image.repository }}"'
DIGEST_RE = re.compile(r"^[A-Za-z0-9._/-]+@sha256:[0-9a-f]{64}$")


def fail(message: str) -> None:
    raise SystemExit(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def _task(tasks: list[dict], name: str) -> dict:
    for task in tasks:
        if task.get("name") == name:
            return task
    fail(f"production patch task not found: {name}")


def _render_production_templates(chart: Path, ue_count: int) -> None:
    tasks = yaml.safe_load(PATCH_CHARTS.read_text(encoding="utf-8"))
    environment = Environment(undefined=StrictUndefined, autoescape=False)
    context = {
        "srsran_network": {
            "n3": {
                "gnb_ip": "10.10.3.234",
                "ue_ips": ["10.10.3.235"],
            }
        },
        "ue_count": ue_count,
    }

    deployment_source = _task(tasks, "Rewrite srsue deployment.yaml")[
        "ansible.builtin.copy"
    ]["content"]
    deployment = environment.from_string(deployment_source).render(**context)
    require(
        deployment.count(IMAGE_SOURCE) == 1,
        "production RFSIM deployment template lost its single image patch site",
    )
    deployment = deployment.replace(IMAGE_SOURCE, IMAGE_HARDENED)
    require(
        deployment.count(IMAGE_HARDENED) == 1 and IMAGE_SOURCE not in deployment,
        "RFSIM UE image hardening did not produce one digest-ready image site",
    )
    (chart / "charts/srsue/templates/deployment.yaml").write_text(
        deployment + "\n", encoding="utf-8"
    )

    configmap = environment.from_string(
        CONFIGMAP_TEMPLATE.read_text(encoding="utf-8")
    ).render(**context)
    (chart / "charts/srsue/templates/configmap.yaml").write_text(
        configmap + "\n", encoding="utf-8"
    )

    files = chart / "charts/srsue/files"
    files.mkdir(parents=True, exist_ok=True)
    for name in ("start_gnu.sh", "multi_ue_scenario.py", "add_route.sh"):
        (files / name).write_text(f"# fixture for {name}\n", encoding="utf-8")


def _selected_ues(count: int) -> list[dict]:
    candidates = [
        {
            "imsi": "001010000000101",
            "k": "00112233445566778899aabbccddeeff",
            "opc": "ffeeddccbbaa99887766554433221100",
            "apn": "internet",
            "sst": "1",
            "sd": "",
            "ueIp": "10.10.3.235",
            "zmqTxPort": 2101,
            "zmqRxPort": 2100,
        },
        {
            "imsi": "001010000000202",
            "k": "10112233445566778899aabbccddeeff",
            "opc": "efeeddccbbaa99887766554433221100",
            "apn": "streaming",
            "sst": "1",
            "sd": "1048576",
            "ueIp": "10.10.3.235",
            "zmqTxPort": 2201,
            "zmqRxPort": 2200,
        },
        {
            "imsi": "001010000000303",
            "k": "20112233445566778899aabbccddeeff",
            "opc": "dfeeddccbbaa99887766554433221100",
            "apn": "telemetry",
            "sst": "2",
            "sd": "2",
            "ueIp": "10.10.3.235",
            "zmqTxPort": 2301,
            "zmqRxPort": 2300,
        },
    ]
    require(count in (1, 3), f"unsupported fixture UE count: {count}")
    return candidates[:count]


def _render_case(chart_source: Path, image: str, count: int) -> None:
    require(DIGEST_RE.fullmatch(image) is not None, f"invalid immutable UE image: {image}")
    with tempfile.TemporaryDirectory(prefix=f"srsran-rfsim-{count}-") as temporary:
        chart = Path(temporary) / "chart"
        shutil.copytree(chart_source, chart)
        _render_production_templates(chart, count)

        values_path = chart / "charts/srsue/values.yaml"
        values = yaml.safe_load(values_path.read_text(encoding="utf-8"))
        mutable_image = f"{values['image']['repository']}:{values['image']['tag']}"
        values = copy.deepcopy(values)
        values["image"]["repository"] = image
        values["image"]["tag"] = ""
        values.update(
            {
                "gnbIp": "10.10.3.234",
                "ueIp": "10.10.3.235",
                "n3networkName": "n3network",
                "nodeName": "ran-ci",
                "nodeSelector": {"kubernetes.io/hostname": "ran-ci"},
                "ueCount": count,
                "ues": _selected_ues(count),
            }
        )
        fixture = chart / f"values-rfsim-{count}.yaml"
        fixture.write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")

        result = subprocess.run(
            [
                "helm",
                "template",
                f"synthran-srsue-{count}",
                str(chart / "charts/srsue"),
                "--namespace",
                "open5gs",
                "-f",
                str(fixture),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        rendered = result.stdout
        require(image in rendered, f"{count}-UE render lost immutable srsUE image")
        require(mutable_image not in rendered, f"{count}-UE render retained mutable srsUE tag")
        require('value: "n3network"' not in rendered, "unexpected quoted N3 fixture sentinel")
        require("n3network" in rendered, f"{count}-UE render lost selected N3 attachment")
        require(f'value: "{count}"' in rendered, f"{count}-UE render lost UE_COUNT")

        selected = _selected_ues(count)
        for ue in selected:
            for expected in (
                ue["imsi"],
                ue["apn"],
                str(ue["sst"]),
                str(ue["zmqTxPort"]),
                str(ue["zmqRxPort"]),
            ):
                require(expected in rendered, f"{count}-UE render lost selected value: {expected}")
            if ue["sd"]:
                require(str(ue["sd"]) in rendered, f"{count}-UE render lost selected SD")

        require(
            rendered.count('"imsi":') == count,
            f"{count}-UE render produced the wrong number of UE identities",
        )
        if count == 1:
            require(
                "001010000000202" not in rendered and "2201" not in rendered,
                "one-UE render leaked an unselected UE",
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chart", required=True, type=Path)
    parser.add_argument("--ue-image", required=True)
    args = parser.parse_args()
    chart = args.chart.resolve()
    require((chart / "charts/srsue/Chart.yaml").is_file(), f"invalid chart checkout: {chart}")
    _render_case(chart, args.ue_image.strip(), 1)
    _render_case(chart, args.ue_image.strip(), 3)
    print("srsRAN RFSIM one/multi-UE render contract OK")


if __name__ == "__main__":
    main()
