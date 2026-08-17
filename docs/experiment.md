# Integrated IoT-to-5G Experiment and Controlled Research

SynthRAN provides two interconnected experiment tiers:
1. **Integrated IoT-to-5G Experiment:** A deterministic base experiment validating end-to-end telemetry transport across the 5G substrate.
2. **Controlled Research Experiments:** Fixed-window measurement campaigns with continuous RTT probing, synchronized multi-point network sampling, and calibrated UDP background load to quantify load effects on IoT telemetry.

Both workflows consume an already `path-proven` Open5GS + srsRAN + RFSIM network without reserving resources or redeploying the base network.

---

## 1. Integrated IoT-to-5G Golden Path

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

### Deterministic scenario

The supported base scenario is fixed to:

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

### Safety and cleanup boundary

The experiment command does not create a reservation, allocate or image nodes, deploy Open5GS, deploy the gNB, or tear down the accepted network. It requires the referenced network manifest to have `status=path-proven` and the referenced network evidence to have `ready=true` before creating the experiment run directory.

Local Cooja runtime prerequisites are strictly validated before any live cluster or 5G mutations occur:
- Java 21 (`openjdk=21.0.9`) must be present in the active `synthran` Conda environment;
- the pinned Contiki-NG checkout is validated;
- the deterministic MQTT sensor includes `project-conf.h` enabling Contiki TCP socket support (`#define UIP_CONF_TCP 1`);
- sensor compilation commands in generated Cooja scenarios explicitly embed the validated absolute Contiki checkout path (`CONTIKI=<path>`) rather than relying on unexpanded placeholders or ambient parent environment variables;
- child processes (`cooja`, SSH port-forwards) are actively monitored during readiness checks so early process exits fail immediately with exit code and log path.

Before live mutation, SynthRAN inspects the root core node and performs guarded preflight checks:
- automatically reclaims only provably stale/orphaned processes (PPID 1) matching exact SynthRAN runtime signatures (edge port-forward `18883:1883`, central port-forward `18885:18884`, `ingress.py`, and `tunslip6`), while active, foreign, or ambiguous ownership remains strictly fail-closed;
- verifies required tools (`ifconfig` from package `net-tools`, `gcc`, `make`, `python3`, `ip`, `tar`), root privileges, `/dev/net/tun`, absence of pre-existing `tun0`, and availability of reserved remote ports `60001`, `18883`, and `18885`;
- validates SSH daemon configuration (`sshd -T`) to require `AllowTcpForwarding` (`yes` or `all`).

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

### Canonical integrated acceptance evidence

The integrated deterministic IoT-to-5G experiment is live-accepted on SLICES:
- **Base network:** `network-acceptance-20260817-04` (`Result: PATH PROVEN`)
- **Integrated experiment:** `iot-acceptance-20260817-06` (`Result: IOT-TO-5G PATH PROVEN`)

Key facts proven live on 2026-08-17:
- **Pre-run stale runtime recovery:** 4 stale SynthRAN processes from previous runs were automatically reclaimed on the core node before mutation.
- **Dynamic PDU rediscovery:** The srsUE rollout dynamically discovered the live PDU address on `tun_srsue1` and bound the edge bridge to the live address.
- **Deterministic collection:** All 10/10 sensors published successfully, yielding 30 canonical JSONL records (minimum 3 per sensor) and derived Parquet.
- **Cleanup and network reproof:** Exact run processes were reaped, `tun0` and remote workspace removed, and the base network reproven (`[PASS] cleanup-base-network`).
- **Independent post-run audit:** Out-of-band inspection confirmed all postconditions (ports free, `tun0` absent, workspace absent).

### Operator commands

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

Render persisted acceptance evidence without touching live state:

```bash
synthran experiment verify --run-id <experiment-run-id>
```

---


## 2. Controlled Research Experiments

### Scientific objective

Controlled research evaluates:

> How does controlled load on the 5G user plane affect deterministic IoT telemetry transported through SynthRAN?

The experimental design contrasts two primary conditions:
- **Baseline:** 10 Cooja sensors, deterministic workload, 0 competing 5G traffic.
- **Loaded:** Same Cooja workload, same network, same measurement setup, with controlled UDP iperf3 traffic injected across `tun_srsue1`.

