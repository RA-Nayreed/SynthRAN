# Live research results — 2026-08-18

This record captures the live SynthRAN research evidence established on SLICES on 2026-08-18 before completion of the multi-seed campaign. It distinguishes accepted experimental evidence from immutable diagnostic failures.

## Accepted network and calibration

Current accepted base network:

```text
network-acceptance-20260818-04
Result: PATH PROVEN
```

External measurement peer:

```text
sopnode-f3
provider-facing IPv4: 172.28.2.95
```

Current accepted external-peer calibration:

```text
artifact: .synthran/research/calibration-20260818-external-01.json
network_run_id: network-acceptance-20260818-04
target: 172.28.2.95
ue_interface: tun_srsue1
reference_capacity_bps: 66,687,096
```

The reference is TCP goodput measured over the UE path to the external peer. Fractional loaded conditions below are UDP offered-load treatments derived from this reference; they are not claims about physical radio capacity.

## Transport-aware smoke acceptance

After the loaded-run readiness fix, the first fresh production-path smoke run was accepted:

| Run | UDP target | Flows | Telemetry | RTT | Load ratio | Result |
|---|---:|---:|---:|---:|---:|---|
| `smoke-20260818-02-udp1m` | 1.00 Mbps | 1 | 60/60 | 30 attempts, 0 timeouts | 1.000 | `READY FOR CAMPAIGN ANALYSIS` |

The run proved the exact route through `tun_srsue1`, the external run-owned iperf3 server, an established UE TCP control connection, the fixed measurement window, post-window network reproof, and cleanup reproof.

## Loaded pilot results

### Accepted runs

| Run | Condition | Aggregate UDP target | Flows | Telemetry | RTT | Measured load | Result |
|---|---|---:|---:|---:|---:|---:|---|
| `pilot-20260818-02-load50` | load50 | 33.34 Mbps | 1 | 360/360 | 180 attempts, 0 timeouts | 33.34 Mbps, ratio 1.000 | `READY FOR CAMPAIGN ANALYSIS` |
| `pilot-20260818-02-load50-p2` | load50 | 33.34 Mbps | 2 | 360/360 | 180 attempts, 0 timeouts | 33.34 Mbps, ratio 1.000 | `READY FOR CAMPAIGN ANALYSIS` |
| `pilot-20260818-02-load80-p2` | load80 | 53.35 Mbps | 2 | 360/360 | 180 attempts, 0 timeouts | 53.35 Mbps, ratio 1.000 | `READY FOR CAMPAIGN ANALYSIS` |
| `pilot-20260818-02-load95-p2` | load95 | 63.35 Mbps | 2 | 361/360 | 180 attempts, 0 timeouts | 63.35 Mbps, ratio 1.000 | `READY FOR CAMPAIGN ANALYSIS` |

Every accepted loaded pilot also completed post-window path verification and run-scoped cleanup with the base network reproven.

The 361/360 telemetry count in `pilot-20260818-02-load95-p2` is not a failed validity gate; the persisted research result was accepted as `READY FOR CAMPAIGN ANALYSIS`.

### Invalid single-flow load80 diagnostic

`pilot-20260818-02-load80` is immutable **INVALID** diagnostic evidence and must not be included as a treatment observation.

The run did not show a base-network collapse:

- telemetry remained 360/360;
- all 180 RTT attempts succeeded;
- the post-window path was ready;
- cleanup reproved the accepted base network.

The failure was isolated to the high-rate single-flow iperf3 load path. The sender sustained approximately 53.35 Mbps through second 87, fell to approximately 9.60 Mbps during second 87–88, and then reported zero transmitted bytes in the remaining intervals. The final client summary reported 581,372,180 bytes over 195 seconds, approximately 23.85 Mbps average sender rate, no usable final receiver result, and:

```text
unable to send control message - port may not be available, the other side may have stopped running, etc.: Broken pipe
```

The corresponding server log was empty. This failure must not be interpreted as evidence that the 5G path itself failed at 80% load.

The immediate follow-up kept the same aggregate 53.35 Mbps target but split it across two UDP flows. `pilot-20260818-02-load80-p2` then sustained the full target for the accepted 180-second measurement and passed all validity gates. The same two-flow configuration also passed load50 and load95.

## Frozen loaded-condition pilot protocol

The live pilot therefore established the following configuration for the multi-seed campaign:

```text
reference TCP goodput: 66,687,096 bps
measurement peer:      sopnode-f3 / 172.28.2.95
UE route:              tun_srsue1

baseline:              no background load
load50:                0.50 reference = 33.34 Mbps aggregate UDP
load80:                0.80 reference = 53.35 Mbps aggregate UDP
load95:                0.95 reference = 63.35 Mbps aggregate UDP
parallel UDP flows:    2 for every loaded condition

sensor count:          10
sensor period:         5 s
warmup:                30 s
measurement:           180 s
network sample target: 1 s
RTT probe target:      1 s
```

Only the target fraction changes between loaded treatments. The flow count and other measurement settings remain fixed.

## Multi-seed campaign status

The first blocked campaign was generated as:

```text
campaign_id: campaign-20260818-01
network_run_id: network-acceptance-20260818-04
campaign_seed: 20260818
seeds: 424242, 424243, 424244
conditions: baseline, load50=0.5, load80=0.8, load95=0.95
parallel_flows: 2 for loaded conditions
```

Persisted randomized order:

```text
Block 1 / seed 424242:
  load95 -> load50 -> baseline -> load80

Block 2 / seed 424243:
  load80 -> load95 -> baseline -> load50

Block 3 / seed 424244:
  baseline -> load50 -> load80 -> load95
```

The 12-run `campaign-run` was started after these pilots were accepted. Campaign outcomes are deliberately not recorded in this document until the persisted campaign completes and the resulting run summaries are inspected. Completed and invalid run IDs remain immutable and are never overwritten.

## Historical invalid evidence retained

The following earlier runs remain diagnostic-only and must not be promoted into the scientific treatment dataset:

- `pilot-20260817-03-load50`: underlying RFSIM/5G path failure before valid loaded measurement;
- `pilot-20260818-01-load50`: same-host measurement topology bug;
- `smoke-20260818-01-udp1m`: ICMP-only pre-window readiness gate prevented the corrected external load transport from starting;
- `pilot-20260818-02-load80`: high-rate single-flow iperf3/control-path stall described above.

Scientific analysis should use only runs whose own persisted validity gates report `READY FOR CAMPAIGN ANALYSIS`.