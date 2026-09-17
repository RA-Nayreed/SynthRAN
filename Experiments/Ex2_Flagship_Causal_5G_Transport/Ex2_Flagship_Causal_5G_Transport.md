# Experiment 2: causal impact of Ambient-IoT timing on 5G transport

## Objective

Experiment 2 tests whether the temporal structure of an **event-identical** decoded Ambient-IoT workload changes application delivery over an accepted 5G testbed.

Infrastructure is selected and accepted through `deploy.sh`; it is not part of the treatment definition. `experiment.sh` discovers the accepted deployment identity, verifies current reservation coverage, records the actual core/RAN/radio/node/UE configuration, and freezes that deployment identity together with the scientific design for the campaign.

## Research questions

- **T1:** For the same decoded event set, does native timing produce a delivery-delay or deadline-failure penalty relative to periodic timing?
- **T2:** Does native timing differ from the mean of two exact-gap permutations, indicating sensitivity to gap ordering beyond the gap histogram?
- **T3:** Does either timing effect change under controlled competing 5G load?

The causal comparison is within source seed. Event identity, order, sensor identity, payload bytes, MQTT topic, event count, source horizon, and gateway role are held fixed. Only release timing changes.

A statistically nonzero effect is not automatically a practically meaningful effect. Practical importance or equivalence requires an independently justified margin frozen before interpreting confirmation data.

## Source cohort

Experiment 2 uses the 30 frozen `knee-common` confirmation seeds from the selected complete Experiment-1 campaign. The prepared cohort is stored under:

```text
results/experiments/ex2-source/<experiment-1-campaign-id>/
```

For each source seed, four matched timing arms are generated:

| Arm | Intervention |
| --- | --- |
| `native` | original completed-reader-decode timing |
| `gap_permutation_r1` | deterministic permutation of native measurement gaps |
| `gap_permutation_r2` | independent deterministic permutation of the same gap multiset |
| `periodic` | same first/last measurement release and event count, with evenly spaced interior releases |

Both gap-permutation controls preserve the native measurement-gap multiset. The two permutations are repeated matched controls; they do not create additional independent source replicates.

## Accepted-testbed execution model

`deploy.sh` owns infrastructure. `experiment.sh` owns scientific execution.

Physical phases consume an already accepted deployment and do not reserve, repair, power-cycle, rebuild, or reconfigure infrastructure. If reservation coverage is absent or expired, the experiment stops.

An incomplete campaign may resume only when the same deployment identity and scientific design regain valid reservation coverage. A changed deployment or changed design starts a separate campaign rather than mixing incompatible evidence.

The full study requires at least two verified UE bindings: one workload UE and one competing-traffic UE. Their bindings, routes, selected service profile, and accepted deployment provenance are retained with campaign evidence.

## Load calibration

The source workload keeps its native 1× time scale. Competing traffic is a separately paced UDP flow through the competing UE to an N6-side sink.

Design version 2 probes the ascending requested application-payload grid:

```text
5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250 Mbps
```

with three repeats per point. Every repeat must achieve 95–105% of its requested application-payload rate and report zero sender errors. A rate whose repeat set fails that generator-validity contract cannot characterize the network.

Using median end-to-end UDP delivery ratio over a complete valid repeat set:

- **ABOVE** = first ascending rate with median delivery ratio below 0.98;
- **NEAR** = immediately preceding valid rate;
- **BELOW** = valid rate immediately preceding NEAR.

The sweep stops once the first valid crossing is established. If the generator is invalid, the grid remains unbracketed, or the crossing lacks two valid predecessors, confirmation remains blocked. Every completed probe is retained in `calibration/load-selection.json`.

These labels describe an operational end-to-end UDP loss boundary. They do **not** by themselves identify queueing onset, radio saturation, path capacity, or the bottleneck layer.

## Read-only transport evidence

Calibration and confirmation retain bounded snapshots from the accepted deployment without changing configuration. Where exposed, evidence includes:

- proved routes of both experiment UEs to the N6 endpoint;
- interface packet/error/drop counters;
- selected kernel IP/TCP/UDP counters;
- queue-discipline state;
- relevant gNB/core process presence;
- Kubernetes pod identity/readiness/restart counts;
- host uptime, load, and clock state.