Research traffic protocol is **UDP only** (TCP controlled load is not supported). A loaded run is valid only when measured background load falls within the target ratio band:

$$0.90 \le \frac{\text{measured\_bps}}{\text{target\_bps}} \le 1.10$$

### Capacity calibration

To establish reproducible fractional load levels (e.g. 50%, 80%, 95%), reference capacity is measured against the path-proven network:

```bash
python -m synthran experiment research calibrate \
  --inventory "$INVENTORY" \
  --network-run-id network-acceptance-20260817-04 \
  --target "$CORE_TARGET" \
  --duration-seconds 10 \
  --out .synthran/research/calibration-20260817-02.json
```

**Calibration behavior:**
- Requires an already `path-proven` network.
- Reconciles RFSIM runtime when needed.
- Discovers the live UE pod and live PDU address.
- Proves or temporarily installs the exact target `/32` route through `tun_srsue1`.
- Starts a run-owned `iperf3` server on the core node.
- Measures saturating throughput over `tun_srsue1`.
- Removes only the SynthRAN-created temporary route.
- Stops the owned `iperf3` server and cleans the workspace.
- Persists calibration evidence only on full success.

**Accepted live calibration evidence:**
- Artifact: `.synthran/research/calibration-20260817-02.json`
- Base network: `network-acceptance-20260817-04`
- Target: `172.28.2.77`
- Reference capacity: `67,253,028 bps` (~67.25 Mbps over `tun_srsue1`).
- PDU discovered during calibration: dynamically discovered from live `tun_srsue1` (never hardcoded).

### Research instrumentation and lifecycle

1. **Reconciled PDU state handoff:** Base runtime performs RFSIM reconciliation once, discovers the live PDU address, updates scenario inputs, and proves the network path. That exact state is handed off to the research collector. The research collector consumes the handed-off state without triggering a second RFSIM reconciliation.
2. **Controlled sidecar readiness barrier:** Edge MQTT configuration refresh tracks the container `restartCount` and waits for increment plus sidecar and pod Ready conditions within a bounded timeout.
3. **Temporary target route lifecycle:** If the target route does not resolve via `tun_srsue1`, SynthRAN temporarily adds `ip route add <target>/32 dev tun_srsue1`. After measurement, only the SynthRAN-created route is deleted, and prior routing state is verified restored.
4. **Owned iperf3 server lifecycle:** Run-scoped workspace `/tmp/synthran-research/<run-id>/`, pidfile `iperf3-<port>.pid`, orphan-only recovery before run, explicit stop, and postcondition verification.
5. **Continuous RTT probe:** Continuous `ping -n -D -I tun_srsue1` to the target. Timestamps and sequence numbers are parsed into `probe.jsonl` / `probe.parquet` with per-sample RTT and timeout flags. Latency is documented as RTT only (no unsynchronized one-way latency claims).
6. **Synchronized network sampling:** Background thread samples Ingress snapshot, UE `tun_srsue1` counters, and UPF `ogstun` counters. Because remote SSH collection is sequential, `sample_interval=1.0` yields ~51 samples over 180.6s (remote latency + sleep interval). Rates are computed from boundary deltas over actual elapsed time.

### First accepted controlled baseline evidence

- **Campaign:** `pilot-20260817-03`
- **Run:** `pilot-20260817-03-baseline`
- **Condition:** `baseline` (0 background load)
- **Seed:** `424242`
- **Network:** `network-acceptance-20260817-04`
- **Sensor count:** 10, period: 5s, warmup: 30s, measurement duration: 180s.
- **Live PDU during run:** dynamically discovered from live `tun_srsue1` (never hardcoded).
- **Result:** `READY FOR CAMPAIGN ANALYSIS`, `IOT-TO-5G PATH PROVEN`.

