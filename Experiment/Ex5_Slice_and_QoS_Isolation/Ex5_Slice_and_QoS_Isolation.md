# Experiment 5: protection of Ambient-IoT traffic under competing 5G load

## Objective and publication role

Test whether a configured 5G resource policy protects Ambient-IoT gateway freshness from another UE's continuous or bursty traffic, and determine which layer provides the protection.

This study is **conditionally feasible**. SynthRAN has slice identities, subscriber profiles and per-UE binding evidence, but identity/DNN separation is not proof of resource isolation. Current srsRAN documentation exposes slice PRB controls; support and uplink behavior in the pinned image must be established experimentally. A routine two-slice deployment has limited novelty. Burst-specific interference and a verified protection/cost trade-off are more useful research outcomes. See [native-cloud 5G slice-isolation experiments](https://arxiv.org/html/2502.02842v1).

## Context for a fresh ChatGPT session

Use this file as a standalone experiment brief for **RA-Nayreed/SynthRAN**. Read the current relevant source before changing or running anything. The review baseline was `main` at `ccaa385174fa695bdaa669e6046b61e80283a0be`, inspected on **8 September 2026**. The physical N320 candidate was draft PR [#7](https://github.com/RA-Nayreed/SynthRAN/pull/7), head `21d0dddb2792a004e529afc3144ab7aaa1eea941`. Its prose mentioned an older hash; the API head was authoritative. Recheck the current revision and retain improvements already present.

SynthRAN executes an Amber-derived SimPy model of energy harvesting, capacitor/controller operation and backscatter access. It freezes decoded events into JSONL, then replays them over MQTT through an actual 5G UE interface to an N6-side application. The Ambient-IoT radio and harvesting are **modeled**. The N320 carries the **5G gateway transport**; it does not make the upstream Ambient-IoT link a physical implementation.

The revised campaign uses **one fixed OAI core + srsRAN gNB + N320 physical-radio configuration**, after a clean acceptance run. This choice follows the repository's active physical reference. It replaces the attachment's Open5GS/RFSIM choice once, before data collection; it introduces no core comparison. RFSIM with the same core is useful for qualification. Its different UE software, band, numerology and image mean its measurements must be analyzed separately. If an already accepted Open5GS/N320 deployment is used instead, freeze that choice before the pilot and revise the manifest consistently; do not mix cores in a result series.

Use a homogeneous slice/DNN/QoS assignment except in the explicit isolation study. The shipped default profile assigns `uesim01` and `uesim02` to different slices, so it is not an appropriate neutral baseline. Begin with two proven physical UE roles: gateway A and competing-traffic UE B. Use only the N320 for physical-radio studies. Node availability and runtime capability require live evidence; scenario examples are not proof.

Complete the necessary model and instrumentation corrections, produce runnable scenario/analysis/campaign files, run qualification and then the declared experiment where resources are available. If physical access is absent, complete all local work and give the exact remaining live commands with their acceptance criteria. Report preparation, simulated results and physical measurements separately. At the end of every working session, retain a concise checkpoint with the actual commit, completed gates, artifact paths/hashes, failures and the next executable step. This file does not require any other handoff file to be understood.

## Questions

- **Q1:** At equal competing traffic volume, do bursts create more victim deadline/freshness violations than smooth traffic?
- **Q2:** Does logical slice separation alone reduce the effect?
- **Q3:** Does a verified resource-control policy reduce it, at what throughput/resource cost to the other slice, and through which mechanism?

Test uplink competition, because the Ambient-IoT gateway sends telemetry toward N6. A downlink scheduling feature must not be presented as validated uplink protection.

## Code and capability gates

Read `deployment/group_vars/all/5g_profile_{default,scenario1}.yaml`, `deployment/roles/5g/srsRAN/config/tasks/{main.yml,apply_5g_profile.yaml}`, the selected core's subscriber/configuration roles, `synthran/deployment_state.py`, UE discovery/binding code and the physical publisher role.

The default profile uses different 5QI and AMBR values on its two slices. Clone a dedicated experimental profile with neutral/equal 5QI, AMBR and other service parameters unless that exact field is the declared intervention. Otherwise a “slice” comparison changes several policies at once.

The reviewed srsRAN profile application writes S-NSSAI entries without a scheduler resource policy. The [srsRAN configuration reference](https://docs.srsran.com/projects/project/en/latest/user_manuals/source/config_ref.html) documents `sched_cfg.min_prb_policy_ratio` and `max_prb_policy_ratio`; check the exact container's version, schema and implementation, and prove the behavior in the **uplink** with measured allocations under load. Do not infer enforcement from YAML acceptance.

PR #7 can attest a secondary MBIM session on `wwan0.1`, while the unchanged physical publisher hard-codes `wwan0`. Correct the binding and demonstrate both S-NSSAI/DNN identities, session IP ranges and actual publisher routes before this study. A 5G registration or first-DNN connection is insufficient proof of the second session's data path.

Choose one enforcement mechanism that is real and observable. Prefer a verified uplink RAN scheduler policy for a radio-isolation claim. If the available mechanism is core/N6 policing or separate UPF CPU resources, that is a different layer and must be named explicitly. It is valid to report the RAN-isolation experiment as blocked while completing a clearly scoped core-queue study; the latter does not substitute for an uplink-RAN claim.

## Fixed physical roles and traffic

UE A carries the victim's frozen native Ambient-IoT decoded stream through a qualified gateway publisher. UE B produces benign competing traffic through the same cell. Use homogeneous modems and fixed radio conditions or account for modem/location differences as blocks. Retain one OAI core, one srsRAN gNB and N320 throughout.

Victim source, payload, gateway/connection count and real-time release schedule remain identical within comparisons. Competing traffic uses a fixed protocol, packet size, connection/flow count and destination. Construct smooth and bursty versions with equal event count, bytes and horizon; freeze burst duration, duty cycle and peak rate from a plausible workload or an explicit stress scenario. Record achieved offered traffic at the source, not only sink throughput.

Keep the broker/sink from becoming the accidental shared bottleneck. Measure their processing/queues and the core host load, especially if both terminate on the same machine. Maintain equivalent logging across arms.

## Experimental policy arms

| Arm | Configuration | Interpretation |
| --- | --- | --- |
| I0 | Same slice, equal QoS, no explicit protection | Shared-resource baseline |
| I1 | Different S-NSSAI/DNN, equal QoS/resource policy | Logical-separation control |
| I2 | Different slices plus one verified protection policy | Mechanism under test |

Measure a no-competitor baseline for every policy arm. A policy can change latency even without load, so normalize against its own unloaded baseline when reporting inflation. Keep the physical core/gNB/radio unchanged; policy/profile changes form separate attested configuration blocks. The current `--workload-only` identity check should refuse an undeclared profile change.

For a scheduler reservation, freeze a feasible victim guarantee/competitor cap from the independent pilot and retain configured and measured PRBs. Ensure resource allocations obey the actual scheduler's rules. For a policer, state its placement, shaping versus dropping behavior, rate, burst allowance and counters. Do not describe a policer's reduction of offered radio demand as RAN scheduling isolation.

## Campaign and run order

1. Prove both UE data paths and neutral service profiles.
2. Determine the victim's baseline deadline/freshness requirement and an independent competitor-load knee.
3. Prove the selected protection mechanism on a simple known traffic pair. Measure actual uplink resource effects and throughput trade-offs.
4. Freeze two nonzero background levels: near and above the identified operating knee, plus no-competitor baselines. The “above” case is a fixed-duration overload test if queues are unstable.
5. Use ten independent victim source realizations as an initial precision-planning set; pair the same source and background realization across policy arms. Use smooth and bursty background patterns at each nonzero load.
6. Main loaded matrix: `3 policies × 2 patterns × 2 loads × 10 sources = 120 replays`. Unloaded baselines add `3 × 10 = 30`, for **150 replays** before capability pilots. Freeze final duration/seed count before confirmation.
7. Randomize workload order inside each configuration block and counterbalance configuration order across at least three sessions. Restore and verify policy state for every block. Do not silently reuse an identity from another policy.

## Outcomes and analysis

Primary victim outcomes are deadline-failure probability and time above the native AoI limit. Also report p95 scheduled-to-receipt delay, conditional transport delay, delivery by drain deadline, and starvation per sensor.

Define a degradation measure, for example

\[
I_{policy,load}=Y_{policy,load}-Y_{policy,no\ competitor}.
\]

For an outcome where lower is better, compare `I_I2 − I_I1` to estimate additional protection beyond identity separation. Compare I1−I0 separately. Use paired seed/session analysis and confidence intervals, with a practically meaningful victim improvement and an explicit acceptable competitor cost established before confirmation.

Report competitor delivered throughput, deadline/loss where meaningful, resource shares and fairness. A victim improvement achieved by entirely starving the other flow is not a free isolation benefit. Retain offered versus admitted versus delivered traffic so shaping/drop mechanisms remain visible.

Distinguish mechanisms using radio allocations and HARQ/BLER, RLC/PDCP queues where available, UPF queue/drop/policing counters, host CPU and broker load. If a field is unavailable in the actual build, mark that attribution unresolved rather than filling it from assumptions.

## Falsification and result scope

I1 may perform like I0 because naming slices does not itself reserve resources. I2 may offer no measurable benefit or may move the bottleneck to a shared core/broker. Either is a meaningful result when the policy is demonstrably active and confidence intervals are adequate.

Claim protection only under the measured load, burst pattern, radio state, policy and time horizon. Do not claim complete isolation, URLLC guarantees, O-RAN RIC control or standardized QoS compliance based solely on these application measurements.

## Figures and completion

Produce victim violation/freshness curves across policy/load/pattern, competitor cost curves, and a mechanism panel showing actual resource allocation or policing. Deliver the exact experimental profiles and a policy evidence record sufficient to prove that I0/I1/I2 were distinct at runtime. If uplink enforcement could not be qualified, finish with a capability report and the remaining concrete requirement; do not label the physical isolation hypothesis tested.

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
