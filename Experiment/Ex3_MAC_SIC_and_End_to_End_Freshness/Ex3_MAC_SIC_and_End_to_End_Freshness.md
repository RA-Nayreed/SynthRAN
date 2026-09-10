# Experiment 3: MAC/SIC improvements versus delivered freshness

## Objective and publication role

Determine whether a MAC or receiver that increases decoded Ambient-IoT traffic also improves freshness at the final application, or whether the additional traffic/burst structure creates a downstream penalty near a 5G transport limit.

The study is technically feasible after receiver, controller and protocol corrections. Its ambitious version tests **whether a locally better MAC has a different end-to-end ranking**. A plot showing that ideal SIC decodes more packets is a qualification result, not sufficient novelty. Availability-aware access already has close prior work in [Wu et al.](https://arxiv.org/abs/2501.15020), and energy-neutral/delay-oriented MAC design in [HENO-MAC](https://arxiv.org/abs/2401.00717).

## Context for a fresh ChatGPT session

Use this file as a standalone experiment brief for **RA-Nayreed/SynthRAN**. Read the current relevant source before changing or running anything. The review baseline was `main` at `ccaa385174fa695bdaa669e6046b61e80283a0be`, inspected on **8 September 2026**. The physical N320 candidate was draft PR [#7](https://github.com/RA-Nayreed/SynthRAN/pull/7), head `21d0dddb2792a004e529afc3144ab7aaa1eea941`. Its prose mentioned an older hash; the API head was authoritative. Recheck the current revision and retain improvements already present.

SynthRAN executes an Amber-derived SimPy model of energy harvesting, capacitor/controller operation and backscatter access. It freezes decoded events into JSONL, then replays them over MQTT through an actual 5G UE interface to an N6-side application. The Ambient-IoT radio and harvesting are **modeled**. The N320 carries the **5G gateway transport**; it does not make the upstream Ambient-IoT link a physical implementation.

The revised campaign uses **one fixed OAI core + srsRAN gNB + N320 physical-radio configuration**, after a clean acceptance run. This choice follows the repository's active physical reference. It replaces the attachment's Open5GS/RFSIM choice once, before data collection; it introduces no core comparison. RFSIM with the same core is useful for qualification. Its different UE software, band, numerology and image mean its measurements must be analyzed separately. If an already accepted Open5GS/N320 deployment is used instead, freeze that choice before the pilot and revise the manifest consistently; do not mix cores in a result series.

Use a homogeneous slice/DNN/QoS assignment except in the explicit isolation study. The shipped default profile assigns `uesim01` and `uesim02` to different slices, so it is not an appropriate neutral baseline. Begin with two proven physical UE roles: gateway A and competing-traffic UE B. Use only the N320 for physical-radio studies. Node availability and runtime capability require live evidence; scenario examples are not proof.

Complete the necessary model and instrumentation corrections, produce runnable scenario/analysis/campaign files, run qualification and then the declared experiment where resources are available. If physical access is absent, complete all local work and give the exact remaining live commands with their acceptance criteria. Report preparation, simulated results and physical measurements separately. At the end of every working session, retain a concise checkpoint with the actual commit, completed gates, artifact paths/hashes, failures and the next executable step. This file does not require any other handoff file to be understood.

## Questions and hypotheses

- **M1:** Qualified SIC increases unique decoded update rate under shared-subcarrier contention for some power-disparity/population regimes.
- **M2:** Increased reader-side success does not necessarily yield proportional improvement in final-application freshness near transport saturation.
- **M3:** An availability-aware/adaptive access policy can trade command/airtime/energy overhead against collision reduction and freshness.

M2 permits a null or monotonic benefit. Do not design the experiment to require a paradoxical ranking reversal.

## Code and acceptance requirements

Read `Experiment/model/{packet_analysis,bsengine,backscatter,controller,capacitor}.py`, `Experiment/ambient_iot/{protocols,runner,bridge,evidence,outcomes}.py`, the protocol examples, and the replay/reconciliation path.

The reviewed `apply_sic()` removed a decoded signal from the set contributing interference, making `cancellation_factor` ineffective. `adaptive_aloha()` compared cumulative historical collision counts with current-frame decodes. Decoding labels were reconstructed from packet records rather than retained per cancellation stage. Transmission was delivered before its later energy-draw phase was complete, and control-message handling was not gated by actual power state. Resolve these problems before calling a scheme energy-aware or SIC-qualified.

Use analytical two- and three-packet SIC fixtures, zero/intermediate/perfect cancellation, equal-power failure/capture cases, singleton sensitivity/SINR cases and packet/slot-edge overlap fixtures. Distinguish radio reception, decoding success and sample identity. A MAC retransmission must not become a new sensed update.

The primary model should have an explicit packet airtime no longer than its allowed slot, consistent energy consumption, sensing-period/phase semantics and a valid channel domain. Use one reader and an explicit common subcarrier. Retain complete frame-local attempts, empty/collision/success observations and receiver decision stages.

## Fair comparison design

Freeze sensor positions, input energy realizations, sensing opportunities, numerical timestep, observation horizon, payload/sample semantics, channel and receiver noise. Use separate seeded streams for exogenous energy/geometry/sensing and policy randomness. Merely passing the same global seed to protocols that consume random numbers differently does not hold exogenous conditions fixed.

Start with these schemes:

| Scheme | Access/receiver | Role |
| --- | --- | --- |
| B0 | Fixed framed broadcast; no SIC, capture only | Primary baseline |
| B1 | Identical framed broadcast; qualified imperfect SIC | Primary comparison |
| B2 | Identical broadcast; perfect cancellation | Idealized receiver upper-bound reference |
| A1 | Frame-local adaptive framed ALOHA with the same imperfect SIC model | Practical protocol alternative |
| U1 | Unicast polling with exclusive response slots | Orthogonal scheduled-access control |

For B0/B1/B2, keep the same attempts/slot choices when receiver feedback does not affect behavior. If the corrected protocol adds success feedback/retries, preserve the same exogenous realizations and describe the policy-mediated differences. Do not force physically different closed-loop protocols to produce identical attempts.

A1 must adapt using observations a reader could actually obtain. A simulator knows every colliding node; a practical reader may know only an undecodable/occupied slot. State whether the policy uses observable slot outcomes, an estimated backlog or an ideal oracle. Use observable slot outcomes for the main practical claim. Record adaptation lag, false occupancy decisions and frame-size limits where modeled.

U1 and A1 can have different frame lengths and control overhead. Compare over equal elapsed time and with complete command/receive/transmit energy and airtime accounting. A throughput gain achieved by giving one scheme more airtime or neglecting its listening cost is not a fair efficiency gain.

## Model campaign

First locate `N-low`, `N*` and `N-high` on a contention curve using independent pilot seeds. Keep a stable PHY power-disparity profile; a secondary homogeneous versus near-far profile can identify where SIC benefits originate. Do not vary geometry, density, SIC quality and energy in one unexplained sweep.

At each of the three populations, use E-knee independent and common harvesting. Suggested primary confirmation: 20 independent seeds × 3 populations × 2 energy-dependence arms × 2 primary schemes = **240 model runs**.

At `N*` only, evaluate B2/A1/U1 for the same 20 seeds and two energy arms = **120 additional model runs**. This totals 360 model runs before pilots. Benchmark model time/memory first and freeze a feasible number using precision targets, not effect-driven expansion.

A limited cancellation-quality sensitivity at `N*` may use 0, 0.5, 0.9 and 1 with the semantics “fraction of power removed.” The values are illustrative model settings, not measurements of a hardware SIC receiver. Estimate realistic residuals from external measurements/literature if making quantitative hardware predictions.

## End-to-end subset

Use a prespecified subset of ten source seeds for B0/B1 at `N*`, common and independent E-knee harvesting, and low/near-knee competing 5G load. This gives `10 × 2 × 2 × 2 = 80` physical replays. Use the fixed N320 gateway path, real-time native release, identical background workload per matched block, neutral slice and a qualified publisher/collector. These are separate source traces because the MAC changes which updates decode.

Compare each scheme's **natural decoded output** first. Different event counts are part of the MAC's total system effect. Do not describe this comparison as equal offered load. Do not restrict evaluation to the intersection of decoded packets: that preferentially selects easy successes and discards the very improvement under study.

For mechanism diagnosis, construct native-versus-periodic timing controls separately within each scheme's event set. This equal-event comparison estimates that scheme's timing penalty. A transport-rate-normalized sensitivity can additionally be useful, but it changes the intervention and must be named separately from the total MAC effect.

## Metrics and analysis

Record:

- Generated updates and energy/busy suppressions; attempted transmissions and retries.
- Unique decodes, receiver failure causes and actual cancellation stages.
- Energy per generated/decoded update, command overhead, occupied/idle slots and useful updates per airtime.
- Per-sensor decode probability, starvation intervals and fairness; include never-decoded sensors.
- Reader-side and final-application AoI, freshness-violation time and deadline utility per sensor.
- Natural decoded rate/burst structure, publisher release error, delivery by deadline/drain, and network/resource usage.

Compare paired run-level outcomes with source seed as the independent block. Primary contrasts are B1−B0 for unique reader decode rate and final-application time-average AoI/violation time. Use confidence intervals and report both layers together. A descriptive trade-off plot should show all schemes' freshness versus consumed energy and transport bytes.

Call a ranking reversal only when the data support a better upstream metric and a worse downstream utility at the same declared operating point with meaningful uncertainty. A higher conditional latency among delivered packets alone is insufficient: more successful delivery can legitimately add previously difficult packets to the sample. AoI across the full fixed population and deadline utility address this selection issue.

If improved SIC simply improves both reader and application outcomes, quantify the benefit and operating range. If only the idealized receiver helps, delimit the practical claim. If A1 uses oracle collision counts, classify it as an upper-bound simulation policy until an observable policy is evaluated.

## Figures and completion

Produce paired decode/freshness comparisons; cancellation-stage examples for prespecified fixtures; contention-response curves; a reader-versus-application utility plot; and energy/airtime/transport-cost trade-offs. Retain the complete source bundles and exact protocol policies so a new session can reproduce both the local MAC result and its downstream effect.

## Measurement and inference contract

For each event retain a stable `event_id`, `sensor_id`, generation sequence, modeled generation time `g`, completed reader-decode time `d`, gateway assignment and payload hash. Preserve the modeled generation time across retransmission and forwarding. Record planned replay release `s`, the timestamp immediately before calling MQTT publish `p`, PUBACK callback `a`, and receiving-application callback entry `r`. Record monotonic times and the UTC/monotonic anchor; use UTC only for verified cross-host comparisons. An optional packet capture or broker hook supplies an explicitly named wire/broker-ingress time.

- `p - s`: publisher release error, including any intentional gateway hold when applicable.
- `r - p`: application delivery latency, including client queuing, transport, broker and subscriber delivery. It is not isolated radio latency.
- `r - s`: scheduled-release-to-application delay. Report this as well, so delayed publication cannot conceal degradation.
- Deadline failure: fraction of expected events not received by `s + D`, including missing events; freeze `D` from an application requirement or an independent pilot.
- Report p50/p95 and deadline failures as primary practical outcomes. Treat p99 as secondary until the run has enough observations. A target of 10,000 delivered events gives about 100 observations in the upper 1%, but dependence can still make its interval wide.

The expected transport cohort comprises events whose planned releases fall in the fixed measurement window. Warm-up events establish state and remain traceable but are excluded from that cohort's delivery denominator. Keep the receiver, established connections and declared competing traffic active through a fixed drain at least as long as `D`; introduce no new post-window victim releases. Compute AoI only over the declared measurement window. Label delay quantiles as conditional on receipts observed by the drain and report unresolved/censored events beside them. With no receipts, a delay quantile is undefined, not zero. The all-input deadline-failure outcome prevents selective survival from hiding overload.

QoS 1 uses PUBACK for its client-to-broker delivery exchange. A PUBACK does not prove the subscriber callback occurred. Count unique application receipts, duplicates, publication failures, late receipts, and still outstanding messages at the fixed drain deadline separately. Do not label an absent callback a physical packet loss. See the [MQTT 3.1.1 specification](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html).

True per-sensor AoI at observation time `t` is

\[
\Delta_j(t)=t-\max\{g_{j,k}^{wall}:r_{j,k}\le t\}.
\]

Use the freshest received generation timestamp, so a duplicate or an older out-of-order update never resets AoI backward to older information. Integrate the sawtooth over a fixed observation window for time-average AoI; calculate time-weighted AoI quantiles, time above the AoI limit, and age immediately before each freshness-improving receipt for peak-AoI statistics. `r-g` for an individual delivered packet is its age at delivery, not the time-average or peak AoI. This distinction follows [Yates et al., Age of Information: An Introduction and Survey](https://arxiv.org/abs/2007.08564).

For native replay at real-time scale, map `g_wall = replay_epoch + g_model_seconds` using the same origin for decode and generation times. Replay the retained warm-up history before the measurement window. If a sensor has no received history, report its uninitialized interval and count it as violating the freshness requirement; do not remove it from the population. Report equal-weight per-sensor outcomes as well as aggregate traffic-weighted outcomes.

Never initialize unknown age to zero or backdate the first receipt. A full-window mean AoI is not identifiable during unknown initial history, or is infinite under an explicitly chosen infinite-age convention. Report any mean over initialized intervals as conditional, alongside the uninitialized-time fraction. The all-sensor freshness-violation metric includes those intervals. For surrogates that move release before generation, physical generation-based AoI is not a valid outcome.

Clock uncertainty must be small relative to the claimed effect. Record synchronization evidence before and after each block and throughout long blocks. Use a combined endpoint error budget `epsilon`; target `epsilon` below one fifth of the smallest claimed latency difference. A shared UTC start or an installed PTP role is insufficient evidence. If synchronization is inadequate, repair it or limit claims to same-clock ACK timing and count metrics. Never clip negative cross-host latencies into valid data.

Qualify the publisher and collector with the same workload over a fast local/wired path. Their processing capacity must exceed the tested application event rate, and their queues, CPU load and scheduling errors must be measured. Timestamp callback entry before parsing/writing. Use append-only records, a subscription-ready barrier, fixed warm-up and drain rules, unique run identity, and queue cleanup between independent replays.

The independent scientific unit is a source realization/seed, with session/day as a block. Packets, two permutations of one trace, and repeated replays are not independent source replicates. Use paired run-level differences and confidence intervals; average repeated surrogate outcomes within source/load before source-level inference. Resample independent source blocks with session structure preserved, or fit a justified repeated-measures model. Freeze primary contrasts, practically meaningful effect size, sample size and exclusions after the independent pilot. Never select visually representative seeds or extend only promising conditions. Missing data due to an invalid measurement system and real overload failures require different labels.

## Required session outputs

Deliver the resolved experiment manifest, runnable campaign and analysis commands, qualified scenario files, immutable input traces with checksums, an outcome table, figures with uncertainty, and a short findings document that answers the hypotheses. Retain per-run publication/receipt evidence and all prespecified exclusions. Include actual software/image versions, mapping, hardware state, clock evidence, timing policies and observation/drain windows in the manifest. Proposed capabilities must be implemented and checked before being described as available commands. Finish with a checkpoint another ChatGPT session can continue without reconstructing the previous conversation.