**Quantitative metrics:**
- **Telemetry:** 360 expected, 360 received (100% delivery ratio). 0 sequence gaps, 0 duplicates. Exactly 36/36 events per sensor.
- **Inter-arrival:** Aggregate mean 5000.58 ms, median 5000.67 ms, p95 5135.58 ms, p99 5310.92 ms. (sensor-04 had tail p95 ~5857.75 ms, p99 ~7060.90 ms, with 100% delivery and zero gaps).
- **RTT probe:** 180 samples, 180 successful, 0 timeouts (0.0 ratio). RTT mean 25.44 ms, median 25.60 ms, p95 36.52 ms, p99 37.92 ms. RTT jitter mean 10.05 ms, median 7.90 ms, p95 20.20 ms, p99 25.11 ms.
- **Network transport path:** Elapsed: 180.6152 s, samples: 51, `transport_path_complete: true`.
  - UE `tun_srsue1`: tx delta = 111,857 B, rx delta = 34,074 B, tx packets = 544, rx packets = 545, dropped = 0 (tx rate ~4954.49 bps, rx rate ~1509.24 bps).
  - UPF `ogstun`: rx delta = 112,211 B, tx delta = 34,158 B, rx packets = 546, tx packets = 546, dropped = 0 (rx rate ~4970.17 bps, tx rate ~1512.96 bps).
  - Ingress: upstream delta = 77,829 B, downstream delta = 0 B, accepted connections delta = 0 (connections established prior to sample window).
- **Validity checks:** `telemetry_present`, `probe_present`, `network_samples_present`, `transport_path_sampled`, `load_target_achieved`, `measurement_window_present`, `instrumentation_clean`, `base_cleanup_reproved` all `True`. Instrumentation errors: `[]`.

---

## 3. Campaign Model and Offline Analysis

The final research design uses run-level experimental units in a randomized block design:

- **Conditions intended:** `baseline` (0%), `load50` (50%), `load80` (80%), `load95` (95% of reference capacity).
- **Deterministic seeds:** Blocked by seed (e.g. `424242`, `424243`, `424244`, `424245`, `424246`).
- **Randomization:** Condition execution order is randomized within each seed block using a fixed campaign seed.
- **Statistical unit:** The run is the statistical unit (not individual packets).
- **Offline analysis:** `synthran experiment research analyze` reads persisted `research-summary.json` files and computes bootstrap paired differences with 95% confidence intervals against baseline without contacting live testbeds.

### Research artifacts

Persisted under `.synthran/experiments/<run-id>/`:
- `experiment-spec.json`: immutable research run specification;
- `measurement-window.json`: exact UTC start and end bounds of the active measurement window;
- `telemetry.jsonl` / `telemetry.parquet`: canonical telemetry events and derived dataset;
- `probe.jsonl` / `probe.parquet`: continuous RTT probe samples and timeout flags;
- `network-samples.jsonl` / `network-samples.parquet`: synchronized interface and ingress counter samples;
- `load.jsonl` / `load.parquet`: background load throughput records (for loaded conditions);
- `research-summary.json`: consolidated research metrics, validity flags, and SHA-256 digests of all source artifacts (`synthran/research-summary/v1alpha1`);
- `experiment-evidence.json`: base-network reproof and step results;
- `logs/`: local probe, client, and server logs.

Missing `load.jsonl` / `load.parquet` is expected for baseline runs where background load is intentionally disabled.

---

## 4. Research Validity, Diagnostics, and Known Limitations

### Separate validity and acceptance concepts

SynthRAN maintains strict separation between infrastructure path proof and experimental validity:
- **`path_acceptance_ready`**: Indicates whether the underlying 5G data path and base network verification passed.
- **`ready_for_campaign_analysis`**: Indicates whether the research run satisfied all scientific validity constraints (complete telemetry, active probing, verified load ratio within $0.90 \le \text{ratio} \le 1.10$, complete multi-point sampling, and clean cleanup reproof).
- **`transport_path_complete`**: Indicates that all three required sampling points (Ingress, UE `tun_srsue1`, UPF `ogstun`) were successfully polled during the measurement window. It does not by itself guarantee that user-plane traffic crossed the path.

### Diagnostic analysis of invalid loaded pilot (`pilot-20260817-03-load50`)

