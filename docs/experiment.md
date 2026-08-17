# Integrated IoT-to-5G Experiment and Controlled Research

SynthRAN provides two connected experiment layers:

1. **Integrated IoT-to-5G experiment:** deterministic end-to-end telemetry transport over the accepted 5G substrate.
2. **Controlled research experiments:** fixed-window measurements with continuous RTT probing, synchronized network sampling, and optional calibrated UDP background load.

Both consume an already `path-proven` Open5GS + srsRAN + RFSIM base network. Experiment commands do not reserve resources or redeploy that network.

## 1. Integrated IoT-to-5G golden path

```text
10 deterministic Contiki-NG/Cooja sensors
-> RPL/6LoWPAN
-> Cooja border router + loopback Serial Socket
-> loopback-only reverse SSH tunnel
-> root tunslip6 / tun0 on core node
-> counted TCP ingress
-> run-owned Mosquitto sidecar in srsUE namespace
-> bridge bound to live UE PDU on tun_srsue1
-> srsRAN gNB
-> Open5GS UPF
-> run-owned central Mosquitto
-> collector
-> canonical JSONL
-> deterministic Parquet
-> experiment evidence
```

The counted TCP ingress is an integration adapter, not the cellular proof boundary. The edge Mosquitto bridge runs inside the srsUE pod network namespace because that is where `tun_srsue1` and the live PDU address exist.

SynthRAN rediscovers the live PDU after srsUE/RFSIM reconciliation, installs the exact temporary broker route through `tun_srsue1`, and requires cellular-path evidence plus broker receipt and sequence integrity before acceptance.

Privileged `tunslip6/tun0` operations are isolated to the root core node. The controller does not require local `sudo` for the accepted workflow.

### Deterministic scenario

The accepted base scenario uses:

- ten sensor motes with stable `sensor-01` through `sensor-10` identities;
- one RPL border router;
- deterministic Cooja topology/seed;
- `fd00::/64` IoT prefix;
- run-scoped MQTT topics;
- canonical `synthran/telemetry/v1alpha1` events;
- contiguous per-sensor sequence validation.

Default integrated acceptance requires all ten sensors and a minimum contiguous event window from each sensor.

### Safety and cleanup

Before mutation, the experiment validates local/runtime prerequisites and guarded core-node state. It reclaims only provably stale SynthRAN-owned process signatures and fails closed on active/foreign/ambiguous ownership.

Cleanup is exact and run-scoped. It:

- terminates owned local/remote process groups;
- removes run-created `tun0` and verifies absence;
- removes the run-scoped remote workspace and verifies absence;
- verifies reserved ports are free;
- removes only the run-injected UE sidecar/config and run-labeled broker objects;
- lets srsUE recover and reconciles RFSIM if required;
- reproves the accepted base network.

A cleanup or base-network reproof failure prevents an `IOT-TO-5G PATH PROVEN` result.

### Accepted integrated evidence

- Base network: `network-acceptance-20260817-04` — `PATH PROVEN`
- Integrated experiment: `iot-acceptance-20260817-06` — `IOT-TO-5G PATH PROVEN`

The accepted IoT run proved all ten sensors, 30 canonical records for the minimum acceptance window, dynamic PDU discovery, exact cleanup, removal of run-created `tun0`/workspace, and base-network reproof.

### Scripted operator commands

```bash
conda activate synthran
source .synthran/preparations/<network-run-id>/authority.env

synthran experiment plan \
  --network-run-id <path-proven-network-run-id> \
  --run-id <experiment-run-id>

synthran experiment run \
  --inventory .synthran/preparations/<network-run-id>/hosts.ini \
  --network-run-id <path-proven-network-run-id> \
  --run-id <experiment-run-id>

synthran experiment verify --run-id <experiment-run-id>
```

These are explicit scripted workflows. The interactive `/run ...` command currently creates an application operation plan and does not invoke these commands behind the scenes.

## 2. Controlled research experiments

### Scientific objective

Controlled research asks:

> How does controlled 5G user-plane load affect deterministic IoT telemetry transported through SynthRAN?

The intended conditions are:

- `baseline`: no competing load;
- `load50`: 50% of the calibrated reference capacity;
- `load80`: 80%;
- `load95`: 95%.

Research load is UDP. A loaded run is valid only when the measured load meets the configured target-ratio gate and all independent path/instrumentation gates remain healthy.

### Reference capacity

Accepted calibration artifact:

```text
.synthran/research/calibration-20260817-02.json
```

Accepted reference capacity:

```text
67,253,028 bps
```

The live PDU is discovered dynamically during calibration and is never treated as desired/static state.

Example calibration command:

```bash
python -m synthran experiment research calibrate \
  --inventory "$INVENTORY" \
  --network-run-id network-acceptance-20260817-04 \
  --target "$CORE_TARGET" \
  --duration-seconds 10 \
  --out .synthran/research/capacity.json
```

### Measurement runtime

A controlled run uses the reconciled live UE/PDU handoff from base experiment setup and then applies these controls:

1. **Sidecar readiness barrier:** configuration refresh must produce the expected restart and Ready state.
2. **Exact route lifecycle:** a temporary target `/32` route is reused if already correct or added/owned explicitly and later removed only if SynthRAN created it.
3. **Owned iperf3 lifecycle:** server workspace/pidfile ownership is run-scoped; orphan recovery and postconditions are exact.
4. **Continuous RTT probe:** every attempt is represented; all-timeout runs retain timeout records rather than fabricated RTT values.
5. **Synchronized sampling:** Ingress, UE `tun_srsue1`, and UPF `ogstun` counters are sampled through the fixed measurement window.
6. **Structured provenance:** measurement path and research artifacts record the exact run inputs/results used for validity decisions.

