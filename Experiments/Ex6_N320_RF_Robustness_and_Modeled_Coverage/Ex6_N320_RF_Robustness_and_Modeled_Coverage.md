# Experiment 6: N320 RF robustness and modeled Ambient-IoT coverage

## Objective and publication role

Determine whether the flagship's traffic-structure effect persists across measured 5G radio conditions, and identify the link conditions under which the gateway stops meeting its delivery/freshness requirement. Treat modeled Ambient-IoT reachability as a separate, optional study with its own assumptions and evidence.

A robustness study is feasible after the N320 path is accepted. A calibrated physical coverage claim additionally requires measured positions or a characterized attenuation setup. This is primarily external-validity evidence for the main paper. An uncalibrated path-loss sweep or a plot of distance against MQTT delay has limited standalone publication value.

## Context for a fresh ChatGPT session

Use this file as a standalone experiment brief for **RA-Nayreed/SynthRAN**. Read the current relevant source before changing or running anything. The review baseline was `main` at `ccaa385174fa695bdaa669e6046b61e80283a0be`, inspected on **8 September 2026**. The physical N320 candidate was draft PR [#7](https://github.com/RA-Nayreed/SynthRAN/pull/7), head `21d0dddb2792a004e529afc3144ab7aaa1eea941`. Its prose mentioned an older hash; the API head was authoritative. Recheck the current revision and retain improvements already present.

SynthRAN executes an Amber-derived SimPy model of energy harvesting, capacitor/controller operation and backscatter access. It freezes decoded events into JSONL, then replays them over MQTT through an actual 5G UE interface to an N6-side application. The Ambient-IoT radio and harvesting are **modeled**. The N320 carries the **5G gateway transport**; it does not make the upstream Ambient-IoT link a physical implementation.

The revised campaign uses **one fixed OAI core + srsRAN gNB + N320 physical-radio configuration**, after a clean acceptance run. This choice follows the repository's active physical reference. It replaces the attachment's Open5GS/RFSIM choice once, before data collection; it introduces no core comparison. RFSIM with the same core is useful for qualification. Its different UE software, band, numerology and image mean its measurements must be analyzed separately. If an already accepted Open5GS/N320 deployment is used instead, freeze that choice before the pilot and revise the manifest consistently; do not mix cores in a result series.

Use a homogeneous slice/DNN/QoS assignment except in the explicit isolation study. The shipped default profile assigns `uesim01` and `uesim02` to different slices, so it is not an appropriate neutral baseline. Begin with two proven physical UE roles: gateway A and competing-traffic UE B. Use only the N320 for physical-radio studies. Node availability and runtime capability require live evidence; scenario examples are not proof.

Complete the necessary model and instrumentation corrections, produce runnable scenario/analysis/campaign files, run qualification and then the declared experiment where resources are available. If physical access is absent, complete all local work and give the exact remaining live commands with their acceptance criteria. Report preparation, simulated results and physical measurements separately. At the end of every working session, retain a concise checkpoint with the actual commit, completed gates, artifact paths/hashes, failures and the next executable step. This file does not require any other handoff file to be understood.

## The two links have different evidence

| Link | What SynthRAN supplies | Defensible outcome |
| --- | --- | --- |
| Modeled sensor to modeled Ambient-IoT reader | A simulated energy/controller/backscatter/channel process; the reference uses a separate approximately 924-MHz model | Coverage or service probability conditional on the stated model and its validation |
| Physical gateway UE to srsRAN gNB/N320 | An actual 5G transport path; the inspected N320 reference uses n78, 20 MHz and 30-kHz subcarrier spacing | Measured transport robustness under the recorded physical conditions |

Do not equate these links, frequencies or distances. A successful MQTT receipt over the N320 does not validate the modeled sensor's RF link budget. RFSIM cannot supply physical RF coverage evidence.

## Questions and primary hypotheses

- **F1:** At a fixed offered competing rate, weaker measured 5G uplink conditions change delivery/freshness outcomes and may amplify the penalty of native bursts relative to an event-identical periodic control.
- **F2:** Some apparent RF effects can be explained by the change in available service capacity. A capacity-normalized secondary comparison tests what remains after adjusting operating load.
- **F3, optional modeled extension:** Ambient-IoT service probability depends jointly on the modeled energy margin, command reception, backscatter reception and contention; a sensitivity-only range limit is insufficient.

F1 does not assume monotonic latency among successful packets: weak conditions can selectively remove slow/difficult traffic. Include deadline failures, outage intervals and all-sensor freshness.

## Code and physical acceptance

Inspect `scenarios/r2lab-reference-oai-srsran.yml` on the physical candidate, N320/RAN deployment inputs, the actual rendered gNB configuration, UE session/attestation evidence, `Experiment/workload/replay.py`, and the MQTT role that launches it. In draft PR #7, the secondary-DNN MBIM path could attest `wwan0.1`, while the unchanged replay task still selected `wwan0`. Bind the publisher to the attested data interface and source address; prove that packets reach the intended user-plane path.

The inspected upstream N320 values specified n78/20 MHz/30 kHz, a 61.44-Msample/s setting, transmit/receive gains of 35/60, internal clock/synchronization and image tag `r2labuser/srsran-gnb-uhd:v1.0`. These are provenance facts about a reference file, not instructions to assume the live hardware has that state or to vary those values blindly. Record the runtime image digest and rendered parameters. The source was [the pinned N320 values](https://github.com/turletti/srsran-helm/blob/8dfb9890d127734cdcd6eee9df8c5d09b1a8076a/charts/srsran-gnb/values-n320-n78-20MHz.yaml); verify the actual deployed upstream revision before execution.

Require stable registration, the expected PDU session/DNN/S-NSSAI, a reachable receiving application and a correctly bound publisher. Retain per-run RF and network telemetry with timestamps. An accepted attachment at good RF is only the first gate; weak-RF treatment failures must be classified against the prespecified service definition.

Freeze core, RAN version, channel bandwidth, numerology, scheduler policy, TDD configuration, UE hardware/firmware, power-control configuration, antenna arrangement and N6/application placement. Keep source traffic and subscriber behavior fixed. The gateway and competitor should have homogeneous QoS in the primary campaign.

## Establish actual RF-control capability

Before selecting treatments, inventory what can physically be controlled in the allocated setup:

| Available capability | Procedure | Claim boundary |
| --- | --- | --- |
| Characterized conducted path with suitable controllable attenuation | Measure/record attenuation and path arrangement, use the established equipment procedure, and randomize attenuation blocks | Causal effect of the specified path attenuation within that setup |
| Controlled over-the-air positioning | Record positions, orientation, environment and repeated channel measurements; balance positions over session/time | Effect of the specified placement intervention, including its propagation consequences |
| Fixed remote UE positions without a controllable path | Record naturally observed channel state and repeat paired workloads across sessions | Conditional robustness across observed RF states; no claim that RF was randomized |

Do not assume a programmable attenuator or remotely movable modem exists. Do not simulate attenuation by silently changing gains or by dropping packets in software and call it physical coverage. In particular, gNB transmit gain changes the downlink, and receiver gain is not calibrated uplink path loss. Any gain sensitivity is a separately named intervention.

Select **good, transitional and weak-but-operational** RF levels in an independent pilot using the actual uplink evidence and service behavior. Use measured ranges and distributions, rather than invented universal SINR thresholds. Collect uplink PUSCH SINR/BLER and retransmission information where the running stack exposes them. UE-reported RSRP and many UE SINR values describe downlink reception; label their direction and source instead of using them as direct uplink measurements. Record cell load, UE transmit-power indicators where available, throughput, queue/backlog evidence, CPU and outages.

For a coverage requirement that includes initial access, registration failures at an assigned position/attenuation are genuine failures. For an already-connected transport requirement, treat access success and subsequent service separately. Do not remove bad-RF outcomes merely because the UE detached. A failed logging/clock system is a measurement failure and is labeled separately.

## Workload and campaign

Use ten prespecified common-harvesting E-knee source realizations from the qualified model, native time scale, the same sensor-to-gateway mapping and the same serialized events. The primary timing comparison is native versus periodic. Periodic release spans the first and last native release with exactly the same event count, bytes, order, topics, fixed horizon and unchanged warm-up. It is a timing intervention; it cannot automatically inherit the native physical generation-age interpretation.

Calibrate the usable service rate with the qualified transport path at good RF. Freeze two competing offered rates: low and near the good-RF operating knee. Keep those **absolute offered rates** unchanged across RF levels for the main question. Measure actual offered and delivered background rate; a nominal target is not evidence of the load reached. A lower-capacity RF level may become overloaded at the fixed background rate. That is part of this intervention and must be visible in backlog, failures and drain outcomes.

The primary confirmation matrix is:

| Factor | Levels |
| --- | --- |
| Independent source seeds | 10 |
| Timing | Native, periodic |
| Measured physical RF treatment | Good, transitional, weak-but-operational |
| Competing offered rate | Low, near good-RF knee |
| Planned physical replays | **10 × 2 × 3 × 2 = 120** |

With 30 seconds warm-up, 300 seconds measurement and 60 seconds fixed drain, this is 13 hours of timed replay before calibration, configuration changes and failed setup attempts. Pilot duration and independent sample size must be adequate for the chosen effect and then frozen. If the cell cannot sustain the intended rates, use the measured feasible range and report the limitation.

Treat RF setting as a block when it is expensive to change. Randomize/balance the RF-block order across sessions and randomize paired trace order within the block. Do not run all weak-RF experiments only at the end of the campaign. Use at least three independently established sessions where practical. Record RF measurements during each replay; a label assigned hours earlier is insufficient.

For F2, optionally add a prespecified smaller subset with the competing rate adjusted to the same measured utilization fraction at each RF level. This answers a different question from fixed-rate F1. Do not replace F1 with normalized-load results after seeing an unfavorable effect. Both the gateway and competitor RF states can affect scheduler allocation; hold the competitor path fixed where possible and record it otherwise.

## Analysis and figures

Primary outcomes are deadline failure and scheduled-release-to-application p95 delay; analyze the native-minus-periodic contrast within each source/RF/load block. Estimate how that contrast changes across the three RF levels, with confidence intervals at the source/session level. Show offered load, delivered load and radio/service evidence beside application outcomes.

Use native traces for reader-to-application AoI and freshness violations over the whole sensor population. Report loss of service, registration/PDU-session failure, reconnects and late receipts separately. Do not calculate the entire result from only surviving good-RF intervals. Fixed-rate overloaded conditions are finite-horizon overload experiments; they do not establish steady-state queue-delay percentiles.

Produce a measured RF-state summary, native-versus-periodic delivery curves, freshness/outage curves for native traffic, and a service-boundary plot with uncertainty. A boundary requires an explicit application requirement and observed pass/fail probability. Three selected RF states establish robustness at those states; they do not produce a general geographic coverage map.

## Optional modeled Ambient-IoT coverage study

Read `Experiment/model/{propagation,backscatter,controller,capacitor}.py` and the energy/source adapter. The reviewed UMa implementation entered a far-distance branch below 10 m, creating a discontinuity between 9 and 10 m while the default layout included 5–10 m. Correct the domain behavior. The code cites a version of [3GPP TR 38.901](https://www.etsi.org/deliver/etsi_tr/138900_138999/138901/15.00.00_60/tr_138901v150000p.pdf); using a formula from that report does not establish indoor-backscatter calibration or full standard conformance.

Choose a model appropriate to the intended geometry/frequency and state what has been calibrated. If no relevant RF measurements are available, restrict results to a model sensitivity analysis. Document forward command and reflected-data paths, antenna assumptions, sensitivity/noise, fading/shadowing, energy conversion and whether RF harvesting shares the same propagation path. Avoid applying a distance loss twice accidentally, or omitting the return path where required by the selected abstraction.

Use five prespecified distance/path-loss levels within the validated model domain, two environmental energy margins and 20 independent exogenous realizations: **200 model runs** as a starting design. Freeze sensor count, collision policy, sensing interval, population layout rule and correlation level. Pair the exogenous realizations across distances. Keep environmental energy independent of distance for a link-only sensitivity; if RF harvesting is distance-dependent, run that as the separately labeled coupled energy/link scenario.

Define service as an update/freshness requirement over a fixed observation window, then count all sensors and seeds. Report command reception failure, insufficient energy, collision/decoding failure, unique updates and starvation separately. A single successful packet at a distance is not reliable coverage. Show both reader-side service probability and its uncertainty. A downstream 5G replay can add application consequences, but it cannot transform a simulated coverage curve into a physical sensor-range measurement.

## Completion criteria

The physical study is complete when the declared RF treatments or observed-state groups are documented, matched traces are verified, every assigned run has a disposition, and application results are tied to measured radio/service evidence. If RF control is unavailable, finish the conditional robustness study and state exactly what additional apparatus or positioning measurements a causal coverage claim requires.

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
