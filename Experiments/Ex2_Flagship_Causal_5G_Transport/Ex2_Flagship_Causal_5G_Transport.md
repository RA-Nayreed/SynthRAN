# Experiment 2: causal impact of Ambient-IoT timing on 5G transport

## Objective

Experiment 2 tests whether the temporal structure of an **event-identical** decoded Ambient-IoT workload changes application delivery over the 5G testbed that is currently active in SynthRAN.

The experiment does **not** prescribe a particular core, RAN, radio unit, SOP-node pair, UE identity, or slice. Infrastructure is selected and accepted through `deploy.sh`. `experiment.sh` discovers `.synthran/active-deployment.json`, validates the saved deployment identity plus current reservation coverage, displays the actual testbed to the operator, and asks whether to use it. The chosen deployment hash and scientific design contract are then frozen for that Experiment-2 campaign so different testbeds or analysis rules are never mixed silently inside one confirmation series.

## Research questions

- **T1:** For the same decoded event set, does native timing produce a delivery-delay or deadline-failure penalty compared with periodic timing?
- **T2:** Does native timing differ from the mean of two exact-gap permutations, indicating sensitivity to gap ordering beyond the gap histogram?
- **T3:** Does either timing penalty change with controlled competing 5G load?

The causal comparison is within source seed. Event identity, event order, sensor identity, payload bytes, MQTT topic, event count, source horizon and gateway role are held fixed. Only release timing changes.

A statistically nonzero effect is not automatically a practically meaningful effect. Experiment 2 does not declare equivalence or practical importance without an independently justified margin specified before interpreting confirmation data.

## Source cohort

Experiment 2 uses all **30 frozen `knee-common` confirmation seeds** from the completed Experiment-1 campaign. Source preparation is local and can therefore run on Roihu. It produces a transferable cohort under:

```text
results/experiments/ex2-source/<experiment-1-campaign-id>/
```

That directory can be copied directly to Duckburg with `rsync`; the complete Experiment-1 campaign does not need to be copied to Duckburg.

For each source seed four matched timing arms are prepared:

| Arm | Intervention |
| --- | --- |
| `native` | original completed-decode timing |
| `gap_permutation_r1` | deterministic permutation of the native measurement gaps |
| `gap_permutation_r2` | independent deterministic permutation of the same gaps |
| `periodic` | same first/last measurement release and event count, with evenly spaced interior releases |

Both gap-permutation controls preserve the native measurement gap multiset. The two permutations are repeated controls; they do not create additional independent source seeds.

## Active-testbed execution model

`deploy.sh` owns infrastructure. `experiment.sh` owns science.

When Experiment 2 starts, it reads the accepted deployment endpoint, rechecks its identity, reports the actual core/RAN/platform/radio/nodes/UE bindings, checks current reservation coverage, and asks:

```text
Run Experiment 2 on this active testbed? [y/N]
```

If the reservation is absent or expired, the experiment does not reserve or repair anything; it stops and tells the operator to extend or reacquire coverage through `deploy.sh`.

Extending reservation coverage does not change the scientific deployment identity. If the same deployment hash and scientific design become active again, an incomplete Experiment-2 campaign can resume. If either the deployment or scientific design changes, qualification/full execution starts a separate campaign instead of combining incompatible evidence.

At least two verified UE bindings are needed for the full study: the first is assigned the workload role and the second the competing-traffic role for that campaign. These assignments, plus all accepted deployment provenance, are retained in the campaign results.

## Load calibration

The source workload keeps its native 1× time scale. Competing traffic is a separately paced UDP flow through the second UE to an N6-side sink.

Design version 2 probes the configured ascending offered-payload grid:

```text
5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250 Mbps
```

with three repeats per point. Every repeat must achieve 95–105% of its requested application-payload rate and report zero sender errors. A rate whose repeat set does not satisfy that generator-validity contract cannot be used to characterize the network.

Using median end-to-end UDP delivery ratio over a complete valid repeat set, the formal rule is:

- **ABOVE** = first ascending rate whose median delivery ratio is below 0.98
- **NEAR** = immediately preceding valid rate
- **BELOW** = immediately preceding NEAR

The sweep stops once the first valid crossing is established. If the generator is invalid, the grid remains unbracketed, or the crossing occurs without two valid predecessors, confirmation does not start. Every completed probe is retained in `calibration/load-selection.json` before the phase stops.

These labels are operational positions around an end-to-end UDP loss boundary. They do **not** by themselves identify the onset of queueing, prove radio saturation, establish path capacity, or locate the bottleneck.

## Read-only transport evidence

Calibration and confirmation retain bounded snapshots from the accepted deployment without changing its configuration. The evidence includes the proved routes of both experiment UEs to the N6 endpoint, interface packet/error/drop counters, selected kernel IP/TCP/UDP counters, queue-discipline state when exposed, relevant gNB/core process presence, relevant Kubernetes pod identity/readiness/restart counts when exposed, and host uptime/load/clock state.

