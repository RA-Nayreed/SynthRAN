# Experiment 2: causal impact of Ambient-IoT timing on 5G transport

## Objective

Experiment 2 tests whether the temporal structure of an **event-identical** decoded Ambient-IoT workload changes application delivery over the 5G testbed that is currently active in SynthRAN.

The experiment does **not** prescribe a particular core, RAN, radio unit, SOP-node pair, UE identity, or slice. Infrastructure is selected and accepted through `deploy.sh`. `experiment.sh` discovers `.synthran/active-deployment.json`, validates the saved deployment identity plus current reservation coverage, displays the actual testbed to the operator, and asks whether to use it. The chosen deployment hash is then frozen for that Experiment-2 campaign so different testbeds are never mixed silently inside one confirmation series.

## Research questions

- **T1:** For the same decoded event set, does native timing produce a practically meaningful delivery-delay or deadline-failure penalty compared with periodic timing?
- **T2:** Does permuting the order of the exact native inter-event gaps change that penalty, indicating sensitivity to gap ordering beyond the gap histogram?
- **T3:** Does the timing penalty interact with controlled competing 5G load?

The causal comparison is within source seed. Event identity, event order, sensor identity, payload bytes, MQTT topic, event count, source horizon and gateway role are held fixed. Only release timing changes.

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

Extending reservation coverage does not change the scientific deployment identity. If the same deployment hash becomes active again, an incomplete Experiment-2 campaign can resume. If a different deployment hash becomes active, Experiment 2 starts a new campaign instead of combining different testbeds.

At least two verified UE bindings are needed for the full study: the first is assigned the workload role and the second the competing-traffic role for that campaign. These assignments, plus all accepted deployment provenance, are retained in the campaign results.

## Load calibration

The source workload keeps its native 1× time scale. Competing traffic is a separately paced UDP flow through the second UE to an N6-side sink.

Before confirmation, Experiment 2 probes the configured ascending offered-payload grid:

```text
5, 10, 15, 20, 25, 30, 40, 50 Mbps
```

with three repeats per point. Using median end-to-end delivery ratio, the formal rule is:

- **ABOVE** = first rate whose median delivery ratio is below 0.98
- **NEAR** = immediately preceding rate
- **BELOW** = immediately preceding NEAR

If this rule cannot select all three levels, confirmation does not start. The calibration result is preserved rather than inventing an artificial knee.

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

## Measurement

Each run retains stable event identity and the planned/publisher/application timing evidence needed for:

- p95 scheduled-release-to-application delay;
- application deadline-failure fraction;
- publisher release error;
- application receipt delay;
- delivery/loss evidence;
- background-flow delivery ratio;
- deployment and UE-binding provenance.

Cross-host timing claims require an explicit clock-uncertainty bound. Experiment 2 collects controller-bracketed UTC probes from the workload-publisher host and broker host and records the resulting uncertainty bound with the campaign. Seeds whose matched arms do not satisfy the clock contract are excluded only from the affected timing contrast, with the exclusion recorded.

## Analysis

For each load level and source seed, the principal paired contrasts are:

```text
ΔNP = native − periodic
ΔNR = native − mean(gap_permutation_r1, gap_permutation_r2)
```

for the prespecified principal outcomes. Positive values mean native timing is worse for outcomes where lower is better. Paired bootstrap confidence intervals are computed across source seeds. The two gap-permutation arms do not double the statistical sample size.

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
