# SynthRAN

SynthRAN models energy-aware ambient IoT devices deterministically, freezes the
energy-ready events into JSONL, and replays them as MQTT traffic through real 5G
UE interfaces. Simulated backscatter, protocol scheduling, collisions, SIC,
propagation, packet analysis, and capacitor/controller primitives remain
available under `synthran.model` for standalone studies.

The primary interface is one interactive command. It prompts for the core, RAN,
platform, radio unit, nodes, profile, and UEs; creates or reuses `.venv`;
generates the immutable energy-aware trace; deploys the network; maps devices to
UE tunnels; replays MQTT; and reconciles the JSONL artifacts:

```sh
./deploy.sh
```

For an Open5GS+srsRAN RFSIM deployment, device order maps explicitly
to `tun_srsue1`, `tun_srsue2`, and `tun_srsue3` inside the srsUE pod. A preparation-only
run is available without deploying infrastructure:

```sh
./deploy.sh --dry-run
```

Use `--config scenarios/<name>.yml` for reproducible non-interactive execution,
or `--no-input` to run the default reference scenario without prompts.

Operational failures stop deployment and retain the run directory; delivery
gaps are summarized as experiment results rather than deployment failures.

The deployment matrix retains OAI, Open5GS, Free5GC, OAI RAN, srsRAN,
UERANSIM, RF simulation, and physical R2Lab adapters. Supported UE interfaces
are `uesimtun0`, `oaitun_*`, `tun_srsue*`, and physical `wwan0`; smartphones are
not supported.
