# Experiment 2 — causal 5G transport

Experiment 2 tests whether the **timing structure** of an event-identical Ambient-IoT workload changes application delivery over a 5G testbed accepted by SynthRAN.

The executable contract is [`experiment.yml`](experiment.yml). The research design and inference contract are in [`Ex2_Flagship_Causal_5G_Transport.md`](Ex2_Flagship_Causal_5G_Transport.md). Detailed scientific rationale, calibration interpretation, and limitations are documented in [`SCIENTIFIC_RATIONALE.md`](SCIENTIFIC_RATIONALE.md).

## Scientific interface

Use the public experiment controller:

```bash
./experiment.sh
```

Select **Experiment 2**. Its phase chain is:

```text
prepare → qualification → calibration → freeze → confirmation → analysis
```

Infrastructure selection remains outside the study design. `deploy.sh` owns infrastructure; `experiment.sh` discovers the accepted deployment, validates its identity and reservation coverage, records the actual core/RAN/radio/node/UE configuration, and asks the operator whether to execute the study on that deployment.

Experiment 2 does not require a user-supplied Experiment-1 path, transport YAML, core/RAN/radio selection, or session number.

## Design summary

The primary confirmation campaign uses:

```text
30 frozen knee-common Experiment-1 source seeds
× 4 matched timing arms
× 3 calibrated competing-load levels
= 360 transport replays
```

The timing arms are:

- `native`;
- `gap_permutation_r1`;
- `gap_permutation_r2`;
- `periodic`.

Source seed is the independent experimental unit. The two gap permutations are repeated matched controls, not additional independent samples.

The competing-load levels are selected prospectively from a UDP calibration curve. **ABOVE** is the first ascending requested rate whose valid repeat set has median delivery ratio below 0.98; **NEAR** is its immediate valid predecessor; **BELOW** is the valid level preceding NEAR.

Design version 2 uses the grid:

```text
5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250 Mbps
```

Every calibration repeat must achieve 95–105% of its requested application-payload rate with zero sender errors. These levels characterize an operational end-to-end UDP loss boundary; they do not by themselves identify queueing onset, radio saturation, path capacity, or the bottleneck layer.

If the grid remains unbracketed, the generator is invalid, or the crossing lacks two valid predecessors, confirmation remains blocked and the calibration evidence is retained.

## Campaign identity and calibration revision

A changed scientific design contract starts a new campaign even when the accepted deployment is unchanged. Previous campaigns remain immutable and are not silently reinterpreted under newer calibration or analysis rules.

`calibration/load-selection.json` retains requested/achieved sender rates, per-probe validity, delivery statistics, and the selection state. A valid unbracketed sweep remains a pilot result; the response is an explicit prospective design revision, not a relaxed threshold or a forced ABOVE label.

## Source cohort preparation and transfer

The `prepare` phase is local. It discovers the newest complete eligible Experiment-1 campaign and creates the transferable source cohort at:

```text
results/experiments/ex2-source/<experiment-1-campaign-id>/
```

The prepared cohort can be transferred between execution hosts with a file-preserving mechanism such as `rsync`, retaining the repository-relative path. The complete Experiment-1 campaign is not required on the physical execution host once the validated source cohort has been prepared.

## Testbed, telemetry, and reservation behavior

Physical phases consume the deployment already accepted by `deploy.sh`. The experiment records deployment hash, core, RAN, radio, nodes, UE bindings, and selected slices as provenance rather than prescribing them in advance.

Calibration and confirmation retain **read-only transport snapshots** from accepted hosts. Where available, these include:

- UE/interface counters and proved routes to N6;
- selected kernel IP/TCP/UDP counters;
- queue disciplines;
- relevant gNB/core process presence;
- Kubernetes pod identity/readiness/restart state;
- host uptime/load/clock state.

The experiment does not restart, repair, power-cycle, or reconfigure infrastructure to obtain telemetry.

This evidence supports stability checks and bottleneck diagnosis but does not automatically attribute an observed effect to radio scheduling. A radio-specific claim requires aligned scheduler/resource evidence.

If reservation coverage is absent or expired, Experiment 2 stops rather than booking or repairing infrastructure. An incomplete campaign may resume only when the same accepted deployment identity and scientific design regain valid reservation coverage. A different deployment or design starts a separate campaign.

## Run validity and results

The frozen design retains the treatment matrix, source cohort identity, calibrated load selection, session organization, and statistical settings. Analysis uses that frozen study rather than current checkout defaults.

Receiver readiness, clock evidence, and background-flow validity are explicit run requirements. Failed attempts are retained separately before rerunning so old victim summaries cannot be paired with replacement background traffic. Missing or failed required drift checkpoints block resume for diagnosis.

A replay is valid for a load-dependent contrast only when its background sender satisfies the frozen achieved-rate/accounting rule and covers the required publisher horizon/drain. Invalid treatments are excluded only from contrasts that require them, with source seed, arm, and reason retained.

Campaign output is stored under:

```text
results/experiments/ex2/<campaign-id>/
```

## Optional archival

S3 archival is optional and separate from scientific execution. A completed result directory may be archived explicitly with:

```bash
python -m synthran.archive_cli results/experiments/ex2/<campaign-id> \
  --alias <mc-alias> \
  --bucket <bucket> \
  --prefix <prefix>
```

No object-storage destination is hardcoded into Experiment 2.

## Claim boundary

Experiment 2 can establish a conditional effect of release timing on application delivery under the retained source cohort, accepted deployment, competing-load treatment, and measurement contract. It does not by itself identify the radio scheduler as the cause, validate physical Ambient-IoT harvesting/backscatter behavior, or establish a universal 5G capacity threshold.

Shared project-level experiment principles are summarized in [`../README.md`](../README.md). Study-specific scientific interpretation remains in [`SCIENTIFIC_RATIONALE.md`](SCIENTIFIC_RATIONALE.md).
