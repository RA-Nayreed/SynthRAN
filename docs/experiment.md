# Integrated IoT-to-5G Experiment

The experiment consumes an already `path-proven` Open5GS + srsRAN + RFSIM network and exercises the deterministic IoT-to-dataset path without reserving resources or redeploying the base network.

## Golden path

```text
10 deterministic Contiki-NG/Cooja sensors on Duckburg
-> RPL/6LoWPAN
-> Cooja border router + Serial Socket (127.0.0.1:60001)
-> loopback-only reverse SSH tunnel (-R 127.0.0.1:60001:127.0.0.1:60001)
-> root tunslip6 / tun0 (fd00::1/64) on core node
-> counted TCP ingress on core node
-> run-owned Mosquitto sidecar in the srsUE pod network namespace
-> bridge bound to live UE PDU address on tun_srsue1
-> srsRAN gNB
-> Open5GS UPF
-> run-owned host-network Mosquitto broker on the core node
-> central collector
-> append-only JSONL
-> deterministic Parquet
-> experiment evidence
```

The TCP ingress is an adapter, not the cellular bridge. The edge Mosquitto bridge is injected temporarily into the existing run-owned srsUE Deployment so it shares the network namespace containing `tun_srsue1`. SynthRAN discovers the live UE PDU address after srsUE rollout, installs a route for the central broker through `tun_srsue1`, restarts only the MQTT sidecar after that route exists, and requires the tunnel byte counter to increase while the central collector receives all ten sensor streams.

Privileged TUN operations (`tunslip6` and `tun0` at `fd00::1/64`) and TCP ingress run exclusively on the root core node (`inventory.core_node`), eliminating any requirement for `sudo` on the Duckburg controller. Duckburg connects Cooja to `tunslip6` via a strict loopback-only reverse SSH tunnel.

## Deterministic scenario

The supported scenario is fixed to:

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

The experiment command does not create a reservation, allocate or image nodes, deploy Open5GS, deploy the gNB, or tear down the accepted network. It requires the referenced network manifest to have `status=path-proven` and the referenced network evidence to have `ready=true` before creating the experiment run directory.

Local Cooja runtime prerequisites are strictly validated before any live cluster or 5G mutations occur:
- Java 21 (`openjdk=21.0.9`) must be present in the active `synthran` Conda environment;
- the pinned Contiki-NG checkout is validated;
- the deterministic MQTT sensor includes `project-conf.h` enabling Contiki TCP socket support (`#define UIP_CONF_TCP 1`);
- sensor compilation commands in generated Cooja scenarios explicitly embed the validated absolute Contiki checkout path (`CONTIKI=<path>`) rather than relying on unexpanded `[CONTIKI_DIR]` placeholders or ambient parent environment variables;
- child processes (`cooja`, SSH port-forwards) are actively monitored during readiness checks so early process exits fail immediately with the exit code and log file path instead of waiting for TCP socket timeouts.

Before live mutation, SynthRAN inspects the root core node and performs guarded preflight checks:
- automatically reclaims only provably stale/orphaned processes (PPID 1 or child of matching PPID 1 wrapper) matching exact SynthRAN runtime signatures (edge port-forward `18883:1883`, central port-forward `18885:18884`, `ingress.py`, and `tunslip6`), while active, foreign, or ambiguous ownership remains strictly fail-closed;
- verifies required tools (`ifconfig` from package `net-tools`, `gcc`, `make`, `python3`, `ip`, `tar`), root privileges, `/dev/net/tun`, absence of pre-existing `tun0`, and availability of reserved remote ports `60001`, `18883`, and `18885`;
- validates SSH daemon configuration (`sshd -T`) to require `AllowTcpForwarding` (`yes` or `all`).

Network verification explicitly addresses the `ue` container (`kubectl exec ... -c ue -- ...`) when probing `tun_srsue1` and UE routing tables. The live UE PDU address is discovered dynamically from `tun_srsue1` after srsUE rollout and is never assumed from historical evidence.

Live experiment changes are limited to:

- run-labeled MQTT ConfigMaps and a central MQTT Deployment;
- one temporary MQTT sidecar and config volume on the run-owned srsUE Deployment;
- one temporary host route inside that pod network namespace;
- on the Duckburg controller: local Cooja simulation, reverse/forward SSH tunnel processes, and central collector client;
- on the root core node: remote `tunslip6`, `tun0`, `CountedTcpIngress`, remote kubectl edge port-forward, and an isolated run-scoped workspace (`/tmp/synthran/<run-id>/`).

Cleanup targets only resources proven to belong to the requested run:
- terminates run-owned local and remote process groups;
- explicitly terminates exact run-scoped remote processes (matching run workspace, UE pod, and central deployment) before filesystem or network deletions;
- deletes the run-created/partially-created `tun0` interface on the core node and verifies its absence postcondition;
- removes the isolated run-scoped workspace `/tmp/synthran/<run-id>/` on the core node and verifies its absence postcondition;
- verifies host runtime postconditions (reserved ports `60001`, `18883`, and `18885` free, `tun0` absent, workspace absent);
- removes the temporary UE sidecar and config volume by strategic patch;
- removes run-labeled central broker and ConfigMap objects;
- waits for the srsUE Deployment to recover and reconciles RFSIM runtime if needed;
- reproves the accepted base network.

