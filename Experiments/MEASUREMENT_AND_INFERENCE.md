# Shared measurement and inference contract

This document defines conventions reused by SynthRAN experiments that replay decoded Ambient-IoT events through an application transport path. A study may impose stricter requirements; its experiment-specific design remains authoritative where the two differ.

## Event identity and timestamps

Each event retains stable scientific identity and timing fields sufficient to distinguish source generation, modeled reader availability, publisher scheduling, broker acknowledgement, and application receipt. At minimum retain:

- `event_id` and sensor identity;
- generation sequence and modeled generation time `g`;
- completed modeled reader-decode time `d` where applicable;
- gateway/connection assignment and payload hash;
- planned replay release `s`;
- timestamp immediately before publication `p`;
- MQTT PUBACK callback time `a` when QoS 1 is used;
- receiving-application callback entry time `r`.

Preserve modeled generation time across retransmission and forwarding. Record monotonic timestamps for local interval calculations and retain the UTC/monotonic anchor required to interpret cross-host evidence. Any packet-capture, broker-ingress, or additional wire timestamp must be named by the point at which it is measured rather than treated as an interchangeable latency marker.

## Transport outcomes

For an expected event:

- `p - s` is publisher release error, including intentional gateway holding when the policy permits it;
- `r - p` is application delivery latency after publication and may include client queueing, network transport, broker processing, and subscriber delivery;
- `r - s` is scheduled-release-to-application delay and exposes both publisher lateness and downstream delivery delay;
- deadline failure is the fraction of expected events not received by `s + D`, where `D` is frozen from an application requirement or independent pilot.

Delay quantiles are conditional on receipts observed by the declared drain deadline. Missing events are not assigned zero delay and are retained in deadline/failure accounting. When no qualifying receipts exist, a delay quantile is undefined.

MQTT QoS 1 PUBACK is evidence of the client-to-broker delivery exchange; it is not evidence that the receiving application callback occurred. Unique application receipts, duplicates, publication failures, late receipts, intentional discards, and events still outstanding at drain are recorded separately when relevant to the study.

## Cohort, warm-up, and drain

The expected transport cohort comprises events whose planned releases fall inside the frozen measurement window. Warm-up events may establish state and remain traceable but are not silently added to the measurement denominator.

The receiver, established connections, and declared competing traffic remain active through a fixed drain long enough to classify the study's deadline outcome. No new victim releases are introduced after the measurement horizon merely to improve completion statistics.

## Age of Information

For sensor `j`, the information age at time `t` is based on the freshest **generation timestamp** among updates received by `t`:

\[
\Delta_j(t)=t-\max\{g_{j,k}^{wall}:r_{j,k}\le t\}.
\]

An older out-of-order receipt never moves the freshness state backward. Time-average AoI is obtained from the age process over the declared observation window; time-weighted tails, time above a frozen freshness limit, and age immediately before freshness-improving receipts may be reported as study outcomes.

`r-g` for one delivered packet is its age at delivery, not the time-average AoI or peak-AoI process. Sensors without initialized received history must remain visible. Unknown initial age is not set to zero or backdated to the first receipt. Any statistic restricted to initialized intervals is labeled conditional and accompanied by the uninitialized-time fraction or the study's explicit alternative convention.

Timing transformations that can move replay release before modeled generation cannot support the same physical generation-based AoI interpretation. Such arms must honor their declared `generation_age_valid` or equivalent contract.

## Clock evidence

Cross-host timing claims require evidence that clock uncertainty is small relative to the claimed effect. Retain synchronization state and a quantitative endpoint uncertainty/error bound when the experiment relies on absolute cross-host timestamps.

A configured NTP/PTP service or common wall-clock start is not, by itself, evidence of the required bound. If clock evidence is inadequate, restrict interpretation to same-clock measurements and count outcomes rather than clipping or repairing invalid negative cross-host latencies.

## Publisher and collector qualification

Publisher and collector capacity must be qualified above the study's tested event rate on an appropriate local/wired path. Record processing load, queue/inflight behavior, scheduling error, and readiness barriers where these can influence the treatment.

Use append-only run evidence, unique run identity, bounded queue/inflight behavior, a subscription-ready barrier, and consistent warm-up/drain rules. Failed attempts remain distinguishable from accepted runs.

## Statistical unit and pairing

The independent scientific unit is normally the independent source realization/seed, with session/day or configuration block retained when it can introduce shared drift. Packets, sensors within the same source realization, time windows, repeated replays, and multiple surrogate transformations of one source trace are not automatically independent replicates.

Use paired run-level effects for matched interventions. Repeated surrogate/control realizations belonging to the same source are combined or modeled within that source before source-level resampling unless the study prespecifies another justified repeated-measures model.

Primary contrasts, sample size or precision target, exclusions, and practically meaningful effect criteria are frozen after independent pilot/calibration work and before confirmation. Confirmation is not extended selectively because a result appears promising.

## Failure and exclusion taxonomy

At minimum distinguish:

- invalid or missing measurement-system evidence;
- deployment/configuration incompatibility;
- genuine service failure or overload under the assigned treatment;
- intentional policy discard/suppression;
- censored/late receipt at the fixed drain;
- undefined metrics caused by a silent or zero-denominator realization.

These categories have different scientific meanings and must not be merged merely to simplify analysis.

## Claim boundary

End-to-end application measurements establish end-to-end outcomes. Attribution to radio scheduling, core transport, MQTT/broker behavior, publisher capacity, or host processing requires aligned evidence from that layer.

Physical 5G transport measurements do not validate the modeled Ambient-IoT harvesting, propagation, collision, or decoding process. Conversely, modeled Ambient-IoT improvements do not establish downstream application improvement without a corresponding transport experiment.

Every reported result should state the tested software revision, frozen design, source cohort, deployment identity when physical, observation horizon, treatment definition, exclusions, and uncertainty. Implemented capability and test coverage are prerequisites for research, not substitutes for measurement.