### Implemented validity gates

The current runtime includes the hardening added after the invalid loaded pilot:

- reprove the accepted network path after warmup and after measurement;
- require the current run-owned UE pod and dynamic PDU handoff to remain consistent;
- require the exact route and bounded reachability before opening the measurement window;
- represent every RTT attempt, including all-timeout outcomes;
- prove the exact run-owned iperf3 listener without consuming the one-shot server;
- use bounded iperf3 control connection timing;
- require proof that the loaded client actually established its connection;
- abort when required probe/load/sampler processes exit unexpectedly;
- allow zero telemetry to represent a scientific outcome only when independent path, load, instrumentation, and cleanup validity remain healthy;
- persist measurement-path provenance;
- use deadline-based network sampling;
- identify repeated zero-sample RFSIM stalls;
- retry complete process-level RFSIM recovery up to the configured bounded attempt count.

These are current implementation properties, not future roadmap items.

## 3. Accepted controlled baseline

Accepted run:

```text
pilot-20260817-03-baseline
```

Configuration:

- campaign: `pilot-20260817-03`;
- condition: baseline;
- seed: `424242`;
- ten sensors;
- sensor period: 5 s;
- warmup: 30 s;
- measurement: 180 s;
- base network: `network-acceptance-20260817-04`.

Result:

```text
READY FOR CAMPAIGN ANALYSIS
IOT-TO-5G PATH PROVEN
```

Key measurements:

- telemetry: 360 expected / 360 received, 100% delivery, zero gaps, zero duplicates, 36 events per sensor;
- inter-arrival aggregate: mean 5000.58 ms, median 5000.67 ms, p95 5135.58 ms, p99 5310.92 ms;
- RTT: 180 attempts, 180 successful, zero timeouts, mean 25.44 ms, median 25.60 ms, p95 36.52 ms, p99 37.92 ms;
- RTT jitter: mean 10.05 ms, median 7.90 ms, p95 20.20 ms, p99 25.11 ms;
- network sampler: 51 samples over 180.6152 s, `transport_path_complete=true`;
- UE and UPF counters both increased with zero recorded drops in the accepted window;
- validity checks passed and instrumentation errors were empty.

## 4. Invalid historical load50 pilot

Run:

```text
pilot-20260817-03-load50
```

This run is **INVALID** and must not be used as scientific evidence that 50% background load caused telemetry failure or congestion.

What happened:

- target load was about 33.63 Mbps (50% of the accepted calibration);
- the iperf3 client failed to establish its control connection;
- background UDP load was therefore never established;
- telemetry was 0/360;
- RTT probes had 100% loss;
- ingress/local UE counters moved while UPF `ogstun` counters did not;
- the underlying RFSIM/5G transport path collapsed before a valid loaded measurement existed.

Process liveness and established ZMQ TCP sockets were not sufficient health proof: the gNB could remain stuck with zero RF sample progression while `tun_srsue1` was absent.

The base network was recovered through process-level RFSIM reconciliation without redeploying Open5GS/Kubernetes and was reproven afterward.

## 5. Campaign model and analysis

Campaign generation uses run-level experimental units in a deterministic randomized block design:

- block by seed;
- randomize condition order within each seed block using a fixed campaign seed;
- treat the run, not individual packets, as the statistical unit;
- compare valid loaded runs against their blocked baseline;
- compute paired differences and bootstrap confidence intervals offline.

Example plan:

```bash
python -m synthran experiment research campaign-plan \
  --campaign-id campaign-01 \
  --network-run-id network-acceptance-20260817-04 \
  --seeds 424242,424243,424244 \
  --conditions baseline,load50:0.5,load80:0.8,load95:0.95 \
  --campaign-seed 12345 \
  --out .synthran/campaigns/campaign-01.json
```

Analysis reads persisted run summaries and does not require live testbed access.

Invalid runs remain diagnostic evidence but are not treatment observations for scientific comparison.

## 6. Research artifacts

Controlled runs persist the applicable run-scoped artifacts, including:

- `experiment-spec.json`;
- `measurement-window.json`;
- telemetry JSONL/Parquet;
- probe JSONL/Parquet;
- network-sample JSONL/Parquet;
- load JSONL/Parquet for loaded conditions;
- `research-summary.json`;
- experiment/path evidence;
- local diagnostic logs.

Baseline runs intentionally have no background-load records when load is disabled.

JSONL remains the append-only audit source for telemetry. Parquet remains a reproducible derivative.

## 7. Separate acceptance concepts

Keep these concepts distinct:

- **base path acceptance:** the current network path is proven;
- **IoT path acceptance:** the integrated telemetry path and cleanup/reproof passed;
- **research validity:** the controlled measurement satisfied all required telemetry/probe/network/load/instrumentation/cleanup rules;
- **campaign readiness:** the run is valid for the intended statistical comparison.

A historical successful path does not prove the path is currently healthy. A currently healthy base path does not automatically make a research run scientifically valid.

## 8. Remaining work

The major scientific work still outstanding is live evidence, not the basic validity-gate implementation:

1. execute a **fresh valid load50** run under the current hardened gates;
2. establish valid load80 and load95 runs;
3. execute the intended multi-seed blocked campaign with never-reused run IDs;
4. analyze valid paired results and report findings;
5. consider network-sampling query batching/parallelization if the sequential remote-query cadence becomes a measurement limitation.

Product-side work is separate: the interactive terminal has application operation plans for `/run`, `/stop`, `/collect`, `/logs`, and `/down`, but their concrete terminal provider/domain executors remain unconnected. Do not conflate that product integration gap with the scientific validity gates already implemented in the scripted research runtime.