Calibration records before/after snapshots. Confirmation records session-start/session-end snapshots and evidence at reservation pause/resume boundaries. The same accepted deployment inventory and SSH contract produced by `deploy.sh` is reused.

This evidence supports infrastructure-stability checks and possible bottleneck diagnosis. It is not automatically evidence that a measured effect was caused specifically by the radio scheduler. A radio-specific attribution requires the corresponding scheduler/resource evidence to be exposed and aligned with the replay interval.

## Confirmation design

The confirmation matrix is:

```text
30 source seeds
× 4 timing arms
× 3 calibrated load levels
= 360 transport replays
```

Source seed is the independent experimental unit. Confirmation is divided into three 10-seed sessions for organization and drift control, but session choice is internal; the user does not supply a session flag.

Within each source-seed/load block, the four timing arms are deterministically randomized. Complete matched blocks are the unit of execution. A drift sentinel is run every 12 replays.

Before starting a matched block, Experiment 2 checks how much reservation time remains. If the next block does not fit with the configured safety margin, the campaign pauses **before** that block. After reservation coverage is extended for the same deployment, rerunning `experiment.sh` reuses completed run records and continues.

Each confirmation replay also retains the actual competing-flow sender result. Analysis treats an arm as a valid load treatment only when its sender achieved 95–105% of the frozen requested rate and reported zero sender errors. An invalid load treatment is not silently reclassified; it is excluded only from the contrasts that require that arm, with the reason retained.

## Measurement

Each run retains stable event identity and the planned/publisher/application timing evidence needed for:

- p95 scheduled-release-to-application delay;
- application deadline-failure fraction;
- publisher release error;
- application receipt delay;
- delivery/loss evidence;
- background-flow requested and achieved rate plus delivery ratio;
- deployment and UE-binding provenance.

Cross-host timing claims require an explicit clock-uncertainty bound. Before qualification and each confirmation session, Experiment 2 collects controller-bracketed UTC probes from the workload-publisher host and broker host. Timing execution is blocked unless **both endpoints report NTP synchronization** and the controller can retain a finite, nonnegative relative-clock uncertainty bound.

Revision 2 deliberately does not invent an arbitrary maximum acceptable uncertainty. The observed bound is retained with the campaign and must be reported and considered against the magnitude of any claimed timing effect. This clock gate prevents plainly unsynchronized runs; it does not prove zero clock drift throughout a long session.

## Analysis

For each load level and source seed, the principal paired contrasts are:

```text
ΔNP = native − periodic
ΔNR = native − mean(gap_permutation_r1, gap_permutation_r2)
```

for the prespecified principal outcomes. Positive values mean native timing is worse for outcomes where lower is better.

Eligibility is **contrast-specific**. `ΔNP` requires only valid native and periodic measurements. `ΔNR` requires native plus both gap permutations. Consequently, a missing, clock-invalid, load-treatment-invalid, or undefined gap-permutation arm does not discard an otherwise valid native-versus-periodic estimate. Every exclusion is retained with its seed, affected arm and reason.

Experiment 2 also estimates the prespecified paired load interactions:

```text
ΔNP(near)  − ΔNP(below)
ΔNP(above) − ΔNP(below)
ΔNR(near)  − ΔNR(below)
ΔNR(above) − ΔNR(below)
```

The same source seed must be eligible for the relevant contrast at both compared loads. Positive interaction values mean the native-timing penalty is larger at the stronger load than at BELOW.

Paired percentile-bootstrap confidence intervals are computed across source seeds with 10,000 deterministic resamples. The two gap-permutation arms do not increase the statistical sample size. The reported 95% intervals are pointwise and have no multiplicity adjustment; they must not be interpreted as familywise-confirmed evidence across all outcomes, loads and contrasts.

## User interface

The only user-facing launcher is:

```bash
./experiment.sh
```

The Experiment-2 phase chain is:

```text
prepare → qualification → calibration → freeze → confirmation → analysis
```

No public Experiment-1 campaign-path flag, generated transport-scenario path, testbed-profile flag, or session flag is required.

## Results and optional S3 archival

Normal Experiment-2 results are written under:

```text
results/experiments/ex2/<campaign-id>/
```

Working results are ordinary directories and can be moved between Roihu and Duckburg with `rsync`; they do not need to be tarred merely for transport.

S3 is optional and is not part of scientific execution. After a completed result directory is available on a host with the configured object-storage client, archive it explicitly with:

```bash
python -m synthran.archive_cli results/experiments/ex2/<campaign-id> \
  --alias <mc-alias> \
  --bucket <bucket> \
  --prefix <prefix>
```

No S3 alias, bucket, or prefix is hardcoded into Experiment 2.
