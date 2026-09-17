# Experiment 4: sensor aggregation, gateway UE count, and service capacity

## Objective

Determine how modeled sensor population, 5G gateway count, and transport-connection count affect timely delivered service under explicit application requirements, and identify which layer becomes limiting as the system scales.

The study distinguishes Ambient-IoT source scaling from 5G gateway scaling. A software guard or configuration limit is not evidence of physical capacity; capacity claims must be tied to observed service criteria, tested hardware/software, and a fixed observation horizon.

## Scope and claim boundary

Three quantities must remain distinct:

| Symbol | Quantity | Potential effect |
| --- | --- | --- |
| `N` | Number of modeled Ambient-IoT sensors | Energy/activity, MAC contention, and source-event volume |
| `U` | Number of software/physical 5G gateway UEs | Radio scheduling entities, tunnels, UE/host resources |
| `K` | Number of MQTT/TCP connections | Client concurrency, queueing, socket/broker behavior |

Changing more than one quantity at a time prevents attribution. The experiment therefore separates sensor-population scaling, fixed-workload gateway partitioning, and connection-count controls.

Ambient-IoT devices remain modeled. Physical UEs are gateway transport entities and must not be counted as physical Ambient-IoT sensors.

## Research questions

- **S1:** At fixed `U` and `K`, where does timely delivered service stop scaling with increasing `N` under realistic per-sensor sensing and energy behavior?
- **S2:** At fixed immutable aggregate event stream and fixed `K`, does distributing traffic across more `U` improve or degrade delivery under shared radio resources?
- **S3:** How much of an apparent multi-UE effect is explained by transport-connection concurrency rather than by the additional UEs themselves?
- **S4:** Does common-energy synchronization change a defensible aggregation limit relative to independent harvesting at matched operating points?

## Implementation prerequisites

Scientific execution requires an explicit `sensor_id -> gateway_id -> connection_id` mapping and evidence that every expected event is forwarded at most once and classified exactly once. A gateway may exist without an assigned modeled sensor, for example when it generates competing traffic.

Source generation must not require one live UE per simulated sensor. Gateway publishers must bind to the attested interface/address of the selected accepted deployment. Per-sensor generation identity and sequence information remain unchanged through gateway aggregation.

Publisher operation must expose queue/inflight behavior rather than serializing all traffic through per-event PUBACK waits. Model/logging runtime is qualified separately from network capacity so an offline simulation bottleneck is not misreported as a 5G capacity limit.

## Experiment A — sensor population at fixed gateway resources

Hold `U=1` data gateway and `K=1` persistent connection fixed, plus a separate competing UE only when a loaded-cell condition is part of the design. Sweep `N` through pilot-supported values such as 8, 16, 32, 64, and 128.

Keep per-sensor sensing law, spatial deployment rule, MAC resources, and energy model fixed. Compare independent and common E-knee harvesting. Event count is allowed to change: this is a total sensor-population intervention, not an equal-offered-load comparison.

Use model pilots to identify low, transition, and high population levels before physical replay. A planning physical design with three `N` levels, two dependence regimes, ten source seeds, and two competing-load levels gives:

```text
3 N levels × 2 energy regimes × 10 seeds × 2 loads = 120 replays
```

Freeze the final levels and sample size before confirmation.

Capacity is defined by an application/service criterion, not by aggregate throughput alone. A valid criterion should include both a freshness/deadline requirement and minimum per-sensor service coverage over a fixed horizon so starved sensors cannot be hidden by high aggregate success.

## Experiment B — fixed-workload partition across gateway UEs

Freeze one aggregate event stream: exact event identities, release times, payload bytes, and sensor identities. Change only the gateway partition. Total offered traffic must remain identical across `U` treatments.

Use balanced deterministic partitions by event volume, with prespecified assignment seeds if routing imbalance is part of the uncertainty assessment. Verify the aggregate release process after partitioning.

Hold `K` fixed and at least as large as the largest tested `U`. For example, `U ∈ {1,2,4}` with `K=4` separates connection-count changes from gateway-count changes. First determine which `U` values are actually sustained by the software/testbed; the first reproducible resource limit is itself an engineering result and must be attributed to the observed resource.

For physical N320 validation, restrict the treatment to the number of homogeneous, independently attested physical UEs actually available. If only two are proven, use `U={1,2}` and do not extrapolate higher software-UE results into physical claims.

A planning matrix with `U={1,2}`, two timing structures, ten immutable source seeds, and one fixed load gives 40 physical replays. Additional load levels require a separately qualified competitor path.

## Experiment C — connection-count control

At one fixed `U`, sweep a small feasible `K` set such as `{1,2,4}` while preserving the same global event set and release process. Measure client queueing, ACK timing, socket behavior, broker load, and host utilization.

This is a diagnostic control used to explain gateway-scaling results; it is not a full factorial crossing of `N`, `U`, `K`, energy, RF, and competing load.

## Measurements

For every condition retain:

- the complete `N/U/K` mapping;
- attempted and realized offered event/byte rate globally and per gateway/connection;
- model, publisher, UE, gNB/core, broker, and receiver CPU/RSS where available;
- queue/inflight occupancy and scheduling error;
- radio/user-plane failure counters where exposed;
- per-sensor delivery, deadline, and freshness outcomes;
- per-sensor service coverage, worst-decile service, starvation intervals, and a precisely defined fairness measure.

If all inputs to Jain's fairness index are zero, report the index as undefined rather than as perfect fairness.

## Analysis

Analyze Experiment A as total population-dependent system behavior. Analyze Experiments B and C as paired immutable-workload interventions.

Source realization/seed is the primary independent scientific unit; physical sessions/configuration blocks are retained when they introduce shared drift. Report uncertainty separately for model-derived source limits and physical gateway-transport limits.

Use language such as **“supported `N` under configuration X, criterion Y, and horizon T”** rather than claiming a universal maximum sensor count. If the Ambient-IoT MAC saturates before gateway transport, low 5G delay does not establish spare end-to-end capacity. If host CPU saturates before radio processing, report a software-host limit.

## Falsification and validity threats

- Adding UEs may provide no benefit when the bottleneck is upstream source contention, broker/application processing, or a shared transport resource.
- A multi-UE improvement may disappear when `K` is held fixed, indicating a connection-concurrency mechanism rather than a UE mechanism.
- Aggregate delivery can mask persistently unserved sensors; per-sensor criteria are therefore mandatory.
- Different modem models, RF positions, subscriber policies, or slices can confound a gateway-count treatment and must be matched, blocked, or reported explicitly.

## Reproducibility and evidence

Retain the frozen population/gateway/connection mapping, source bundles, deployment identity, UE interface/address bindings, treatment ordering, background-load identity, resource observations, exclusions, and analysis outputs.

Shared timestamp, receipt, AoI, clock, experimental-unit, and failure-taxonomy conventions are defined in [`../MEASUREMENT_AND_INFERENCE.md`](../MEASUREMENT_AND_INFERENCE.md).

## Completion criteria

The study is complete when:

1. `N`, `U`, and `K` are independently controllable for the declared comparisons;
2. every expected event has reconciled sensor, gateway, and connection identity;
3. service-capacity criteria are frozen before confirmation;
4. all assigned runs have an explicit disposition and retained resource evidence;
5. capacity is attributed to the observed limiting layer where the evidence supports that attribution;
6. physical conclusions remain bounded to the tested hardware, accepted deployment, load, and observation horizon.
