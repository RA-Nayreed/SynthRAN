# Experiment 2: causal impact of Ambient-IoT timing on physical 5G transport

## Objective and candidate contribution

Test whether the temporal order and variability of a decoded Ambient-IoT workload changes its application delivery and freshness over a fixed physical 5G gateway path when the event set, bytes and mean offered rate are held constant within each comparison.

This is the highest-priority SynthRAN experiment. It is potentially a full research-paper contribution if the causal controls, realistic load, physical evidence and uncertainty are convincing. The broad fact that traffic burstiness matters is established in [Leland et al.](https://www.cse.cuhk.edu.hk/~cslui/CSC5480/selfsim-eth.pdf); the candidate contribution is the validated energy/MAC origin, operating boundary and actionable consequences in this two-stage system.

## Context for a fresh ChatGPT session

Use this file as a standalone experiment brief for **RA-Nayreed/SynthRAN**. Read the current relevant source before changing or running anything. The review baseline was `main` at `ccaa385174fa695bdaa669e6046b61e80283a0be`, inspected on **8 September 2026**. The physical N320 candidate was draft PR [#7](https://github.com/RA-Nayreed/SynthRAN/pull/7), head `21d0dddb2792a004e529afc3144ab7aaa1eea941`. Its prose mentioned an older hash; the API head was authoritative. Recheck the current revision and retain improvements already present.

SynthRAN executes an Amber-derived SimPy model of energy harvesting, capacitor/controller operation and backscatter access. It freezes decoded events into JSONL, then replays them over MQTT through an actual 5G UE interface to an N6-side application. The Ambient-IoT radio and harvesting are **modeled**. The N320 carries the **5G gateway transport**; it does not make the upstream Ambient-IoT link a physical implementation.

The revised campaign uses **one fixed OAI core + srsRAN gNB + N320 physical-radio configuration**, after a clean acceptance run. This choice follows the repository's active physical reference. It replaces the attachment's Open5GS/RFSIM choice once, before data collection; it introduces no core comparison. RFSIM with the same core is useful for qualification. Its different UE software, band, numerology and image mean its measurements must be analyzed separately. If an already accepted Open5GS/N320 deployment is used instead, freeze that choice before the pilot and revise the manifest consistently; do not mix cores in a result series.

Use a homogeneous slice/DNN/QoS assignment except in the explicit isolation study. The shipped default profile assigns `uesim01` and `uesim02` to different slices, so it is not an appropriate neutral baseline. Begin with two proven physical UE roles: gateway A and competing-traffic UE B. Use only the N320 for physical-radio studies. Node availability and runtime capability require live evidence; scenario examples are not proof.

Complete the necessary model and instrumentation corrections, produce runnable scenario/analysis/campaign files, run qualification and then the declared experiment where resources are available. If physical access is absent, complete all local work and give the exact remaining live commands with their acceptance criteria. Report preparation, simulated results and physical measurements separately. At the end of every working session, retain a concise checkpoint with the actual commit, completed gates, artifact paths/hashes, failures and the next executable step. This file does not require any other handoff file to be understood.

## Research questions

- **T1:** For an identical decoded event set, do native timings produce a practically meaningful delivery-delay/deadline penalty compared with periodic timings near a measured transport limit?
- **T2:** Does permuting the order of the exact native inter-event gaps change that penalty, suggesting sensitivity to ordering beyond the gap histogram?
- **T3:** Does the penalty interact with competing load, and can endpoint/resource evidence locate the limiting stage?
- **T4:** For native real-time workloads, how much freshness is lost upstream through energy/MAC behavior and downstream through gateway/5G/application delivery?

Only within-source timing interventions establish the intended equal-volume comparison. Differences between two energy regimes may also include changes in generated/decoded volume and have a different interpretation.

## Required implementation before the pilot

Read `synthran/scenario.py`, the Ambient-IoT runner/bridge/evidence modules, `synthran/workload/{trace,replay}.py`, `synthran/results/reconcile.py`, `synthran/deployment_state.py`, `deploy.sh`, the broker/publisher/software-UE roles and the current N320 candidate.

Qualify sensing and energy inputs, circuit/receiver semantics, shared-subcarrier contention, and true generation/completed-decode timestamps. Separate modeled sensor membership from gateway UE membership. The current loader silently discards sensors not in the UE list.

Correct replay's per-event `wait_for_publish()` blocking and its post-ACK `sent_utc`. Add a subscription-ready barrier, append-only publication/receipt records, monotonic scheduling, queue/in-flight limits and source/derived trace provenance. Use the attested physical interface, including a secondary MBIM interface where applicable. Add a prepared-trace route through `--workload-only`; the current orchestrator regenerates the model and does not accept a surrogate bundle as an input.

Qualify instruments over a local/wired path using the complete event rate and burst pattern. Demonstrate that they preserve planned release structure, and record application-side and host resource use. The accepted network path must traverse the intended UE tunnel, gNB and UPF. Retain the actual deployment/image/RF fingerprints.

## Fixed physical system

| Element | Fixed primary choice |
| --- | --- |
| Core/gNB/radio | OAI + srsRAN + N320 after qualification |
| Radio settings | One accepted n78, 20-MHz configuration; retain actual ARFCN, SCS, TDD, gains and image digests |
| UE A | Gateway forwarding all modeled sensors for the primary causal comparison |
| UE B | Separately controlled uplink competing traffic through the same cell and neutral slice |
| MQTT | Version 3.1.1, QoS 1, one persistent connection on gateway A, fixed 256-byte application payload |
| Topics | Equal-length sensor identifiers/topics, one unchanged receiving subscription |
| Model | One reader, qualified broadcast SIC, explicit shared subcarrier, fixed geometry and `N*` |
| Source arms | Always-powered, E-knee independent harvesting, E-knee common harvesting |
| Native time scale | 1× modeled seconds to wall seconds |

Record protocol bytes and actual wire traffic separately from the 256-byte payload. If 256 bytes cannot hold the required event metadata, freeze a larger exact size before calibration and use it in every matched arm. Keep client queue, in-flight window, socket settings, logging and broker configuration identical.

The single-gateway primary design avoids changing the per-UE routing/connection structure when gap order is changed. A later multi-gateway validation needs per-gateway source/arrival metrics and controls that do not silently change gateway loads.

## Construct the matched timing interventions

Take a frozen decoded source trace with `m` events and ordered native decode-availability offsets `r_1,...,r_m` inside a fixed horizon `[0,T]`. Use stable event order for ties. Keep event IDs, sensor sequence, payload bytes/hashes, topics and gateway assignment unchanged. Store transformation metadata outside the MQTT payload so variant labels do not alter packet size or content.

Let `W` be the retained model warm-up duration. Transform only the measurement segment: its offsets are `r_i = d_i - W`, and transformed wall release is `replay_epoch + W + r'_i`. Replay the same unmodified native warm-up `[0,W)` before every timing variant. The common measurement window is `[replay_epoch + W, replay_epoch + W + T)`. Retain generation time as `replay_epoch + g_i`; do not reset it to the measurement origin. Specify treatment of exact endpoints once, so no event is duplicated across warm-up, measurement and drain. Model duration must cover both warm-up and measurement.

| Variant | Timing construction | Preserved and changed |
| --- | --- | --- |
| Native N | Original completed-decode offsets | Original timing and marks |
| Gap permutation R1 | Keep `r_1`; permute the `m−1` gaps and cumulatively sum them | Same gap multiset, first/last event, horizon and event order; changes gap order |
| Gap permutation R2 | Independent prespecified permutation seed | Same invariants; assesses permutation variability |
| Periodic P | `r'_i = r_1 + (i−1)(r_m−r_1)/(m−1)` | Same first/last event, event set and horizon; removes interior gap variability |

The mean offered event rate is `m/T` for every variant. The initial and final quiet intervals are retained, and the exact first-to-last span is equal. Do not call a finite permutation an independent renewal process. It disrupts gap ordering but does not guarantee removal of every kind of dependence. Check the resulting autocorrelation/burst metrics instead of asserting that they vanish.

For `m<2`, zero span or identical gaps, report degenerate controls explicitly. Retain silent sources in the upstream energy/freshness analysis. Do not manufacture additional events or remove a trace because its control contrast is null.

Verify, before any replay: identical event-ID sets and order; byte-identical payload/topic/gateway tuples; identical counts and duration; identical sorted gap vectors for N/R1/R2; equal endpoints; nondecreasing offsets; reproducible transformation hashes. Preserve ties, which may be scientifically meaningful.

Surrogates can move a forwarded event earlier than its modeled generation. Therefore **their transformed timings do not represent physical sensor histories**. Use them for transport-delay/arrival-process causal tests. Report physical end-to-end AoI for native 1× traces only.

## Load calibration that preserves physical time

Keep the native source time axis unchanged. Vary an independent, precisely paced uplink competitor on UE B, terminating at a qualified N6 sink. Hold packet size, direction, transport protocol, flow count and pattern fixed during the main campaign. UDP is suitable for controlling offered background rate, provided offered and received rates and loss are recorded. MQTT victim transport remains unchanged.

Start at zero competitor load, increase offered background rate logarithmically until a clear operating limit or the justified resource ceiling is reached, then refine around the first transition. Use a fixed periodic sentinel and repeated pilot blocks. Define the knee before examining native-versus-surrogate outcomes: for example, the smallest stable background-rate interval crossing a chosen application deadline-failure threshold or a preregistered p95 inflation threshold, corroborated by queue/radio/resource measurements.

Freeze three settings from this curve: **below knee, near knee, above knee**. Store actual offered Mbps, event/packet rates, delivered rates and the selection rule. Do not label them percentages of universal “network load.” If no knee is observed within the credible range, retain that result and do not substitute saturation of the Python publisher as a 5G knee.

The existing 121-event/10-second reference is only about 24.8 kbit/s of application payload. A dense gateway workload must be justified through population and sensing rates, or used as a controlled stress case. Extreme time compression is an optional secondary sensitivity, not the primary evidence. If performed, apply the same factor to each matched variant and label the experiment as accelerated workload replay; omit physical sensor-AoI claims.

Above sustainable capacity, queues may keep growing. Treat these as **finite-duration overload experiments**, report backlog/drain behavior and observation length, and do not claim stationary p99 or a stable throughput region.

## Pilot, confirmation and execution

1. Complete instrumentation and a clean N320 path acceptance. Run a same-slice neutral baseline with both UE roles. Freeze all system controls.
2. Generate a small independent pilot source set and calibrate power, `N*`, model duration and background load. Establish the smallest worthwhile effect and instrument tolerance.
3. Choose confirmation seeds by ID before viewing their outcomes. Suggested initial design: ten seed blocks, paired across AP/K-I/K-C, with R1/R2 seeds derived deterministically from each source identity. Ten is a planning number, not a guarantee of power.
4. Freeze the manifest and analysis. The planning matrix is `3 × 10 × 4 × 3 = 360` replays. At 300-s measurement + 30-s warm-up + 60-s drain, this is 39 timed hours, plus setup/cooldown/calibration. Extend horizons if pilot event counts cannot support the intended tail precision, before confirmation starts.
5. Randomize variant order within source/load blocks and distribute source/energy/load blocks across at least three independent sessions. Counterbalance order to reduce thermal, scheduler-phase and drift confounding. Keep the competitor realization equal within a matched block.
6. Start the receiver and sink, confirm subscription/publisher readiness, establish one UTC/monotonic anchor and replay retained warm-up history. Collect the fixed measurement window and fixed drain interval. Record current interface mappings, clock uncertainty and resource evidence.
7. Reuse the accepted deployment for replays. Do not rebuild it between timing arms. Clear or drain previous queues and isolate run identities before starting the next arm. Keep load-induced missing/late events as outcomes.
8. Replay a fixed sentinel between blocks, for example every 12 replays. Freeze drift criteria from the pilot. If drift invalidates comparisons, preserve the affected block, diagnose and repeat all affected matched arms under the same rule.

## Endpoints and bottleneck evidence

Primary outcomes are paired changes in p95 scheduled-release-to-application delay and application deadline-failure probability. Also report p95 `r−p`, publisher release errors, p99 where adequately sampled, ACK timing, delivery by drain deadline, duplicates and per-sensor starvation. Do not calculate all tail summaries only on successful timely packets.

Measure the source, actual publisher and receiving-application count processes using the same windows and origin. Report Fano curves, count autocorrelation, peak counts and a clearly defined burst threshold. Fano and the count index of dispersion are one metric. KS distance can describe inter-arrival distributions; ordinary IID KS p-values are inappropriate for dependent packet sequences.

Collect publisher/collector CPU and queues, broker load, UPF throughput/CPU, UE/gNB scheduler occupancy and available RLC/PDCP/HARQ/BLER metrics. Retain metric definitions and unavailable fields. These locate the limiting stage; tail latency alone does not.

For physical attribution, compare the instrument-qualified wired bypass and physical path at prespecified settings. This is an instrumentation/control comparison, not another core or radio model. If the penalty also occurs in the generator or receiving application, attribute it accordingly.

## Causal analysis

For each independent source/load block compute `Delta_NP = Y_N − Y_P` and `Delta_NR = Y_N − mean(Y_R1,Y_R2)`, for delay and deadline outcomes. Positive values mean native timing is worse for an outcome where lower is better. Report effect sizes and paired confidence intervals. The two permutations do not double the sample size.

Use source seed as a repeated block and session/day as a block or random effect. Prespecify N−P and N−R as the principal contrasts and correct the planned contrast family, for example with Holm adjustment if p-values are used. A three-way model is optional if adequately supported; do not fit a high-order interaction to too few independent sources. The principal interaction is timing variant × competitor load.

For a mechanism check, fit a simple queue model on independent calibration data, e.g. Lindley's recurrence `Q_(i+1)=max(0,Q_i+S_i−A_i)`, with a stated service-time model. Test whether it predicts the direction and scale of held-out timing effects. Treat it as an explanatory approximation: MQTT/TCP and 5G involve multiple queues and feedback, so a fitted single-server model is not the ground truth.

If R differs from N, the result is sensitivity to the tested gap-order intervention. It is not a proof of long-range dependence or self-similarity. If only P differs, gap variability is implicated without evidence for an additional ordering effect. If intervals exclude worthwhile effects for all contrasts, report a practical null; wide intervals remain inconclusive.

## Bottleneck and freshness interpretation

| Upstream energy/MAC status | Transport healthy | Transport degraded |
| --- | --- | --- |
| Upstream degraded | Ambient-limited operating point | Joint limitation |
| Upstream healthy | Healthy operating point | Transport-limited operating point |

Freeze upstream and transport thresholds from application needs/calibration and retain their continuous measures. Upstream status must distinguish energy generation outages from attempted-packet decoding failures. By construction, the same source trace has the same upstream status at every competitor load. That is an intervention property, not standalone evidence of a new physical phase transition.

For native traces, compute reader and receiving-application AoI on the same wall-time mapping and population. Quantify downstream added staleness using their time-average difference on a common window; do not assume it equals mean packet transport delay. Treat power/MAC failures and transport failures as distinct reasons for missing fresh information.

## Final figures and completion

Produce: (1) qualified source structure by energy arm, (2) paired N/R/P delay and deadline results across load, (3) planned→publisher→application structure distortion, (4) resource/bottleneck evidence, and (5) native reader-versus-application AoI. A compact causal diagram and full provenance accompany these figures.

The study is complete when the hypotheses can be answered with uncertainty, the timing intervention invariants are independently checked, all exclusions and censored/late events are accounted for, and a fresh session can reconstruct every figure from the retained records. A null answer is a valid completion; a deployment smoke test is not.

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
