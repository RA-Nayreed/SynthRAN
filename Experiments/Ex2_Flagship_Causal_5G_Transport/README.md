# Experiment 2 — Causal 5G transport

Experiment 2 tests whether the **timing structure** of an event-identical Ambient-IoT workload changes delivery over the 5G testbed that SynthRAN currently has accepted.

The executable contract is [`experiment.yml`](experiment.yml). The research rationale and inference contract are in [`Ex2_Flagship_Causal_5G_Transport.md`](Ex2_Flagship_Causal_5G_Transport.md).

## Interface

Use only:

```bash
./experiment.sh
```

Choose **Experiment 2**. The phase chain is:

```text
prepare → qualification → calibration → freeze → confirmation → analysis
```

Experiment 2 does not ask for an Experiment-1 path, transport YAML, core/RAN/radio choice, or session number. `deploy.sh` owns infrastructure. When a testbed phase starts, `experiment.sh` discovers `.synthran/active-deployment.json`, displays the actual accepted deployment and current reservation coverage, and asks whether to run on it.

## Design

The primary confirmation campaign uses:

```text
30 frozen knee-common Experiment-1 source seeds
× 4 matched timing arms
× 3 calibrated competing-load levels
= 360 transport replays
```

The timing arms are `native`, `gap_permutation_r1`, `gap_permutation_r2`, and `periodic`. Source seed is the independent experimental unit; the two gap permutations are repeated matched controls, not extra independent samples.

The competing-load levels are selected automatically before confirmation from a prespecified UDP calibration curve as **below**, **near**, and **above** the first median-delivery-ratio crossing of 0.98.

## Roihu → Duckburg source handoff

`prepare` is local, so it can run on Roihu. It discovers the newest complete local Experiment-1 campaign and creates the transferable source cohort at:

```text
results/experiments/ex2-source/<experiment-1-campaign-id>/
```

Copy that directory directly to the same repository-relative path on Duckburg with `rsync`. No tarball is required for working transfer, and Duckburg does not need the complete 210-run Experiment-1 campaign.

## Testbed and reservation behavior

For physical/testbed phases, Experiment 2 consumes the testbed already accepted by `deploy.sh`. It records the actual deployment hash, core, RAN, radio, nodes, UE bindings and slices as provenance rather than prescribing them in advance.

If reservation coverage is missing or expired, Experiment 2 stops; it never books or repairs infrastructure. If the same deployment later has extended reservation coverage, rerunning `experiment.sh` resumes the incomplete campaign from retained run records. If a different deployment hash is active, qualification/full execution starts a separate campaign instead of mixing testbeds.

## Results

Campaigns are stored under:

```text
results/experiments/ex2/<campaign-id>/
```

S3 archival is optional and separate from scientific execution:

```bash
python -m synthran.archive_cli results/experiments/ex2/<campaign-id> \
  --alias <mc-alias> \
  --bucket <bucket> \
  --prefix <prefix>
```

No S3 destination is hardcoded into Experiment 2.
