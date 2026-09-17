# Experiment 3: MAC/SIC improvements versus delivered freshness

## Objective

Determine whether a MAC or receiver configuration that increases decoded Ambient-IoT traffic also improves freshness at the final application, or whether the additional traffic and burst structure can create a downstream penalty near a 5G transport limit.

The central contribution is not simply that SIC can decode more packets. The study asks whether a locally improved reader-side outcome changes the end-to-end application ranking once energy cost, contention, transport load, and information freshness are considered together. Availability-aware access and energy-neutral/delay-oriented MAC design already have relevant prior work; see [Wu et al.](https://arxiv.org/abs/2501.15020) and [HENO-MAC](https://arxiv.org/abs/2401.00717).

## Scope and claim boundary

Ambient-IoT harvesting, capacitor behavior, access, propagation, collision, and decoding are modeled. Physical replay, when used, evaluates the resulting decoded workload over an accepted 5G gateway transport path. A physical N320 transport does not make the upstream Ambient-IoT radio process physical.

Reader-side improvements and application-level improvements are therefore distinct outcomes. A higher decode count is not sufficient evidence of improved application freshness, and an end-to-end latency change does not by itself identify the radio scheduler as the cause.

## Research questions and hypotheses

- **M1:** Qualified SIC increases unique decoded-update rate under shared-subcarrier contention for some power-disparity and population regimes.
- **M2:** Increased reader-side success does not necessarily produce a proportional improvement in final-application freshness near a transport service limit.
- **M3:** An availability-aware or adaptive access policy can trade command, airtime, and energy overhead against collision reduction and freshness.

M2 explicitly permits a null or monotonic benefit. The design must not require a paradoxical ranking reversal in order to be considered informative.

## Methodological prerequisites

Before scientific confirmation, the receiver/controller/protocol implementation must satisfy retained qualification checks covering:

- analytical two- and three-packet SIC fixtures;
- zero, intermediate, and perfect cancellation behavior;
- equal-power failure/capture cases;
- singleton sensitivity/SINR cases;
- packet/slot-edge overlap semantics;
- complete transmission-energy accounting;
- power-gated control-message handling;
- frame-local collision/occupancy observations for adaptive policies;
- stable sample identity across retransmission and decoding stages.

A MAC retransmission must not become a new sensed update. Packet airtime must fit the declared slot model, and the primary contention study uses one reader with an explicit shared subcarrier.

## Fair-comparison design

Freeze sensor positions, input-energy realizations, sensing opportunities, numerical timestep, observation horizon, payload/sample semantics, channel parameters, and receiver noise within matched comparisons. Use separate seeded streams for exogenous energy/geometry/sensing and for policy randomness so a protocol change does not implicitly change all upstream random inputs.

The initial scheme set is:

| Scheme | Access/receiver | Role |
| --- | --- | --- |
| B0 | Fixed framed broadcast; no SIC, capture only | Primary baseline |
| B1 | Identical framed broadcast; qualified imperfect SIC | Primary comparison |
| B2 | Identical broadcast; perfect cancellation | Idealized upper-bound reference |
| A1 | Frame-local adaptive framed ALOHA with the same imperfect SIC model | Practical protocol alternative |
| U1 | Unicast polling with exclusive response slots | Orthogonal scheduled-access control |

For B0/B1/B2, preserve the same attempts and slot choices when receiver feedback does not alter behavior. For closed-loop policies, preserve the same exogenous realizations and record policy-mediated attempt differences rather than forcing physically different protocols into identical trajectories.

A1 should use observations a real reader could obtain, such as occupied/idle/undecodable slot outcomes or an explicitly modeled estimator. An oracle that reads simulator-only collision identities is an upper-bound policy and must be labeled as such.

Compare schemes over equal elapsed time with complete command, receive, transmit, and listening energy accounting. Differences in frame length or control overhead are part of the intervention and remain visible.

## Model campaign

Use independent pilot seeds to locate low-contention, transition, and high-contention populations (`N-low`, `N*`, `N-high`) under a stable PHY power-disparity profile.

At each population, compare E-knee independent and common harvesting. A planning confirmation design is:

```text
20 source seeds
× 3 population levels
× 2 energy-dependence regimes
× 2 primary schemes (B0, B1)
= 240 model runs
```

At `N*`, evaluate B2/A1/U1 for the same source seeds and both energy regimes, adding 120 model runs. The final confirmation size must be frozen from measured runtime and precision requirements rather than expanded in response to observed effects.

A cancellation-quality sensitivity may use a small prespecified set such as 0, 0.5, 0.9, and 1 under the explicit semantics “fraction of interference power removed.” These are model settings, not measured hardware residuals.

## End-to-end replay subset

Use a prespecified source subset for B0/B1 at `N*`, both E-knee dependence regimes, and low/near-limit competing 5G load. A planning matrix with ten source seeds is:

```text
10 source seeds
× 2 MAC/receiver schemes
× 2 energy-dependence regimes
× 2 competing-load levels
= 80 physical replays
```

Each scheme's **natural decoded output** is the primary system-level treatment. Different decoded event counts are therefore part of the MAC effect and must not be mislabeled as equal offered load. Do not restrict analysis to the intersection of packets decoded by both schemes, because that preferentially removes the very successes produced by the intervention.

For mechanism diagnosis, construct native-versus-periodic timing controls separately inside each scheme's event set. A transport-rate-normalized sensitivity may also be useful, but it is a different intervention from the total MAC effect.

## Outcomes

Retain, at minimum:

- generated updates and energy/busy suppressions;
- transmission attempts, retries, airtime, and command overhead;
- unique decodes, receiver failure causes, and SIC cancellation stages;
- energy per generated and decoded update;
- per-sensor decode probability, starvation intervals, and fairness including never-decoded sensors;
- reader-side and application-side AoI/freshness-violation outcomes;
- decoded rate and burst structure;
- publisher release error, delivery by deadline/drain, and relevant network/resource evidence.

Primary paired contrasts are B1−B0 for unique reader decode rate and for a prespecified application-freshness outcome. Report both layers together with uncertainty.

A ranking reversal is supported only when the same operating point shows a credible reader-side improvement and a credible downstream deterioration under the frozen outcome definitions. Higher conditional latency among delivered packets alone is insufficient because a better receiver can admit packets that were previously absent from the sample.

## Analysis and falsification

Treat source realization/seed as the independent scientific unit and retain session/configuration blocking for physical replay. Report paired run-level effects with confidence intervals.

- If B1 improves both reader and application outcomes, quantify the benefit and operating region.
- If B1 improves reader decoding but not application freshness, quantify the decoupling rather than forcing a reversal claim.
- If only the idealized B2 receiver helps, constrain practical conclusions accordingly.
- If A1 requires oracle information, keep its result as an upper bound until an observable policy is evaluated.

The experiment does not establish that SIC, MAC adaptation, or any transport mechanism is universally beneficial. Claims remain conditional on the modeled energy/channel process, tested population/receiver parameters, accepted transport deployment, and observation horizon.

## Reproducibility and evidence

Retain the frozen scientific design, source bundles, protocol/receiver configuration, implementation/dependency fingerprint, per-run evidence, exclusions, and analysis outputs. Physical runs also retain accepted deployment identity, UE binding, clock evidence, background-load realization, and experiment-time transport observations.

Shared timestamp, receipt, AoI, clock, experimental-unit, and failure-taxonomy conventions are defined in [`../MEASUREMENT_AND_INFERENCE.md`](../MEASUREMENT_AND_INFERENCE.md).

## Completion criteria

The study is complete only when:

1. receiver/MAC qualification fixtures pass under the exact implementation used for confirmation;
2. pilot-selected operating points and confirmation seeds are frozen prospectively;
3. every assigned confirmation run has an explicit disposition;
4. reader-side and application-side outcomes are analyzed together with uncertainty;
5. source, protocol, deployment, and measurement provenance are sufficient to reproduce every reported contrast;
6. limitations and unresolved mechanism attribution are reported rather than filled from assumptions.
