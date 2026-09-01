from __future__ import annotations
import csv, json
from pathlib import Path
import yaml
from synthran.model import EnergyWorkloadModel
from synthran.scenario import load_scenario, redacted

def generate(config: str | Path, output: str | Path) -> Path:
    scenario = load_scenario(config); destination = Path(output); destination.mkdir(parents=True, exist_ok=True)
    result = EnergyWorkloadModel(scenario).run()
    (destination / "resolved-scenario.yml").write_text(yaml.safe_dump(redacted(scenario), sort_keys=False), encoding="utf-8")
    for name in ("events", "suppressed", "transitions"):
        with (destination / f"{name}.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for row in result[name]: stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    for device, rows in result["histories"].items():
        with (destination / f"energy-{device}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    return destination / "events.jsonl"
