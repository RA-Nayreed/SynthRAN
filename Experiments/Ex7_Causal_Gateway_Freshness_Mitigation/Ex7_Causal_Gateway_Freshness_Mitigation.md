# Experiment 7: causal gateway policies for information freshness

## Objective

Evaluate whether a practical gateway policy can reduce application freshness violations caused by bursty decoded arrivals while making the cost in sample completeness, transport bytes, fairness, and latency explicit.

The intended contribution is a causal gateway policy and an experimentally supported operating rule, evaluated on held-out source realizations over an accepted physical 5G transport path. Token buckets, latest-update queues, and Age of Information are established concepts; novelty must come from the validated intervention, trade-off, generalization, or mechanism rather than from deploying those mechanisms alone. See the [Age of Information survey](https://arxiv.org/abs/2007.08564) for background.

## Scope and application semantics

The primary application model is periodic sensor-state reporting where a newer measurement may supersede an older **not-yet-published** measurement from the same sensor. That assumption permits coalescing.

It does not automatically apply to alarms, billing records, irreversible actions, or event logs where every observation is semantically distinct. Those workloads require lossless policies or an explicitly different utility model.

Gateway policies act **after** modeled reader decoding. They do not reduce modeled sensor energy consumption or Ambient-IoT collisions in the open-loop architecture. Any upstream energy benefit would require an implemented feedback path and a different experiment.

## Research questions and hypotheses

- **G1:** Lossless pacing can reduce burst pressure after the gateway but may worsen freshness by moving waiting time into the gateway queue.
- **G2:** A fair latest-update policy can reduce freshness-violation time and network cost near a transport service limit, with an explicit reduction in sample completeness.
- **G3:** A policy selected using pilot conditions retains useful performance on held-out source realizations and prespecified load shifts.

No policy is assumed to improve every objective. A useful policy must satisfy a prospectively defined trade-off, including any required completeness floor.

## Causality contract

Every decoded source event becomes an immutable gateway-arrival event at its native release time `s`. A policy may inspect only:

- events whose release time has already occurred;
- current queue/inflight/token state;
- permitted past local observations.

It must not inspect future trace entries, future energy/channel state, or future application receipts. A deterministic qualification fixture must show that changing a trace's future suffix cannot alter earlier policy decisions.

For each event retain source identity and generation sequence, gateway arrival, queue admission, intentional waiting, replacement/drop decision and reason, publication time, acknowledgement/receipt evidence, and relevant queue/token/inflight state.

A PUBACK is a local client-to-broker signal, not application-delivery feedback. An adaptive policy may use it only under that interpretation unless an explicit receiving-application feedback protocol is implemented and its traffic/delay are part of the experiment.

## Primary policies

| Policy | Action | Scientific role |
| --- | --- | --- |
| P0 — immediate FIFO | Publish eligible arrivals promptly through the qualified asynchronous client, subject to the common bounded queue/inflight rules | Unshaped reference |
| P1 — lossless FIFO pacing | FIFO queue with fixed token-bucket byte rate and burst budget | Isolates smoothing/holding effect |
| P2 — fair FIFO pacing | Same token policy with per-sensor FIFO queues and fair service | Isolates scheduling/fairness effect |
| P3 — fair latest-update pacing | Same fair scheduler/token policy; retain only the freshest pending unsent update per sensor | Adds causal coalescing |

Use one common MQTT connection, one gateway UE, fixed QoS, and identical serialization in the primary campaign. P1/P2/P3 use exactly the same frozen token rate and burst budget within matched conditions.

Specify token initialization, accumulation cap, queue limits, inflight limit, tie-breaking, and drain behavior. The burst budget must accommodate the largest legal message. P1/P2 may be called lossless only inside a qualified operating domain where queue/inflight overflow does not occur.

P3 may replace an older **pending unsent** update only with a newer generation from the same sensor. Equal or older generations cannot evict a fresher update. Messages already handed to the MQTT client cannot be retracted or relabeled as if they had never been sent.

## Parameter selection

Select one token rate and burst budget from an independent pilot that characterizes source rates and the relevant service/latency transition. Freeze the parameters before confirmation.

A practical fixed policy must not know the future background-load schedule. An optional adaptive variant may use past local queue age, submission/ACK behavior, or other explicitly available signals within frozen control limits, but it remains a secondary treatment until its algorithm and feedback assumptions are fully specified.

Policy parameters must not be tuned separately on each confirmation trace.

## Confirmation design

Use qualified native source traces at real-time scale with E-knee independent and common harvesting as two source regimes. Preserve source event bytes, generation timestamps, and gateway-arrival times across policies.

A planning confirmation matrix is:

| Factor | Levels |
| --- | --- |
| Source regime | E-knee independent, E-knee common |
| Independent source seeds | 10 per regime |
| Gateway policy | P0, P1, P2, P3 |
| Competing offered load | Low, near pilot service transition |
| Planned physical replays | **160** |

Final source count and duration must be frozen from independent pilot variance, runtime, and practical-effect requirements. Confirmation source realizations remain outside parameter tuning.

Randomize policy order within matched source/load blocks and balance blocks across multiple physical sessions where practical. The same background-workload realization is replayed across the matched policy comparison.

An optional shift study may compare P0/P3 on unseen source seeds under prospectively defined within-run load schedules. The fixed policy parameters must be selected without using those shift outcomes.

## Outcomes and accounting

Set an application freshness limit `A_max` independently of confirmation results. The primary utility is the equal-weight per-sensor fraction of observation time for which `AoI > A_max`, including sensors without initialized received history according to the frozen convention.

Use **all decoded gateway arrivals** as the denominator for completeness. Every event must end in a reconciled scientific disposition, such as:

- received by deadline;
- received late;
- intentionally superseded/discarded;
- rejected/failed by the publisher;
- still outstanding at the fixed drain.

Do not remove intentionally coalesced samples from the denominator. A policy's reduced byte count is a treatment effect, not evidence that it was subjected to the same post-policy offered load.

Also report:

- time-average/tail AoI and freshness-violation time;
- maximum starvation interval and worst-served sensor/group;
- delivery-by-deadline and total unique sample completeness;
- intentional discards, unintentional failures, late delivery, and final backlog;
- `p-s` gateway holding/release error and `r-s` gateway-arrival-to-application delay;
- payload and measured transport bytes where available;
- queue occupancy, token utilization, per-sensor service, publisher/collector CPU, and background-flow impact.

Do not judge pacing from `r-p` alone: a pacer can make post-publication latency look better by moving waiting into the gateway.

## Primary contrasts

- **P1 − P0:** effect of lossless pacing.
- **P2 − P1:** effect of fair service under the same token policy.
- **P3 − P2:** additional effect of latest-update coalescing.
- **P3 − P0:** practical total policy effect.

The primary confirmatory comparison is P3−P0 at near-transition load for the frozen freshness outcome, interpreted jointly with the prespecified completeness/cost requirement. Mechanism contrasts remain visible even when designated secondary.

If coalescing accounts for the observed improvement, do not describe the result as a novel pacing algorithm effect.

## Qualification

Before physical confirmation, deterministic fixtures must establish:

- token conservation and burst limits;
- nonnegative causal release lag;
- FIFO order where required;
- at most one pending latest update per sensor in P3;
- protection against out-of-order generation replacement;
- no retraction of inflight publications;
- fair eventual service under the declared scheduler;
- exact accounting after overflow, disconnect, and drain;
- future-suffix independence of earlier policy decisions.

Publisher/collector capacity must also be qualified so an artificial Python/client bottleneck is not mistaken for a network-policy benefit.

## Analysis and falsification

Source realization is the independent scientific unit, with physical session retained as a block where appropriate. Use paired policy differences and report uncertainty for all primary outcomes and costs.

A policy is useful only when it meets the declared practical trade-off. Freshness improvement accompanied by unacceptable sample loss is a trade-off, not unconditional success.

Important null/negative outcomes include:

- pacing merely moves delay into the gateway and does not improve end-to-end freshness;
- fairness changes which sensors are served without improving aggregate utility;
- coalescing helps only under a narrow overload regime;
- the qualified physical transport already has enough capacity that no mitigation is needed;
- a benefit disappears when publisher/collector limitations are removed.

Held-out load/source-shift results must be reported regardless of direction.

## Reproducibility and evidence

Retain source bundles, policy manifest, frozen parameters, accepted deployment identity, UE/interface binding, background-workload identity, run order, clock evidence, event-level policy dispositions, resource observations, exclusions, and analysis outputs.

Shared timestamp, receipt, AoI, clock, experimental-unit, and failure-taxonomy conventions are defined in [`../MEASUREMENT_AND_INFERENCE.md`](../MEASUREMENT_AND_INFERENCE.md).

## Completion criteria

The experiment is complete when:

1. policy implementations satisfy the causal and accounting qualification fixtures;
2. pilot-selected parameters and confirmation design are frozen prospectively;
3. every decoded gateway input reconciles to a retained final disposition;
4. every assigned physical run has a documented disposition;
5. freshness, completeness, fairness, latency, and byte/resource costs are analyzed together with uncertainty;
6. the final conclusion states the application semantics, operating region, measured benefit/cost, and observed failure boundary without extrapolating beyond the tested system.
