#!/usr/bin/env python3
"""Build the fixed RFSIM transport scenario for Experiment 2.

The immutable workload is independent of the selected 5G core.  Experiment 2
uses the previously qualified OAI+srsRAN multi-UE/slice path for RFSIM so that
its software transport baseline matches the intended OAI+srsRAN physical path.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


DEFAULT_PILOT = Path("results/exp2-matched-trace/pilot-seed1001")


def prepare(pilot_root: Path, output: Path) -> Path:
    source = pilot_root / "native" / "model" / "resolved-scenario.yml"
    if not source.is_file():
        raise SystemExit(f"Native pilot scenario not found: {source}")
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing transport scenario: {output}")

    scenario = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(scenario, dict) or not isinstance(scenario.get("deployment"), dict):
        raise SystemExit(f"Invalid source scenario: {source}")

    deployment = scenario["deployment"]
    if deployment.get("platform") != "rfsim" or str(deployment.get("ran", "")).lower() != "srsran":
        raise SystemExit(
            "Experiment-2 pilot source must already use platform=rfsim and ran=srsran"
        )

    # Freeze the transport implementation, without altering any modeled sensor,
    # sensor->gateway, workload, MQTT, or measurement setting.
    deployment["core"] = "oai"
    deployment["ran"] = "srsran"
    deployment["platform"] = "rfsim"
    deployment["nodes"] = {
        "core": "sopnode-f2",
        "ran": "sopnode-f3",
        "broker": "sopnode-f2",
    }
    deployment["profile"] = "default"

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(scenario, sort_keys=False), encoding="utf-8")
    print(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-root", type=Path, default=DEFAULT_PILOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_PILOT / "rfsim-oai-srsran.yml",
    )
    args = parser.parse_args()
    prepare(args.pilot_root, args.output)


if __name__ == "__main__":
    main()
