# SynthRAN

SynthRAN runs its native Ambient-IoT model deterministically, freezes decoded
packets into JSONL, and replays only those packets as MQTT traffic through real
5G UE interfaces. Scientific model primitives live in `synthran/model/`, while
configuration, protocols, evidence, and event bridging live in
`synthran/ambient_iot/`. The model originated from Amber; its provenance and
license are preserved under `third_party/amber/`.
Protocol examples are colocated at `synthran/ambient_iot/examples/`.

The primary interface is one interactive command. It prompts for the core, RAN,
platform, radio unit, currently available nodes, profile, UEs, POS reservation
duration, and node image; creates or reuses `.venv`;
generates the immutable energy-aware trace; deploys the network; maps devices to
UE tunnels; replays MQTT; and reconciles the JSONL artifacts:

```sh
./deploy.sh
```

For an Open5GS+srsRAN RFSIM deployment, device order maps explicitly to
`tun_srsue1` through `tun_srsueN` inside the srsUE pod. `deployment.ues` is the
source of truth: known devices use the selected 5G profile, while additional
names such as `uesim04` receive a deterministic IMSI and the profile's first
slice. A scenario can override either value under `deployment.ue_profiles`.
Missing model-device entries are materialized from the declared device templates
in UE order, and the explicit result is retained in `resolved-scenario.yml`.
A preparation-only run is available without deploying infrastructure:

```sh
./deploy.sh --dry-run
```

Use `--config scenarios/<name>.yml` for reproducible non-interactive execution,
or `--no-input` to run the default reference scenario without prompts. Use
`--no-reservation` only when the selected SOP nodes are already allocated,
imaged, booted, and reachable. A full deployment without SynthRAN reservation
evidence also requires the deliberate scenario setting
`deployment.allow_destructive_node_reset: true`; otherwise the Kubernetes/CNI/
containerd reset is refused before any destructive task runs.

A full deployment allocates the selected SOP nodes, selects the configured POS
image, and resets them into a known state even when an existing calendar event
is retained. Use `--workload-only` for repeated measurements without a reset.

After one healthy deployment, run additional immutable traces without rebuilding
the cluster or 5G stack:

```sh
./deploy.sh --config scenarios/rfsim-sidecars-3ue.yml --workload-only
```

If a full run reaches deployment attestation but fails during MQTT setup or
telemetry replay, resume that run without reserving, reimaging, or rebuilding
the nodes:

```sh
./deploy.sh --resume results/<failed-run-id>
```

Resume reuses the failed run's resolved scenario and exact generated trace. It
fails closed unless the source identity is intact, its attestation evidence is
present, and the same identity is still stored in the live Kubernetes cluster.

SynthRAN never rewrites the supplied scenario. Every run retains an immutable
`resolved-scenario.yml` containing reservation-time node choices and materialized
device settings.

After a successful full run, SynthRAN stores a versioned deployment identity in
both `.synthran/deployment-fingerprint.json` and the live Kubernetes cluster.
The identity covers the core, RAN, platform, node mapping, effective profile,
PLMN, slices, UE IMSIs, expected tunnels, and the asserted topology contract.
The workload-only path fails closed unless the requested identity matches both
records and the core/RAN nodes are Ready. Software UE replay additionally proves
each declared pod/interface, slice address, and—for srsUE—its generated IMSI and
DNN configuration, while rejecting unexpected stale UE tunnels. The evidence is
retained as `live-deployment-evidence.json` and included in `summary.json`.
Full deployment replaces only the selected Open5GS subscriber records, which
resets stale authentication state retained by MongoDB across repeat runs.
Open5GS WebUI and its administrator account are disabled by default because the
experiment loads subscribers directly; set
`deployment.open5gs_webui_enabled: true` only when interactive UI access is needed.

Ready-to-edit combinations for software-UE sidecars, physical QHAT/QFIT UEs,
N300/N320 and Benetel radios, network slices, and auxiliary R2Lab sensor, edge,
and USRP nodes are listed in [`scenarios/README.md`](scenarios/README.md).

Load any scenario as editable interactive defaults without modifying the source
file:

```sh
./deploy.sh --config scenarios/r2lab-n300-qhats-sdr.yml --interactive
```

Press Enter to retain a value or enter a replacement. The resolved selection is
saved as `interactive-scenario.yml` in the run directory.

Operational failures stop deployment and retain the run directory; delivery
gaps are summarized as experiment results rather than deployment failures.

The deployment matrix retains OAI, Open5GS, Free5GC, OAI RAN, srsRAN,
UERANSIM, RF simulation, and physical R2Lab adapters. Supported UE interfaces
are `uesimtun0`, per-pod OAI `oaitun_ue1`, `tun_srsue*`, and physical `wwan0`;
smartphones are not supported.

For software UEs, the workload role discovers the real tunnel inside running
UE pods and injects an isolated publisher container into the same network
namespace. This keeps MQTT replay independent of the selected core and dispatches
uniformly across OAI NR-UE, UERANSIM, and srsUE. Physical qhat/qfit publishers
run on their UE hosts and bind to `wwan0`.
