# Experiment 7: causal gateway policies for information freshness

## Objective and publication role

Evaluate whether a practical gateway can reduce freshness violations caused by energy-driven arrival bursts, while making its cost in completeness, transport bytes, fairness and latency explicit. This is the main proposed enhancement beyond the uploaded descriptive experiment.

The study is feasible after the source model, event identity and asynchronous replay path are qualified. The ambitious contribution is a **causal policy and an experimentally supported rule for when to use it**, evaluated on held-out workloads over the physical N320 path. Token buckets, latest-update queues and AoI are established concepts; placing them in this testbed alone does not make a new algorithm. Use strong simple baselines and demonstrate a useful operating region, generalization or mechanism. The [AoI survey](https://arxiv.org/abs/2007.08564) provides the necessary freshness/queueing context.

## Context for a fresh ChatGPT session

Use this file as a standalone experiment brief for **RA-Nayreed/SynthRAN**. Read the current relevant source before changing or running anything. The review baseline was `main` at `ccaa385174fa695bdaa669e6046b61e80283a0be`, inspected on **8 September 2026**. The physical N320 candidate was draft PR [#7](https://github.com/RA-Nayreed/SynthRAN/pull/7), head `21d0dddb2792a004e529afc3144ab7aaa1eea941`. Its prose mentioned an older hash; the API head was authoritative. Recheck the current revision and retain improvements already present.

SynthRAN executes an Amber-derived SimPy model of energy harvesting, capacitor/controller operation and backscatter access. It freezes decoded events into JSONL, then replays them over MQTT through an actual 5G UE interface to an N6-side application. The Ambient-IoT radio and harvesting are **modeled**. The N320 carries the **5G gateway transport**; it does not make the upstream Ambient-IoT link a physical implementation.

The revised campaign uses **one fixed OAI core + srsRAN gNB + N320 physical-radio configuration**, after a clean acceptance run. This choice follows the repository's active physical reference. It replaces the attachment's Open5GS/RFSIM choice once, before data collection; it introduces no core comparison. RFSIM with the same core is useful for qualification. Its different UE software, band, numerology and image mean its measurements must be analyzed separately. If an already accepted Open5GS/N320 deployment is used instead, freeze that choice before the pilot and revise the manifest consistently; do not mix cores in a result series.

Use a homogeneous slice/DNN/QoS assignment except in the explicit isolation study. The shipped default profile assigns `uesim01` and `uesim02` to different slices, so it is not an appropriate neutral baseline. Begin with two proven physical UE roles: gateway A and competing-traffic UE B. Use only the N320 for physical-radio studies. Node availability and runtime capability require live evidence; scenario examples are not proof.

Complete the necessary model and instrumentation corrections, produce runnable scenario/analysis/campaign files, run qualification and then the declared experiment where resources are available. If physical access is absent, complete all local work and give the exact remaining live commands with their acceptance criteria. Report preparation, simulated results and physical measurements separately. At the end of every working session, retain a concise checkpoint with the actual commit, completed gates, artifact paths/hashes, failures and the next executable step. This file does not require any other handoff file to be understood.

## Application semantics and questions

Assume periodic sensor-state updates for which a newer measurement can supersede an older **not-yet-published** measurement. This assumption permits coalescing. It does not apply automatically to alarms, billing records, irreversible actions or event logs where every sample matters. For those workloads, only lossless policies and explicitly provisioned capacity are appropriate within this study.

- **G1:** Lossless pacing can reduce transport contention/release bursts, but may worsen end-to-end freshness by holding samples at the gateway.
- **G2:** A fair latest-update policy can reduce native-trace freshness-violation time and network cost near a service limit, with an explicit reduction in delivered sample completeness.
- **G3:** A policy selected on pilot energy/load conditions retains useful performance on held-out source realizations and load shifts.

No policy is assumed to improve every objective. Prespecify a useful trade-off, including a completeness floor if the application requires one. A higher delivered-packet success percentage after intentional suppression is not by itself an improvement.

## Required implementation and evidence

Read `Experiment/workload/{trace,replay}.py`, the model-to-trace bridge and all MQTT publication/collection/reconciliation tasks. At the review baseline, replay waited for each PUBACK before submitting the next event and set `sent_utc` after that wait. That behavior can resemble uncontrolled pacing. Implement and qualify a nonblocking release scheduler before comparing deliberate gateway policies.

Retain the same source trace for all policies. Every completed reader decode becomes an immutable gateway-arrival event at its native real-time release `s`. A policy may inspect that event only after `s`, plus the queue and locally available past observations. It must not read future trace entries, future energy, future channel state or future application receipts. The runner can read input for scheduling, but the policy interface must expose only released events and permitted state.

Record at least `event_id`, sensor/generation identity, original arrival `s`, queue admission, intentional waiting, replacement/drop decision and reason, immediately-prepublish time `p`, ACK callback, receiver entry `r`, queue lengths and token/inflight state. Keep future input outside the policy object. A small deterministic causality fixture must demonstrate that modifying a trace's future suffix cannot alter earlier policy decisions.

Use the correct attested UE interface/address, a subscription-ready barrier, bounded queues/inflight windows, append-only outcome records and measured clocks. A PUBACK is a client-to-broker event, not an application delivery observation. The optional adaptive policy below uses it only as a local congestion proxy. Do not feed receiving-application knowledge back into the gateway unless an explicit feedback protocol, its traffic and delay are implemented and evaluated.

## Four primary policies

| Policy | Action | Why it is included |
| --- | --- | --- |
| P0: immediate FIFO | Publish eligible decoded arrivals promptly through the qualified asynchronous client; hold remaining work in FIFO under the common bounded inflight/queue policy | No intentional rate shaping; measures the existing application service objective without acknowledgement-induced serialization |
| P1: lossless FIFO pacing | FIFO queue with a fixed token-bucket byte-rate and burst budget | Tests whether smoothing alone helps after accounting for gateway holding time |
| P2: fair FIFO pacing | Same token rate and burst budget, with per-sensor FIFO queues and byte-fair round-robin/deficit service | Separates fairness/scheduling effects from coalescing |
| P3: fair latest-update pacing | Same fair scheduler and token budget; retain only the freshest pending unsent update per sensor | Adds coalescing while preserving a service opportunity for every active sensor |

Use one common MQTT connection for the primary campaign, one gateway UE, fixed QoS 1 and identical message serialization. Account tokens in a declared byte unit: serialized MQTT application payload is simple and reproducible, while measured on-wire bytes are a separate reported cost. Do not call payload bytes total radio resource consumption. With variable sizes, specify deficit weights and packet eligibility; with equal sizes, simple round-robin can suffice.

Specify token initialization, maximum accumulation, queue limits, inflight limit, scheduler tie-breaking and drain behavior. Reset identically at each run. Choose a burst budget at least large enough for the largest legal message; otherwise some messages can never become eligible. Establish that P1/P2 do not overflow in their declared lossless operating domain. If the offered rate exceeds sustained service or queue capacity, classify the resulting backlog/overflow explicitly rather than calling them lossless without qualification.

P3 may replace an older pending update only with one having a newer generation sequence/time for that sensor. Equal or older generations must not evict a fresher update. Never retract or relabel an MQTT message already handed to the client; it may still arrive. An inflight window that is too large can move stale work into a queue the policy cannot control, so qualify and freeze it consistently across policies. A replaced sample remains in the expected-input ledger as an **intentional policy discard**.

Do not clear a sensor's fresh pending update merely because an older sample was acknowledged. Record which event an acknowledgement belongs to. Use non-retained MQTT updates and cleanly scoped run identities/queues unless persistence/retention is an explicitly tested application feature.

## Parameter selection and causality

Select a single token rate and burst budget from an independent pilot that estimates the relevant service/latency knee and source rates. Freeze them before confirmation. P1/P2/P3 must use exactly the same rate/burst parameters within a matched condition. A small prespecified pilot grid is acceptable; tuning separately on each confirmation trace is not.

For the main held-out test, the gateway does not know the future background-load schedule. Use the fixed pilot policy unchanged. This supplies a strong test of whether simple shaping generalizes. A policy that is given the true future service curve is an oracle upper bound and belongs outside the practical comparison.

An optional second-stage adaptive variant may update its budget using past local queue age, achieved submission/ACK rate and observed ACK delay, subject to fixed minimum/maximum rates and a declared control period. Define its algorithm exactly before testing. It cannot treat ACK delay as a pure radio measurement. Compare it against P3 with fixed parameters under the same held-out shifts, and count control oscillation, queue starvation and any added feedback traffic. Do not add machine learning unless a concrete limitation of the simple policies motivates it and a separate training/validation split is feasible.

These gateway policies act **after** the modeled reader has decoded an update. They do not save modeled sensor energy or improve Ambient-IoT collision rate in this open-loop architecture. Those upstream outcomes are identical across policies. Any energy saving requiring feedback to sensors is a different closed-loop system and needs an implemented feedback/energy model.

## Campaign design

Use the qualified native traces at real-time scale, with E-knee independent and common harvesting as two source regimes. Preserve every source's event bytes, generation timestamps and gateway-arrival times across policies. All runs begin with the same retained native warm-up. Unlike the flagship timing surrogates, these are causal policies acting on genuine arrivals, so the native generation-to-application AoI process remains meaningful.

After a separate pilot, a compact confirmation matrix is:

| Factor | Levels |
| --- | --- |
| Source regimes | E-knee independent, E-knee common |
| Independent source seeds | 10 per regime, paired across policies/load |
| Policy | P0, P1, P2, P3 |
| Competing offered load | Low, near the pilot service knee |
| Planned physical replays | **2 × 10 × 4 × 2 = 160** |

At 30 seconds warm-up, 300 seconds measurement and 60 seconds drain, this requires about 17.3 hours of timed replay before setup/calibration. The count is a planning estimate, not a power calculation. Freeze confirmation size based on pilot variance and the meaningful effect. Confirm that the primary native traffic occupies a regime where a policy could matter; a well-measured null at low load is useful.

Keep all confirmation energy realizations out of parameter tuning. Use confirmation seeds from the declared held-out range, such as 1001–1010, consistently across policies. Repeat/balance matched blocks across at least three sessions where practical. Randomize policy order and hold the actual background workload schedule fixed within each block. Verify background offered rate and RF/runtime state for each replay.

Add an optional **40-run** shift test only after the fixed-policy comparison is qualified: ten unseen seeds × P0/P3 × two prespecified within-run background schedules. One schedule can rise from low to near-knee service pressure, and the other reverse the order. Define switch times in advance and replay the same schedule for each pair. Select policy parameters without using these outcomes. A different held-out energy correlation/period can substitute for one schedule if energy generalization is the central question; record this choice before confirmation.

An always-powered/low-load subset is a useful negative control when the pilot suggests idle service. If all baselines already meet the requirement, there may be no meaningful mitigation benefit in that regime. Do not compress source time or weaken baselines after seeing a null.

## Primary outcomes and accounting

Set an application freshness limit `A_max` independently of confirmation results. The primary utility is the equal-weight per-sensor fraction of observation time with `AoI > A_max`, counting sensors without history as violating. Report time-average AoI, time-weighted tails, maximum starvation interval and the worst served sensor/group as supporting outcomes.

Use **all decoded gateway arrivals** as the denominator for sample completeness. Classify each event as received by deadline, received late, intentionally superseded/discarded, rejected/failed by the publisher, or still outstanding at the drain deadline. Preserve any overlap needed for events that were already published and later arrived; status transitions must be time-stamped rather than rewritten to make final percentages look cleaner. A mutually exclusive final-disposition summary should reconcile to the input count.

Report:

- Freshness-violation time and AoI for the fixed sensor population, including quiet/starved sensors.
- Delivery-by-deadline fraction and total unique sample completeness relative to all gateway inputs.
- Intentional discards, unintentional failures, late delivery and final backlog, separately.
- `p-s` intentional/unintentional holding and `r-s` full gateway-arrival-to-application delay.
- Payload and observed transport bytes, publication attempts, duplicates and protocol overhead where measured.
- Queue occupancy, token utilization, per-sensor service, gateway/collector CPU and background-UE impact.

Do not judge the policy using `r-p` alone: a pacer can reduce that interval simply by moving waiting into the gateway. Do not remove coalesced samples from the denominator to inflate reliability. A coalescing policy's lower byte count is an intended treatment effect, so this is not an equal-offered-load experiment after policy action.

P1−P0 isolates the declared lossless pacing intervention; P2−P1 isolates fair service under the shared token policy; P3−P2 isolates latest-update coalescing within that fair service design. Mechanisms can interact, so report both these sequential contrasts and the practical P3−P0 total effect. If coalescing produces the whole benefit, a “new pacing algorithm” claim is unsupported.

An optional byte-budget diagnostic can compare a prespecified content-agnostic thinning rule at a pilot-fixed rate, but it must be causal and its completeness/fairness costs remain visible. Do not derive a perfect per-trace discard budget using future confirmation outcomes and present it as an online baseline.

## Qualification fixtures and analysis

Before hardware runs, use short deterministic inputs to verify token conservation/burst limits, nonnegative release lag, fixed FIFO order where required, one pending latest update per sensor, protection against out-of-order generations, no retraction of inflight publications, fair eventual service and consistent accounting after overflow/disconnect. These fixtures validate actual scientific invariants; they are not substitutes for performance qualification.

Use independent source realizations with session blocking and paired policy differences. The primary confirmatory contrast is P3−P0 in freshness-violation time at near-knee load, alongside the prespecified completeness floor/cost requirement. Report confidence intervals and all four policies. Present P1/P2 mechanism contrasts as secondary unless explicitly allocated confirmatory error control. Analyze the low-load control and held-out shifts regardless of outcome.

A policy is useful only if it meets the declared practical trade-off. Report improvements that come with unacceptable sample loss as trade-offs, not unconditional success. If improvement appears only with artificially constrained Python capacity, fix/qualify that capacity or limit the claim to that gateway implementation. If no policy meaningfully improves the qualified physical system, report the operating boundary and avoid claiming necessity of mitigation.

## Figures and completion

Produce a freshness-versus-completeness/byte-cost frontier, paired near-knee utility comparisons, low-load guardrail results, per-sensor fairness/starvation summaries, queue/age timelines from prespecified runs and held-out shift results. Include a concise deployment rule stating when the measured policy helps, what it discards, the assumed application semantics and where it fails.

The experiment is complete when the policies are causal and reproducible, inputs and outcome accounting reconcile, pilot choices are separated from confirmation, and the practical trade-off is quantified with uncertainty. A fresh session should be able to rerun any reported contrast using the retained source bundle, policy manifest and exact campaign command.

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