Calibration records before/after snapshots. Confirmation records session boundaries and reservation pause/resume boundaries.

This evidence supports infrastructure-stability checks and bottleneck diagnosis, but it does not automatically attribute an observed effect to radio scheduling. A radio-specific claim requires aligned scheduler/resource evidence.

## Confirmation design

The confirmation matrix is:

```text
30 source seeds
× 4 timing arms
× 3 calibrated load levels
= 360 transport replays
```

Source seed is the independent experimental unit. Three 10-seed sessions organize execution and drift checks but do not increase sample size.

Within each source-seed/load block, the four timing arms are deterministically randomized. Complete matched blocks are the execution unit. A drift sentinel is run every 12 replays.

Before starting a matched block, the experiment checks whether reservation coverage plus the configured safety margin is sufficient. If not, the campaign pauses **before** the block and resumes only after coverage is extended for the same deployment.

Each replay retains the actual competing-flow sender result. A load treatment is valid only when the sender achieved 95–105% of the frozen requested rate with zero sender errors. An invalid arm is excluded only from contrasts that require it, and the source seed, arm, and exclusion reason remain in the evidence.

## Measurement

Each run retains stable event identity and the timing/application evidence needed for:

- p95 scheduled-release-to-application delay;
- application deadline-failure fraction;
- publisher release error;
- application receipt delay;
- delivery and missing-event evidence;
- requested and achieved competing-flow rate plus delivery ratio;
- accepted deployment and UE-binding provenance.

Cross-host timing claims require an explicit clock-uncertainty bound. Before qualification and each confirmation session, the experiment collects controller-bracketed UTC probes from the workload-publisher and broker hosts. Timing execution is blocked unless both endpoints report NTP synchronization and a finite, nonnegative relative-clock uncertainty bound can be retained.

The observed bound is reported with the campaign and interpreted relative to the size of any claimed timing effect. The synchronization gate prevents plainly unsynchronized runs; it does not prove zero drift throughout a long session.

Shared timing, receipt, AoI, clock, and failure-taxonomy conventions are defined in [`../MEASUREMENT_AND_INFERENCE.md`](../MEASUREMENT_AND_INFERENCE.md).

## Analysis

For each load level and source seed, the principal paired contrasts are:

```text
ΔNP = native − periodic
ΔNR = native − mean(gap_permutation_r1, gap_permutation_r2)
```

For lower-is-better outcomes, positive values mean a native-timing penalty.

Eligibility is **contrast-specific**. `ΔNP` requires only valid native and periodic measurements. `ΔNR` requires native plus both gap permutations. A missing or invalid gap-permutation arm therefore does not discard an otherwise valid native-versus-periodic estimate.

The prespecified paired load interactions are:

```text
ΔNP(near)  − ΔNP(below)
ΔNP(above) − ΔNP(below)
ΔNR(near)  − ΔNR(below)
ΔNR(above) − ΔNR(below)
```

The same source seed must be eligible for the relevant contrast at both compared loads.

Paired percentile-bootstrap confidence intervals use 10,000 deterministic resamples across source seeds. The two gap-permutation controls do not increase the number of independent source replicates. Reported 95% intervals are pointwise and are not familywise multiplicity-adjusted.

## Scientific interface

The public launcher is:

```bash
./experiment.sh
```

The phase chain is:

```text
prepare → qualification → calibration → freeze → confirmation → analysis
```

The user does not supply a session number, generated transport scenario, or a separate core/RAN/radio treatment choice for this experiment.

## Results and archival

Campaign output is stored under:

```text
results/experiments/ex2/<campaign-id>/
```

Working results remain ordinary directories and may be transferred between execution hosts without changing campaign identity.

Object-storage archival is optional and separate from scientific execution:

```bash
python -m synthran.archive_cli results/experiments/ex2/<campaign-id> \
  --alias <mc-alias> \
  --bucket <bucket> \
  --prefix <prefix>
```

No object-storage destination is hardcoded into Experiment 2.

## Claim boundary

Experiment 2 can establish a conditional effect of release timing on application delivery under the retained source cohort, accepted deployment, competing-load treatment, and measurement contract.

It does not by itself identify the radio scheduler as the cause, validate physical Ambient-IoT harvesting/backscatter behavior, establish a universal 5G capacity threshold, or prove standards compliance.
