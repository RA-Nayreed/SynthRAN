# Experiment and research protocol

SynthRAN has two connected experiment layers:

1. **Integrated IoT-to-5G experiment** — prove deterministic telemetry can traverse the accepted open 5G path and be collected reproducibly.
2. **Controlled research experiment** — run the same workload inside a fixed measurement window while adding calibrated background load and instrumentation.

Both consume an already path-proven Open5GS + srsRAN + RFSIM base network. Experiment commands do not silently reserve resources or redeploy the network.

Current live results are summarized in [`results.md`](results.md).

## 1. End-to-end path

```text
10 deterministic Contiki-NG/Cooja sensors
-> RPL / 6LoWPAN
-> Cooja Serial Socket
-> loopback-only reverse SSH tunnel
-> tunslip6 / tun0
-> counted TCP/MQTT ingress
-> Mosquitto bridge in srsUE network namespace
-> tun_srsue1
-> srsRAN gNB
-> Open5GS UPF
-> run-owned central broker / collector
-> canonical JSONL
-> deterministic Parquet
```

The edge bridge runs inside the srsUE network namespace because that is where the live UE PDU address and `tun_srsue1` exist. SynthRAN rediscovers the PDU after RFSIM reconciliation rather than trusting an older manifest value.

The counted ingress is an integration adapter; it is not the cellular proof boundary. Acceptance also requires current UE/UPF path evidence and exact cleanup/base-network reproof.

## 2. Deterministic IoT workload

The accepted virtual experiment uses:

- exactly ten sensors, `sensor-01` through `sensor-10`;
- one RPL border router;
- deterministic Cooja seed/topology;
- run-scoped MQTT topics;
- canonical `synthran/telemetry/v1alpha1` records;
- per-sensor sequence integrity checks.

Research campaigns vary the Cooja seed between blocks while keeping the scenario fixed within a block. Conditions inside a block therefore observe the same deterministic workload under different network treatments.

## 3. Controlled research conditions

The accepted campaign studies controlled user-plane background load:

```text
baseline  no background load
load50    0.50 × calibrated reference capacity
load80    0.80 × calibrated reference capacity
load95    0.95 × calibrated reference capacity
```

Research load is UDP. The reference capacity is calibrated separately over the UE path to the external measurement peer. All loaded campaign-06 treatments use two parallel UDP flows while keeping aggregate target bitrate fixed by condition.

The current accepted calibration is:

```text
network run:        network-acceptance-20260818-09
measurement peer:   172.28.2.95
reference capacity: 66,366,402 bps
artifact:           calibration-20260819-external-08.json
```

This is an empirical UE-path reference for the accepted testbed epoch, not a claim about physical radio capacity.

## 4. External measurement peer

Capacity calibration and loaded research traffic must terminate outside the 5G core host:

```text
UE PDU
-> tun_srsue1
-> srsRAN / 5G user plane
-> Open5GS UPF
-> core egress / NAT
-> prepared RAN node
```

The core node is rejected as the research iperf3 server because a same-host endpoint can collapse into a Kubernetes/hairpin path and misrepresent external user-plane transport.

See [`research-measurement-peer.md`](research-measurement-peer.md) for the exact ownership/readiness contract.

## 5. Measurement window

A controlled run has explicit warmup and measurement boundaries. Campaign-06 uses:

```text
sensor count:            10
sensor period:           5 s
warmup:                  30 s
measurement:             180 s
RTT probe request:       1 s
network sample request:  1 s
loaded UDP flows:        2
```

During the measurement window SynthRAN records, as applicable:

- telemetry received by the run-owned collector;
- continuous ICMP RTT attempts bound to the UE path;
- UE `tun_srsue1` counters;
- UPF `ogstun` counters;
- counted ingress state;
- iperf3 background goodput;
- exact UTC window bounds and measurement-path evidence.

## 6. Readiness and validity

A loaded condition is not scientifically valid merely because iperf3 printed throughput. The runtime independently checks the path, load, instrumentation, and cleanup boundaries.

Before/during/after the window, the current runtime requires the applicable checks to pass:

- current base network is path-proven;
- current run-owned UE/PDU handoff is consistent;
- exact target route uses `tun_srsue1`;
- baseline target is reachable through the bounded baseline readiness proof;
- loaded conditions have a run-owned external iperf3 server and an `ESTABLISHED` UE TCP control connection before the window opens;
- requested load reaches the configured target-ratio gate;
- RTT instrumentation produces records;
- network counter sampling covers the transport path;
- post-window network proof succeeds;
- run-owned cleanup succeeds and the base network is reproven.

