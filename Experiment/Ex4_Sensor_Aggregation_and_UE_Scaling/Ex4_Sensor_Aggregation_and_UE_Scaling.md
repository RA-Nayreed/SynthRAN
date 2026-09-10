# Experiment 4: sensor aggregation, gateway UE count and capacity

## Objective and publication role

Determine how many modeled sensors a 5G gateway arrangement can serve under a declared freshness/delivery requirement, and identify whether the limiting resource is the model, publisher, MQTT connections, UE processing, radio scheduler, core or receiving application.

Software scale qualification is feasible after decoupling sensors from UEs. Physical scaling is limited by the actual number of available, successfully attached UEs. The repository's srsRAN port-space guard permits up to 635 UE definitions; **that is not demonstrated 635-UE capacity**. This study has medium standalone ambition. Its value increases when it produces an aggregation rule and explains a bottleneck under energy-correlated traffic.

## Context for a fresh ChatGPT session

Use this file as a standalone experiment brief for **RA-Nayreed/SynthRAN**. Read the current relevant source before changing or running anything. The review baseline was `main` at `ccaa385174fa695bdaa669e6046b61e80283a0be`, inspected on **8 September 2026**. The physical N320 candidate was draft PR [#7](https://github.com/RA-Nayreed/SynthRAN/pull/7), head `21d0dddb2792a004e529afc3144ab7aaa1eea941`. Its prose mentioned an older hash; the API head was authoritative. Recheck the current revision and retain improvements already present.

SynthRAN executes an Amber-derived SimPy model of energy harvesting, capacitor/controller operation and backscatter access. It freezes decoded events into JSONL, then replays them over MQTT through an actual 5G UE interface to an N6-side application. The Ambient-IoT radio and harvesting are **modeled**. The N320 carries the **5G gateway transport**; it does not make the upstream Ambient-IoT link a physical implementation.

The revised campaign uses **one fixed OAI core + srsRAN gNB + N320 physical-radio configuration**, after a clean acceptance run. This choice follows the repository's active physical reference. It replaces the attachment's Open5GS/RFSIM choice once, before data collection; it introduces no core comparison. RFSIM with the same core is useful for qualification. Its different UE software, band, numerology and image mean its measurements must be analyzed separately. If an already accepted Open5GS/N320 deployment is used instead, freeze that choice before the pilot and revise the manifest consistently; do not mix cores in a result series.

Use a homogeneous slice/DNN/QoS assignment except in the explicit isolation study. The shipped default profile assigns `uesim01` and `uesim02` to different slices, so it is not an appropriate neutral baseline. Begin with two proven physical UE roles: gateway A and competing-traffic UE B. Use only the N320 for physical-radio studies. Node availability and runtime capability require live evidence; scenario examples are not proof.

Complete the necessary model and instrumentation corrections, produce runnable scenario/analysis/campaign files, run qualification and then the declared experiment where resources are available. If physical access is absent, complete all local work and give the exact remaining live commands with their acceptance criteria. Report preparation, simulated results and physical measurements separately. At the end of every working session, retain a concise checkpoint with the actual commit, completed gates, artifact paths/hashes, failures and the next executable step. This file does not require any other handoff file to be understood.

## Three quantities that must be separated

| Symbol | Quantity | What changing it can change |
| --- | --- | --- |
| N | Number of modeled Ambient-IoT sensors | Generation/energy/MAC contention and offered events |
| U | Number of actual software/physical 5G UE gateways | Scheduling entities, tunnels, radio/host resources |
| K | Number of MQTT/TCP connections | Flow multiplexing, client queues and protocol concurrency |

The current implementation maps one modeled device to each `deployment.ues` entry and launches one publisher per device. Consequently an apparent N sweep also changes U and K. It cannot isolate the desired effects.

## Required source work

Read `synthran/scenario.py`, `synthran/deployment_state.py`, `deploy.sh`, `Experiment/workload/replay.py`, `deployment/roles/synthran/software_ue_publish/`, `deployment/roles/synthran/publisher/`, and srsRAN's UE/broker configuration roles. Read the model runner/bridge for source identities.

Implement separate sensor and gateway identities, an explicit `sensor_id -> gateway_id -> connection_id` mapping, and validation that every expected event is forwarded exactly once. A gateway with no assigned modeled sensor, such as a competing-load UE, must be allowed. Preserve the old 1:1 mapping as an explicit special case if useful; do not silently rewrite populations.

Generate events without requiring a live UE for each simulated sensor. Bind each gateway/connection to its attested interface/address and keep per-sensor generation/sequence fields. Remove per-event PUBACK blocking and measure client queue/in-flight limits. Complete source-time/circuit/receiver corrections before interpreting capacity in terms of energy-aware sensors.

Qualify logging/model runtime separately. Stream or decimate observational voltage histories with a documented cadence while preserving the integration algorithm and energy accounting. Record both simulation elapsed time and simulated duration; an offline simulation need not run in real time to be scientifically valid.

## Questions

- **S1:** At fixed U/K and realistic per-sensor sensing/energy behavior, where does timely delivered service stop scaling with N?
- **S2:** At fixed immutable aggregate event stream and fixed K, does distributing traffic across more UEs improve or degrade delivery under shared radio resources?
- **S3:** How much of any apparent UE benefit can be explained by extra MQTT/TCP concurrency?
- **S4:** Does common-energy synchronization change a safe aggregation limit relative to independent harvesting at comparable operating points?

## Experiment A: sensor population at fixed gateways

Keep U=1 data gateway and K=1 persistent MQTT connection, plus a separate competing UE if a loaded-cell condition is required. Increase N through pilot-feasible values such as 8/16/32/64/128. Larger populations require a measured runtime/memory budget and a plausible application interpretation.

Use fixed per-sensor sensing law, valid spatial deployment rule, MAC resources and two energy-dependence settings: independent/common at E-knee. The resulting event count is allowed to change. This estimates the total effect of adding sensors, including Ambient-IoT contention; it is not an equal-rate comparison.

Run the model first to find where generated/decoded traffic ceases to grow or fairness deteriorates. Replay only a prespecified low/transition/high subset through the physical gateway. A planning matrix of three N levels × two dependence settings × ten seeds × two competing-load levels gives **120 physical replays**, plus model characterization. At low populations, retain zero-output and underpowered tail cases rather than silently pooling them away.

Report capacity using a joint criterion, for example a maximum allowed freshness-violation fraction plus minimum per-sensor service coverage, selected from a requirement or pilot before confirmation. A high aggregate receipt ratio can coexist with starved sensors. State the observation duration over which the criterion holds.

## Experiment B: partition a fixed workload across UEs

Freeze one aggregate event stream, including exact release times, payload bytes and all sensor identities. Change only the gateway partition. Do not increase total offered traffic when U increases. Use balanced deterministic partitions by event volume, with several prespecified assignment seeds if routing imbalance is a concern. Verify the actual aggregate release process remains equal after distribution.

Hold K fixed and at least as large as the largest tested U. For example, U in {1,2,4} with K=4 gives 4/2/1 connections per gateway. Keep the connection-to-sensor assignment stable as far as the partition permits and retain it in the manifest. The global event set and per-connection stream stay unchanged; only the connection-to-UE allocation changes.

First determine which U values the software setup actually sustains. Stop at the first reproducible resource limit and report its cause. The [srsRAN multi-UE tutorial](https://docs.srsran.com/projects/project/en/latest/tutorials/source/srsUE/source/index.html) establishes an available setup approach, not the capacity of this installation.

For physical N320 validation, use U={1,2} if only two homogeneous modems are proven. If both are data gateways, a third UE is needed for an independent over-radio competitor; otherwise use an unloaded-cell comparison or explicitly share a declared background flow. Do not assume a third physical UE exists. Modem models and locations must be matched or treated as separate blocks.

A planning physical matrix with U={1,2}, two timing structures, ten immutable source seeds and one fixed load is **40 replays**. A second load doubles it only when independent physical background generation is available and qualified. Treat higher-U software findings separately from this physical validation.

## Experiment C: connection-count control

At one fixed U, sweep K over a short feasible range such as {1,2,4}, using the same global event set and release process. Measure actual client queueing, ACK delay, socket buffers and broker load. This explains whether an improvement from a naive “more UEs” run was actually a concurrency change.

Keep this a small diagnostic subset. It does not require crossing all N, U, K, energy, radio and load factors. Use results to clarify the primary capacity claim, not to create an unmanageable factorial.

## Resource and statistical evidence

For every condition record the N/U/K mapping, attempted and realized offered rate, event/byte rate per gateway/connection, CPU/RSS for model/publisher/UE/gNB/core/receiver, queue occupancy, scheduling errors, actual uplink resource use and radio failure counters where exposed.

Report per-sensor freshness/coverage, Jain fairness with its exact input quantity, worst-decile service, deadline misses and delivery by drain deadline. If all inputs to Jain's index are zero, label it undefined; do not return perfect fairness for a silent system.

Analyze A as population-dependent total system behavior. Analyze B and C as paired immutable-workload interventions. Treat source seeds as independent units and physical sessions as blocks. Model-derived capacity and physical gateway capacity require separate confidence statements.

Use “supported N under configuration X, criterion Y and horizon T” rather than a universal maximum sensor count. If offered traffic stops growing because the Ambient MAC is saturated, low 5G delay does not prove spare end-to-end capacity. If software UEs saturate CPU before radio processing, that is a software-host limit.

## Figures and completion

Produce a sensor-count versus timely-service curve with upstream/downstream failure breakdown; fixed-workload U comparisons; the K control; and a resource-attribution panel. Deliver a small aggregation table mapping observed load/energy dependence and U/K choices to service criteria, with confidence intervals and exact scope. Do not extrapolate beyond the tested hardware or claim that modeled sensors are physical attached 5G UEs.

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