A cleanup, host postcondition, or network-reproof failure prevents an `IOT-TO-5G PATH PROVEN` result.

## Current status and live acceptance

The integrated deterministic IoT-to-5G experiment is live-accepted. The canonical accepted evidence pair on SLICES is:

- **Base network:** `network-acceptance-20260817-04` (`Result: PATH PROVEN`)
- **Integrated experiment:** `iot-acceptance-20260817-06` (`Result: IOT-TO-5G PATH PROVEN`)

Key facts proven live on 2026-08-17:
- **Pre-run stale runtime recovery:** 4 stale SynthRAN processes from previous runs were automatically reclaimed on the core node before mutation, requiring zero manual PID cleanup.
- **Dynamic PDU rediscovery:** The srsUE rollout dynamically discovered live PDU address `12.1.0.8` on `tun_srsue1` (distinct from the accepted baseline address `12.1.0.3`) and bound the edge bridge to the live address.
- **Deterministic collection:** All 10/10 sensors published successfully, yielding 30 canonical JSONL records (minimum 3 per sensor) and derived Parquet.
- **Cleanup and network reproof:** Exact run processes were reaped, `tun0` and the remote workspace were removed, and the base network was reproven (`[PASS] cleanup-base-network`).
- **Independent post-run audit:** Out-of-band inspection of `sopnode-f2` confirmed all postconditions: reserved ports `60001`, `18883`, and `18885` had no listeners; `tun0` was absent; `/tmp/synthran/iot-acceptance-20260817-06` was absent.

Historical context: earlier attempts `iot-acceptance-20260817-02` through `-05` served as engineering provenance for missing host `net-tools`/`ifconfig` (-02), stale edge port-forward (-03), dynamic PDU proof followed by stale central port-forward (-04), and Paho v2 ReasonCode evaluation / remote process persistence (-05), which were resolved in commit `0f0d2d2`.

## Operator commands

Activate the repository environment and load the private authority file created by the accepted network preparation so strict SSH host-key verification is configured.

```bash
conda activate synthran
source .synthran/preparations/<network-run-id>/authority.env
```

Preview the deterministic scenario without changing live state:

```bash
synthran experiment plan \
  --network-run-id <path-proven-network-run-id> \
  --run-id <experiment-run-id>
```

Execute the integrated experiment:

```bash
synthran experiment run \
  --inventory .synthran/preparations/<network-run-id>/hosts.ini \
  --network-run-id <path-proven-network-run-id> \
  --run-id <experiment-run-id>
```

The default collector allows 180 seconds and requires at least three contiguous events from every sensor. Those controls can be changed explicitly with `--collection-seconds` and `--minimum-per-sensor` without changing the fixed ten-sensor topology.

Render persisted acceptance evidence without touching live state:

```bash
synthran experiment verify --run-id <experiment-run-id>
```

## Acceptance checks

A successful run records checks for:

- deterministic Cooja startup and Serial Socket availability;
- RPL border-router attachment through `tunslip6/tun0`;
- sensor MQTT connections crossing the counted `tun0` ingress;
- edge bridge configuration bound to the live dynamically discovered UE PDU address on `tun_srsue1`;
- `tun_srsue1` transmit-counter growth during telemetry delivery;
- the accepted slice-one UPF route remaining path-proven;
- receipt of all ten deterministic streams by the central broker and collector;
- complete ten-sensor coverage;
- no duplicate or missing sequence numbers in the accepted collection window;
- valid append-only JSONL;
- deterministic derived Parquet;
- exact-run remote and Kubernetes cleanup with verified absence postconditions and successful reproof of the base network.

Only when every check passes does the experiment manifest use `status=iot-to-5g-path-proven` and the evidence report end with:

```text
Result: IOT-TO-5G PATH PROVEN
```

A deployment or collection failure remains `failed` or `completed-unverified`; it is never promoted merely because Cooja, Kubernetes pods, or brokers are Running.

## Artifacts

Ignored run artifacts live below `.synthran/experiments/<run-id>/`:

- `manifest.json`: run lifecycle and base-network reference;
- `scenario.json`: deterministic run input;
- `cooja/experiment.csc`: generated simulator scenario;
- `sensor/experiment-generated.h`: generated firmware constants;
- `telemetry.jsonl`: canonical append-only audit record;
- `rejected-events.jsonl`: validation failures without raw payload copies, when present;
- `telemetry.parquet`: deterministic derived table;
- `experiment-evidence.json`: sanitized acceptance evidence;
- `logs/`: local process logs kept out of Git.

Raw packet captures are not required for the default acceptance contract. Route proof, tunnel counters, broker receipt, sequence integrity, and the already accepted UPF path provide the default evidence without introducing capture-data privacy risk.
