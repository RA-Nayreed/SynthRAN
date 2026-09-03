from __future__ import annotations
import json
from pathlib import Path
import yaml
from synthran.amber import AmberRunner
from synthran.amber.evidence import write as write_amber_evidence
from synthran.scenario import load_scenario, redacted

def generate(config: str | Path, output: str | Path) -> Path:
    scenario = load_scenario(config); destination = Path(output); destination.mkdir(parents=True, exist_ok=True)
    result = AmberRunner(scenario).run()
    (destination / "resolved-scenario.yml").write_text(yaml.safe_dump(redacted(scenario), sort_keys=False), encoding="utf-8")
    bridge = write_amber_evidence(result, scenario, destination)
    with (destination / "events.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in bridge["events"]: stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    with (destination / "suppressed.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in bridge["suppressed"]: stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return destination / "events.jsonl"
