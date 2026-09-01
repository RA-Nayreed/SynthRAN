# SynthRAN

SynthRAN models energy-aware ambient IoT devices deterministically, freezes the
energy-ready events into JSONL, and replays them as MQTT traffic through real 5G
UE interfaces. Simulated backscatter, protocol scheduling, collisions, SIC,
propagation, packet analysis, and capacitor/controller primitives remain
available under `synthran.model` for standalone studies.

Generate a headless model run:

```sh
python -m synthran.cli model run --config scenarios/reference.yml --output results/example/model
```

Replay its immutable trace through a UE tunnel:

```sh
synthran workload replay --trace results/example/model/events.jsonl \
  --broker 10.45.0.1 --interface uesimtun0 --start-utc 2026-09-01T12:00:00Z
```

Run the complete deployment workflow with `./deploy.sh --config
scenarios/reference.yml`. Operational failures stop deployment and retain the
run directory; delivery gaps are summarized as experiment results rather than
deployment failures.

The deployment matrix retains OAI, Open5GS, Free5GC, OAI RAN, srsRAN,
UERANSIM, RF simulation, and physical R2Lab adapters. Supported UE interfaces
are `uesimtun0`, `oaitun_*`, `tun_srsue*`, and physical `wwan0`; smartphones are
not supported.
