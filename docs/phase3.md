# Integrated IoT-to-5G Workflow

Phase 3 consumes an already `path-proven` Open5GS + srsRAN + RFSIM network and exercises the deterministic IoT-to-dataset path without reserving resources or redeploying the base network.

## Golden path

```text
10 deterministic Contiki-NG/Cooja sensors
-> RPL/6LoWPAN
-> Cooja border router + Serial Socket
-> tunslip6 / tun0 (fd00::1/64)
-> counted controller ingress
-> run-owned Mosquitto sidecar in the srsUE pod network namespace
-> bridge bound to the accepted UE PDU address on tun_srsue1
-> srsRAN gNB
-> Open5GS UPF
-> run-owned host-network Mosquitto broker on the core node
-> central collector
-> append-only JSONL
-> deterministic Parquet
-> Phase 3 evidence
```

The controller-side ingress is deliberately a TCP adapter, not the 5G bridge. The real edge Mosquitto bridge is injected as a temporary sidecar into the existing run-owned srsUE Deployment so it shares the network namespace that contains `tun_srsue1`. SynthRAN installs a run-specific route for the central broker through `tun_srsue1`, restarts only the MQTT sidecar after that route exists, and requires the tunnel byte counter to increase while the central collector receives the ten sensor streams.

## Deterministic scenario

The first supported scenario is fixed to:

- ten Cooja sensor motes, IDs 1 through 10;
- one Cooja RPL border router with a non-sensor mote ID;
- fixed UDGM geometry and success ratios;
- Cooja seed `424242`;
- Serial Socket port `60001`;
- `fd00::/64` RPL prefix and `fd00::1` host-side `tun0` address;
- one telemetry publish every 10 seconds per sensor;
- topics below `synthran/<run-id>/sensor/`;
- at least three contiguous events from every sensor for default acceptance.

Each sensor publishes `synthran/telemetry/v1alpha1` JSON containing the run ID, deterministic `sensor-01` through `sensor-10` identity, a positive sequence number, sensor time, and deterministic integer measurement.

## Safety boundary

The run command does not create a reservation, allocate or image nodes, deploy Open5GS, deploy the gNB, or tear down the accepted network. It requires the referenced network manifest to have `status=path-proven` and the referenced network evidence to have `ready=true` before it creates the experiment run directory.

Live Phase 3 changes are limited to:

- run-labeled MQTT ConfigMaps and a central MQTT Deployment;
- one temporary MQTT sidecar and config volume on the run-owned srsUE Deployment;
- one temporary host route inside that pod network namespace;
- local Cooja, `tunslip6`, SSH/kubectl port-forward, and ingress-proxy processes.

Cleanup removes exact run-labeled resources, removes the sidecar by strategic patch, waits for the srsUE Deployment to recover, and reproves the accepted network path. A cleanup failure prevents an `IOT-TO-5G PATH PROVEN` result.

## Operator commands

Activate the repository environment and load the private authority file created by the accepted network preparation so strict SSH host-key verification is configured.

```bash
conda activate synthran
source .synthran/preparations/<network-run-id>/authority.env
```

Preview the deterministic scenario without changing live state:

```bash
synthran-phase3 plan \
  --network-run-id <path-proven-network-run-id> \
  --run-id <experiment-run-id>
```

Execute the complete integrated experiment:

```bash
synthran-phase3 run \
  --inventory .synthran/preparations/<network-run-id>/hosts.ini \
  --network-run-id <path-proven-network-run-id> \
  --run-id <experiment-run-id>
```

The default collector allows 180 seconds and requires at least three contiguous events from every sensor. Those controls can be changed explicitly with `--collection-seconds` and `--minimum-per-sensor` without changing the fixed ten-sensor topology.

Render persisted acceptance evidence without touching live state:

```bash
synthran-phase3 verify --run-id <experiment-run-id>
```

## Acceptance checks

A successful run records checks for:

- deterministic Cooja startup and Serial Socket availability;
- RPL border-router attachment through `tunslip6/tun0`;
- sensor MQTT connections crossing the counted `tun0` ingress;
- edge bridge configuration bound to the accepted UE PDU address;
- `tun_srsue1` transmit-counter growth during telemetry delivery;
- the accepted slice-one UPF route remaining path-proven;
- receipt of all ten deterministic streams by the central broker/collector;
- complete ten-sensor coverage;
- no duplicate or missing sequence numbers in the accepted collection window;
- valid append-only JSONL;
- deterministic derived Parquet;
- exact-run cleanup and successful reproof of the base network.

Only when every check passes does the experiment manifest use `status=iot-to-5g-path-proven` and the evidence report end with:

```text
Result: IOT-TO-5G PATH PROVEN
```

A deployment or collection failure must remain `failed` or `completed-unverified`; it must never be promoted merely because Cooja, Kubernetes pods, or brokers were Running.

## Artifacts

Ignored run artifacts live below `.synthran/experiments/<run-id>/`:

- `manifest.json`: run lifecycle and base-network reference;
- `scenario.json`: deterministic run input;
- `cooja/phase3.csc`: generated simulator scenario;
- `sensor/phase3-generated.h`: generated firmware constants;
- `telemetry.jsonl`: canonical append-only audit record;
- `rejected-events.jsonl`: validation failures without raw payload copies, when present;
- `telemetry.parquet`: deterministic derived table;
- `phase3-evidence.json`: sanitized acceptance evidence;
- `logs/`: local process logs kept out of Git.

Raw packet captures are not required for the default acceptance contract. Route proof, tunnel counters, broker receipt, sequence integrity, and the already accepted UPF path provide the default evidence without introducing capture-data privacy risk.
