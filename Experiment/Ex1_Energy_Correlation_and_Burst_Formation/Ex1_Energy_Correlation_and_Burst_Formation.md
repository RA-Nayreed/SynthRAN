# Experiment 1: energy correlation, activation and burst formation

## Objective and publication role

Determine whether spatial correlation in harvested energy synchronizes sensor activity and changes the decoded Ambient-IoT traffic process when each sensor's energy statistics and the RF/MAC configuration are controlled. Establish calibrated energy and contention operating points for later 5G replay.

This is feasible after correcting the source, controller, capacitor and receiver semantics. It is a strong mechanism component of the flagship. Correlated harvesting and random access already appear in [Abad et al.](https://arxiv.org/abs/1902.04890), and availability-aware access appears in [Wu et al.](https://arxiv.org/abs/2501.15020). The added value is a validated capacitor-to-decoded-traffic mechanism with reusable workloads and a subsequent physical-transport consequence. Simulation curves alone should not be presented as proof of real tag behavior.

## Context for a fresh ChatGPT session

Use this file as a standalone experiment brief for **RA-Nayreed/SynthRAN**. Read the current relevant source before changing or running anything. The review baseline was `main` at `ccaa385174fa695bdaa669e6046b61e80283a0be`, inspected on **8 September 2026**. The physical N320 candidate was draft PR [#7](https://github.com/RA-Nayreed/SynthRAN/pull/7), head `21d0dddb2792a004e529afc3144ab7aaa1eea941`. Its prose mentioned an older hash; the API head was authoritative. Recheck the current revision and retain improvements already present.

SynthRAN executes an Amber-derived SimPy model of energy harvesting, capacitor/controller operation and backscatter access. It freezes decoded events into JSONL, then replays them over MQTT through an actual 5G UE interface to an N6-side application. The Ambient-IoT radio and harvesting are **modeled**. The N320 carries the **5G gateway transport**; it does not make the upstream Ambient-IoT link a physical implementation.

The revised campaign uses **one fixed OAI core + srsRAN gNB + N320 physical-radio configuration**, after a clean acceptance run. This choice follows the repository's active physical reference. It replaces the attachment's Open5GS/RFSIM choice once, before data collection; it introduces no core comparison. RFSIM with the same core is useful for qualification. Its different UE software, band, numerology and image mean its measurements must be analyzed separately. If an already accepted Open5GS/N320 deployment is used instead, freeze that choice before the pilot and revise the manifest consistently; do not mix cores in a result series.

Use a homogeneous slice/DNN/QoS assignment except in the explicit isolation study. The shipped default profile assigns `uesim01` and `uesim02` to different slices, so it is not an appropriate neutral baseline. Begin with two proven physical UE roles: gateway A and competing-traffic UE B. Use only the N320 for physical-radio studies. Node availability and runtime capability require live evidence; scenario examples are not proof.

Complete the necessary model and instrumentation corrections, produce runnable scenario/analysis/campaign files, run qualification and then the declared experiment where resources are available. If physical access is absent, complete all local work and give the exact remaining live commands with their acceptance criteria. Report preparation, simulated results and physical measurements separately. At the end of every working session, retain a concise checkpoint with the actual commit, completed gates, artifact paths/hashes, failures and the next executable step. This file does not require any other handoff file to be understood.

## Questions and hypotheses

- **E1:** Near an activation threshold, common harvesting produces more correlated activation and more clustered decoded arrivals than independent harvesting with the same marginal source law.
- **E2:** The effect depends on capacitor storage and energy timescale; it is not explained entirely by aligned startup or periodic MAC frames.
- **E3:** More harvested energy may improve availability while increasing collision exposure. Whether reader-side freshness improves is an empirical question.

Use one modeled reader and static RF geometry initially. Main energy variation is **environmental harvesting**, with constant RF illumination and identical link powers across paired energy arms. This prevents an energy-power intervention from silently improving the backscatter channel too.

## Readiness specific to this study

Read `Experiment/ambient_iot/{config,runner,protocols,bridge,evidence,outcomes}.py` and `Experiment/model/{capacitor,controller,propagation,backscatter,bsengine,packet_analysis}.py`.

The reviewed code ignored sensing intervals and CSV timestamps; `wpt_power_w` had no effect; one energy actor served all sensors; capacitor branches accounted for charging differently; generation/completed-decode timestamps were absent. Missing subcarrier assignments gave nodes separate subcarriers. The receiver also accepted singleton packets without applying the same SINR threshold used for collisions. Resolve these before generating a scientific energy sweep.

Acceptance evidence must include a known-period always-powered source, an irregular timestamp trace, analytical charging/leakage/zero-load tests, timestep convergence, powered/off command handling, completed-transmission energy accounting, true sample identity and SIC fixtures. Use explicit shared-subcarrier assignments for contention.

For each sensing opportunity, log unavailable energy, busy operation, successful generation, pending sample state, transmission attempt and completed decode as separate events. A polling command that received no response is not automatically a lost generated sample. Keep one pending sample per sensor and no catch-up generation in the primary model; declare any alternative buffering rule separately.

## Controlled energy sources

Use a positive stochastic power process with a specified marginal distribution, mean, variance and temporal correlation time. Freeze its construction and its units. Include a constant-power arm for calibration; a constant source cannot have a meaningful common-versus-independent correlation comparison.

A reproducible option for dynamic traces is a Gaussian-copula construction:

\[
Z_j(t)=\sqrt{c}\,Z_0(t)+\sqrt{1-c}\,Z_j^{ind}(t),
\qquad P_j(t)=F_P^{-1}(\Phi(Z_j(t))).
\]

The Gaussian processes have identical temporal autocorrelation and unit variance. This preserves each source's marginal law while changing shared dependence. `c=0` gives independent latent processes and `c=1` a common process. `c` is not generally the Pearson correlation of the transformed power; measure and report the realized correlation. Do not use a simple weighted average of positive traces and assume its variance stays unchanged.

Use common and independent realizations of the same source law, with paired geometry and sensing phases. Report finite-window power integrals and distributions; random draws need not have exactly equal realized energy. A sensitivity analysis can use equal-energy-duration traces, clearly distinguishing that conditioning from the original stochastic source law.

An independently phase-shifted copy of a single periodic trace is a **phase-offset control**, not a genuinely independent energy source. Use it as a separate robustness test if useful.

Choose the primary power-correlation timescale from a plausible harvesting scenario and its source evidence. A pilot can inspect 1, 5 and 20 seconds, but these are synthetic sensitivity settings, not measured environmental values. If measured traces become available, retain their original time axis and provenance and reserve some for validation. Do not label model parameters as a standardized device class without an energy-budget justification.

## Calibration procedure

1. **Cost and physics pilot.** Try 8, 16 and 32 modeled sensors and 60-second runs. Record wall time, peak memory, initialization transient and logging volume. Increase population/duration only after estimating the campaign cost. Current millisecond histories are not evidence that large populations are cheap.
2. **Geometry.** Choose a valid channel domain with useful reception powers. With the existing UMa model, exclude the invalid below-10-m region. Hold locations and radio parameters identical across the energy arms. Record received power separately from harvested DC power.
3. **Energy sweep.** At a moderate population, sweep mean available power logarithmically over a range that actually contains inactive and predominantly active operation. Measure effective energy delivered to the capacitor, not just the YAML value. Refine around the steepest activation response.
4. **Freeze three energy points.** Choose `E-low` in a mostly energy-limited region, `E-knee` near the steep response, and `E-high` where energy rarely prevents operation. Active fractions around 10–30% and above 90% are useful descriptive targets, not guarantees. Retain the response curve if these states cannot be separated.
5. **Population sweep.** At `E-knee`, increase population with a fixed frame/slot configuration to identify low-contention, transition and heavily contended states. Start with 8/16/32/64/128 only while runtime and the source model remain credible. Freeze `N*` near a transition using an explicit decode/attempt or collision criterion from the pilot.
6. **Observation window.** Select a warm-up from voltage/activation convergence and a measurement duration covering at least several dozen relevant energy cycles where affordable. Verify sensitivity to doubled duration and finer numerical timestep on a small prespecified subset. Do not choose a window solely because its plotted burst looks striking.

Keep pilot seeds `1–5` separate from confirmation seeds. A suggested confirmation set is `1001–1030`; store separate streams for geometry, sensing phases, energy, MAC choices and surrogate generation so protocol changes do not accidentally alter every subsequent random draw.

## Main design

At fixed `N*`, fixed sensing periods/phases, one shared contention subcarrier and broadcast SIC with qualified residual cancellation:

| Arm | Power regime | Cross-sensor dependence |
| --- | --- | --- |
| AP | Always powered | No starvation; same schedules/channel |
| H-I | E-high | Independent |
| H-C | E-high | Common |
| K-I | E-knee | Independent |
| K-C | E-knee | Common |
| L-I | E-low | Independent |
| L-C | E-low | Common |

Thirty source seeds per arm gives **210 model runs** before calibration and sensitivity cases. This is a planning size; determine feasibility from the cost pilot and statistical precision. Run isolated processes when parallelizing simulations, because the current runner resets global random generators.

Prespecify a small secondary subset at `E-knee`: intermediate dependence `c=0.5`; randomized versus deliberately aligned sensing phases; an orthogonal/no-collision access control; and one smaller/larger storage value with all energy-accounting parameters reported. Change one secondary question at a time. Do not multiply all sensitivities into the primary factorial.

## Required measurements

| Layer | Measurements |
| --- | --- |
| Energy | Input-power integral, capacitor-energy change, operating/leakage/series/PMIC losses, voltage distribution, active fraction, threshold crossings, outage durations |
| Generation | Opportunities, true generated samples, energy/busy suppressions, generation times, pending/overwritten samples if the selected policy allows them |
| MAC | Attempts and airtime, command overhead, capture/actual SIC-stage decodes, collisions, sensitivity/SINR failures, per-source success probability |
| Structure | Event rate, inter-event-gap CV, count-window Fano curve, count autocorrelation, peak count/window, burst-duration/run-length under a frozen threshold |
| Correlation | Pairwise harvested-power correlation, activation correlation and wake-up lag distribution |
| Utility | Reader-side AoI, AoI violations, equal-weight per-sensor successful-update rate and fairness |

Define `F(w)=Var[N_w]/E[N_w]` using fixed count-window widths. Fano factor and the count index of dispersion are the same quantity under this definition; do not count them as independent evidence. Use windows such as 10/50/100 ms and 0.5/1/5 seconds when resolvable by the model and useful for the observed energy/MAC timescales. Record window origin, overlap policy and zero-mean handling. Do not divide by zero for a silent trace.

Use voltage/energy state intervals for active fraction. Count energy per successfully decoded update across all nodes, including expenditure on unsuccessful attempts. Do not estimate consumed energy from voltage drop alone while harvesting is active.

## Analysis, falsification and figures

Primary contrast: common minus independent harvesting at `E-knee`, paired by source seed. Primary mechanism outcomes are activation correlation and Fano factor at one preregistered scientifically relevant window. Report the full Fano curve as supporting evidence, with simultaneous uncertainty or a clear exploratory label for unplanned windows.

Use confidence intervals for paired effects and an energy-regime-by-dependence interaction where the sample size supports it. Report rate differences; common versus independent energy can legitimately change event volume, so this model comparison alone does not establish a rate-independent downstream effect. Export all traces for later within-trace timing controls.

E1 is unsupported if the effect is too small, inconsistent or explained by the startup/frame-phase controls. A confidence interval inside a prespecified negligible-effect band supports a practical null; a wide interval is inconclusive. E3 need not be monotonic: either outcome should be retained.

Produce: (1) energy-response curves with the chosen points, (2) input/voltage/activation/decoded-event panels for prespecified illustrative seeds, (3) common/independent Fano curves, and (4) energy–collision–reader-freshness operating maps. Do not use illustrative seeds as the statistical sample.

## Handoff to physical replay

Export all generated and decoded events, including modeled warm-up history and sensors with no output. Freeze the chosen AP, K-I and K-C confirmation seeds in a source manifest. The 5G flagship may use a prespecified subset chosen by seed ID, never by whether its result supports the hypothesis. The physical workload begins at **completed reader decode availability**, preserving the original generation timestamp for native AoI.

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
