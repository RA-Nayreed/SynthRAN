# Experiment 1: energy correlation, activation, and burst formation

## Objective

Determine whether cross-sensor correlation in harvested energy synchronizes sensor activity and changes the decoded Ambient-IoT traffic process when each sensor's marginal energy statistics and the RF/MAC configuration are controlled.

The study establishes calibrated energy and contention operating points for later transport experiments. Its contribution is a validated mechanism from harvested-energy dependence through capacitor/controller behavior to decoded event structure. It does not claim that simulated harvesting or backscatter behavior is a physical device measurement.

Correlated harvesting and random access have prior research foundations, including [Abad et al.](https://arxiv.org/abs/1902.04890); availability-aware access is also studied by [Wu et al.](https://arxiv.org/abs/2501.15020). SynthRAN's contribution is therefore the reproducible mechanism/evidence chain and its use as a controlled source process for downstream 5G experiments, not the existence of correlated energy itself.

## Scope and claim boundary

Experiment 1 is a **modeled Ambient-IoT study**. Harvested energy, capacitor dynamics, sensing, access, propagation, collision, decoding, and SIC are simulated. Any later physical N300/N320 replay carries the **5G gateway transport** for a frozen decoded event trace; it does not convert the upstream Ambient-IoT process into a physical implementation.

Model results, physical transport results, and combined end-to-end interpretations must therefore be reported separately.

## Research questions and hypotheses

- **E1:** Near an activation threshold, common harvesting produces more correlated sensor activation and more clustered decoded arrivals than independent harvesting with the same marginal source law.
- **E2:** The effect depends on energy storage and source timescale and is not explained entirely by aligned startup or periodic MAC timing.
- **E3:** Increased harvested energy can improve availability while also increasing contention/collision exposure; the net reader-side freshness effect is empirical rather than assumed monotonic.

Use one modeled reader and fixed RF geometry in the primary design. The primary energy intervention is **environmental harvesting dependence**, while backscatter illumination/link power is held constant across paired energy arms so the treatment does not silently improve the communication channel.

## Model qualification prerequisites

Before generating a scientific energy sweep, retained qualification evidence must cover:

- sensing interval and phase semantics;
- timestamp-preserving irregular energy traces;
- known-period always-powered behavior;
- analytical capacitor charging, leakage, zero-load, and voltage-limit checks;
- numerical timestep convergence on a prespecified subset;
- powered/off command handling;
- complete transmission-energy accounting;
- stable sample/event lineage across sensing, retransmission, and decoding;
- singleton sensitivity/SINR behavior;
- collision and SIC fixtures;
- explicit shared-subcarrier assignments for contention studies.

For each sensing opportunity, distinguish unavailable energy, busy operation, successful generation, pending sample state, transmission attempt, and completed decode. A command that receives no response is not automatically equivalent to a lost generated sample.

The primary model uses at most one pending sample per sensor and no catch-up generation unless an alternative buffering rule is explicitly declared as a separate treatment.

## Controlled energy source

Use a positive stochastic power process with a specified marginal distribution, mean, variance, temporal correlation time, and units. Include a constant-power arm for calibration, but do not interpret a constant source as a meaningful common-versus-independent correlation comparison.

A reproducible dynamic construction is a Gaussian copula:

\[
Z_j(t)=\sqrt{c}\,Z_0(t)+\sqrt{1-c}\,Z_j^{ind}(t),
\qquad
P_j(t)=F_P^{-1}(\Phi(Z_j(t))).
\]

The latent Gaussian processes have equal temporal autocorrelation and unit variance. `c=0` produces independent latent processes and `c=1` a common latent process. Because the marginal transform can change Pearson correlation, report the **realized** power correlation rather than equating it directly with `c`.

Use paired geometry and sensing phases across common/independent arms. Report finite-window source-energy integrals and distributions; independent stochastic realizations are not required to contain exactly equal realized energy.

A phase-shifted copy of one periodic trace is a **phase-offset control**, not an independent energy process. Measured traces, when available, retain their original time axis and provenance.

## Calibration procedure

### 1. Cost and numerical pilot

Evaluate small sensor populations and short runs first, recording wall time, peak memory, initialization transient, and evidence volume. Increase population/duration only after establishing campaign feasibility.

### 2. Geometry and channel validity

Choose a geometry inside the declared propagation model's valid domain. Hold locations and radio parameters fixed across paired energy arms. Record received RF power separately from harvested environmental/DC power.

### 3. Energy sweep

Sweep mean available power across a range that contains energy-limited and predominantly active operation. Measure the effective energy delivered to the capacitor, not only the configured source parameter. Refine around the steepest activation-response region.

### 4. Freeze energy operating points

Select:

- `E-low` — predominantly energy-limited;
- `E-knee` — near the steep activation transition;
- `E-high` — energy rarely prevents operation.

Illustrative active-fraction targets may guide calibration but are not hardcoded scientific truths. Retain the complete response curve and actual selection rule.

### 5. Population sweep

At `E-knee`, increase population under fixed frame/slot settings to identify low-contention, transition, and heavily contended operation. Freeze `N*` near a transition using a prespecified decode/attempt, collision, or related contention criterion.

### 6. Observation window

Choose warm-up from voltage/activation convergence and choose measurement duration to cover multiple relevant source timescales. Verify duration and numerical-step sensitivity on a prespecified subset. Do not select a horizon because one visual trace appears especially bursty.

Pilot seeds and confirmation seeds must be disjoint. Use separate deterministic random streams for geometry, sensing phase, energy, MAC choice, and any surrogate construction so a protocol change does not unintentionally alter every exogenous input.

## Confirmation design

At fixed `N*`, fixed sensing schedules, a shared contention resource, and qualified receiver/SIC behavior, use the following primary arms:

| Arm | Power regime | Cross-sensor dependence |
| --- | --- | --- |
| AP | Always powered | No energy starvation |
| H-I | E-high | Independent |
| H-C | E-high | Common |
| K-I | E-knee | Independent |
| K-C | E-knee | Common |
| L-I | E-low | Independent |
| L-C | E-low | Common |

A planning design of 30 independent source seeds per arm gives 210 confirmation runs. Final confirmation size must be frozen from runtime and precision requirements before confirmation begins.

Prespecified secondary controls may include:

- intermediate dependence such as `c=0.5`;
- randomized versus deliberately aligned sensing phases;
- an orthogonal/no-collision access control;
- a limited storage-capacitance sensitivity.

Secondary controls should answer one mechanism question at a time rather than becoming an unconstrained factorial expansion.

## Required measurements

| Layer | Measurements |
| --- | --- |
| Energy | Input-energy integral, capacitor-energy change, operating/leakage/series/PMIC losses, voltage distribution, active fraction, threshold crossings, outage intervals |
| Generation | Opportunities, generated samples, energy/busy suppressions, generation time, pending/overwritten state when applicable |
| MAC | Attempts, airtime, command overhead, collision/capture/SIC outcomes, sensitivity/SINR failures, per-source success probability |
| Traffic structure | Event rate, inter-event-gap CV, count-window Fano factor, count autocorrelation, peak count/window, frozen burst/run-length descriptors |
| Dependence | Pairwise harvested-power correlation, activation correlation, wake-up-lag distribution |
| Utility | Reader-side AoI/freshness, equal-weight per-sensor successful-update rate, fairness, starvation |

Define the count-window Fano factor as:

\[
F(w)=\frac{\mathrm{Var}[N_w]}{\mathrm{E}[N_w]}.
\]

Window width, origin, overlap policy, and zero-mean handling are frozen. Fano factor and count index of dispersion are the same statistic under this definition and must not be treated as independent evidence.

Energy per successful decoded update includes expenditure on unsuccessful attempts. Do not infer consumed energy from capacitor-voltage drop alone while harvesting remains active.

## Primary analysis

The principal comparison is **common minus independent harvesting at `E-knee`**, paired by source seed.

Primary mechanism outcomes are:

- activation dependence/correlation;
- one preregistered traffic-burst statistic such as the Fano factor at a scientifically relevant window.

Report the full Fano/window sensitivity as supporting evidence and label unplanned window selection as exploratory.

Use paired effect estimates with confidence intervals and, where supported by sample size, an energy-regime × dependence interaction. Report event-rate differences explicitly: common and independent harvesting may legitimately produce different decoded volumes, so this comparison alone does not establish a rate-independent transport effect.

## Falsification and interpretation

E1 is unsupported when the dependence effect is negligible, inconsistent, or explained by startup/frame-phase controls. A confidence interval inside a prospectively defined negligible-effect region can support a practical null; a wide interval is inconclusive.

E3 may be non-monotonic. Both improved availability and increased collision exposure are admissible outcomes.

Illustrative traces are selected prospectively or by fixed seed identity and are not treated as the statistical sample.

Recommended figures include:

1. energy-response curves with frozen operating points;
2. source/voltage/activation/decoded-event panels for prespecified seeds;
3. common-versus-independent traffic-structure curves;
4. energy–contention–reader-utility operating maps.

## Handoff to downstream transport experiments

Export generated and decoded events with stable event identity, modeled generation time, completed reader-decode time, sensor identity, gateway assignment, and payload hash. Retain warm-up history and sensors that produce no output.

Downstream experiments select source bundles by frozen seed/campaign identity, never by whether an individual trace supports the desired hypothesis. Native physical replay begins from completed modeled reader-decode availability while preserving the original generation timestamp for valid AoI calculations.

Timing transformations that move release before modeled generation must explicitly mark generation-based AoI as invalid for that transformed arm.

## Reproducibility and evidence

Retain the versioned scientific design, calibration evidence, frozen confirmation contract, source/dependency fingerprint, complete run bundles, run dispositions, exclusions, and analysis outputs. Existing immutable run bundles are validated and reused rather than overwritten.

Historical Experiment-1 results are documented separately in [`RESULTS.md`](RESULTS.md). Historical aggregates remain evidence about the historical campaign; they do not replace calibration under a newer implementation.

Shared event-timing, AoI, experimental-unit, and failure-taxonomy conventions used by downstream transport studies are summarized in [`../MEASUREMENT_AND_INFERENCE.md`](../MEASUREMENT_AND_INFERENCE.md).

## Completion criteria

Experiment 1 is complete for a declared campaign when:

1. model qualification gates pass under the exact implementation used;
2. energy and contention operating points are selected from independent calibration evidence;
3. the confirmation treatment matrix and seeds are frozen prospectively;
4. every assigned run has an explicit retained disposition;
5. primary contrasts are analyzed with uncertainty at the source-seed level;
6. model claims remain separated from any later physical 5G transport claims;
7. the retained evidence is sufficient to reproduce each reported statistic from the frozen source bundles.