Following the accepted baseline run, a 50% loaded pilot was executed and is recorded as consumed and **`INVALID`**:
- **Campaign:** `pilot-20260817-03`
- **Run ID:** `pilot-20260817-03-load50`
- **Condition:** `load50` (target bitrate: `33,626,514 bps` / ~33.63 Mbps, 50% of reference capacity `67,253,028 bps`)
- **Seed:** `424242`
- **Final status:** `Research result: INVALID`, `Path acceptance: NOT PROVEN`, `ready_for_campaign_analysis: false`, `path_acceptance_ready: false`.

**Root cause analysis:**
1. **Background load was never established:** The `iperf3` client inside the srsUE pod failed to establish its control connection to the core server (`unable to connect to server: Connection timed out`). No background UDP load was injected (`measured_bps: null`, `load_target_achieved: false`).
2. **Path failure prior to measurement:** Telemetry delivery was 0/360 events across all 10 sensors (no JSONL generated), and the RTT probe recorded 100% packet loss (178 pings sent, 0 received).
3. **Transport counters:** Network sampling recorded Ingress upstream traffic (+77,919 B) and local UE TX counters (+16,992 B), but UPF `ogstun` counters remained at 0 bytes throughout the entire window.
4. **Scientific conclusion:** This run **must not** be interpreted as evidence that 50% load causes telemetry loss or congestion. The underlying 5G/RFSIM transport path collapsed before the measurement window opened and before load could be applied.
5. **Collector UX defect:** The terminal logged `collector: OK (0 events from 10 sensors)` followed by `unable to read JSONL telemetry`. This reflects an inherited test renderer defect where fixed-window timer completion was misinterpreted as data collection success.

### RFSIM failure diagnostics and recovery without redeployment

During teardown of `pilot-20260817-03-load50`, automated cleanup initially failed closed when srsUE tunnel readiness timed out after 2 attempts while the `srsue` process remained alive. Read-only verification confirmed `[FAIL] ue-tunnel` while all Kubernetes pods and gNB cell remained active.

Detailed runtime inspection revealed:
- `srsue`, GNU Radio broker, and `gnb` processes were all alive;
- All expected ZMQ TCP socket connections were established (srsUE $\leftrightarrow$ GNU Radio broker, broker $\leftrightarrow$ gNB);
- The srsUE startup log reached `Waiting PHY to initialize ... done!` and `Attaching UE...` and stalled indefinitely;
- The gNB logged `Waiting for data. Waiting for reading samples. Completed 0 of 23040 samples.`;
- `tun_srsue1` was absent.

**Key finding:** Process liveness and established ZMQ TCP connections do not guarantee that the RFSIM RF sample stream is progressing.

**Recovery without redeployment:** Explicit process-level RFSIM reconciliation was executed against base network `network-acceptance-20260817-04`. It stopped stale processes, restarted the gNB, activated the cell, restarted GNU Radio and `srsue`, and cleanly restored `tun_srsue1`, returning `Result: PATH PROVEN` without requiring Open5GS or Kubernetes redeployment.

### Known research runtime gaps and future roadmap

The following six items represent identified runtime limitations and planned engineering corrections:

1. **Pre-measurement health gate:** Add an active user-plane reachability check immediately prior to opening the controlled measurement window to prevent executing measurements on degraded radio paths.
2. **Load startup fail-fast:** Implement early termination if the `iperf3` client cannot establish a connection to the server within an initial timeout, avoiding running out empty 180-second measurement windows.
3. **Zero-telemetry validation semantics:** Formally distinguish valid experimental zero-delivery outcomes (under extreme congestion with healthy infrastructure) from invalid zero-delivery caused by underlying transport/instrumentation failure.
4. **Stronger RFSIM health detection:** Implement deep RFSIM health probing based on active RF sample stream progression and tunnel establishment rather than process presence and TCP socket connections.
5. **Enhanced terminal observability:** Implement structured multi-stage console progress rendering (`ResearchProgressRenderer`) to surface active runtime state transitions (UE/PDU discovery, route verification, probe health, load client connection, bitrate, achieved ratio, and cleanup reproof).
6. **Network sampling cadence optimization:** Revisit sequential remote SSH query latency in the network sampler to evaluate batching or parallel queries before large-scale multi-seed campaigns.