`CLOSE-WAIT` is never accepted as loaded readiness. Failed runs retain their evidence and IDs; they are not silently retried under the same identity.

## 7. Network-sampling cadence

The network sampler records `sample_duration_seconds` and `schedule_lag_seconds`; therefore the configured interval and the achieved interval are distinct pieces of evidence.

Campaign-06 requested 1-second network-counter sampling but achieved approximately one sample every three seconds because the ingress, UE, and UPF queries were collected sequentially. The run-level first/last counter deltas remain usable, but campaign-06 must not be described as 1 Hz counter-resolution evidence.

The sampler is hardened for future runs by:

1. collecting the independent ingress, UE, and UPF read-only sources concurrently;
2. retaining deadline-based scheduling;
3. rejecting a run when achieved sample count falls below the accepted fraction of the requested cadence.

RTT probing is independent and did achieve 180 attempts in each 180-second campaign-06 window.

## 8. Telemetry count semantics

A periodic source and a hard observation window do not guarantee exactly `duration / period` records inside the window. The first transmission can occur at an arbitrary phase relative to the window boundary.

For the current v1alpha1 summaries:

- `expected_events` is a **nominal fixed-window expectation**;
- `delivery_ratio` should be interpreted as nominal window occupancy;
- per-sensor sequence gaps and duplicates are the direct observed integrity metrics.

Campaign-06 contains zero sequence gaps and zero duplicates, including the few streams that contain 35 rather than 36 records inside the window. Do not report those boundary-aligned 35-record streams as observed packet loss.

This distinction is intentionally scientific: actual sequence loss is allowed to be an experimental outcome when the independent network/load/instrumentation validity gates remain healthy.

## 9. Campaign design

Campaigns use a randomized blocked design:

- each Cooja seed is one block;
- every condition appears once in each block;
- condition order is randomized reproducibly with a fixed campaign seed;
- a **run**, not an individual packet or RTT sample, is the statistical unit;
- loaded runs are paired with the baseline from the same seed block.

Example planning command:

```bash
python -m synthran experiment research campaign-plan \
  --campaign-id campaign-01 \
  --network-run-id NETWORK_RUN_ID \
  --seeds 424242,424243,424244 \
  --conditions baseline,load50:0.5,load80:0.8,load95:0.95 \
  --campaign-seed 12345 \
  --out .synthran/campaigns/campaign-01.json
```

Offline analysis reads only persisted run summaries whose own validity gates report readiness.

```bash
python -m synthran experiment research analyze \
  --campaign .synthran/campaigns/campaign-01.json \
  --run-root /path/to/experiments \
  --out .synthran/reports/campaign-01-analysis.json
```

## 10. Research artifacts

A controlled run persists the applicable evidence below its run directory:

```text
experiment-spec.json
measurement-window.json
measurement-path.json
telemetry.jsonl / telemetry.parquet
probe.jsonl / probe.parquet
network-samples.jsonl / network-samples.parquet
load.jsonl / load.parquet       # loaded conditions only
research-summary.json
logs and integrated experiment evidence
```

JSONL is the append-only audit source. Parquet is a deterministic analysis derivative.

## 11. Accepted campaign and next question

`campaign-20260819-06` completed all 12 runs across three seeds and four conditions. It established valid controlled transport up to 95% of the reference capacity with no RTT timeouts, no observed telemetry sequence gaps/duplicates, and no receiver-reported UDP packet loss in the loaded runs.

The unexpected result is that RTT was consistently lower during all three continuously loaded conditions than during baseline. Because load50/load80/load95 cluster close together, the next experiment should distinguish **idle versus active path state** from **load magnitude** before any causal claim is made.

See [`results.md`](results.md) for the measured values, preservation identifiers, limitations, and proposed follow-up.

## 12. Operator entry points

The scripted CLI remains the live execution path. Typical research stages are:

```text
prepare resources
-> deploy 5G network
-> verify path
-> calibrate external UE path
-> plan campaign
-> run campaign
-> analyze persisted valid runs offline
```

Exact commands and safety boundaries are in [`operator-guide.md`](operator-guide.md). The interactive terminal may create state-sensitive operation plans but does not yet execute these provider/domain workflows itself.
