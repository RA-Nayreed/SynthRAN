# Experiment 2 — Causal 5G transport

Experiment 2 tests whether the **timing structure** of an event-identical Ambient-IoT workload changes delivery over the 5G testbed that SynthRAN currently has accepted.

The executable contract is [`experiment.yml`](experiment.yml). The research rationale and inference contract are in [`Ex2_Flagship_Causal_5G_Transport.md`](Ex2_Flagship_Causal_5G_Transport.md).

The detailed hypothesis, literature, interpretation of the initial calibration stop, and scientific limitations are in [`SCIENTIFIC_RATIONALE.md`](SCIENTIFIC_RATIONALE.md).

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

The competing-load levels are selected automatically before confirmation from a prespecified UDP calibration curve. **ABOVE** is the first ascending rate whose median UDP delivery ratio falls below 0.98, **NEAR** is its immediate predecessor, and **BELOW** is the preceding rate.

Design version 2 preserves the original 5–50 Mbps anchors and uses the complete grid:

```text
5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250 Mbps
```

Every repeat must achieve 95–105% of its requested application-payload rate without sender errors. These levels describe a measured UDP loss boundary; they do not identify the first onset of queueing or prove that the radio is the bottleneck. No crossing or an invalid generator measurement stops confirmation and retains the calibration evidence.

## Revising the initial calibration campaign

After updating to design version 2, choose qualification or the full Experiment-2 sequence in `experiment.sh`. A different design contract starts a new campaign even when the accepted deployment is unchanged. The old campaign remains intact; selecting only calibration/confirmation on a legacy campaign is rejected. Prepared source bundles can be reused unchanged.

Inspect `calibration/load-selection.json` for measured sender rates, per-probe validity, medians and the selection status. If the grid remains unbracketed, retain it as a pilot and revise the calibration design explicitly before another campaign. Do not lower the 0.98 threshold or force the highest tested rate into the ABOVE label to make confirmation start.

## Roihu → Duckburg source handoff

`prepare` is local, so it can run on Roihu. It discovers the newest complete local Experiment-1 campaign and creates the transferable source cohort at:

```text
results/experiments/ex2-source/<experiment-1-campaign-id>/
```

Copy that directory directly to the same repository-relative path on Duckburg with `rsync`. No tarball is required for working transfer, and Duckburg does not need the complete 210-run Experiment-1 campaign.

## Testbed, telemetry and reservation behavior

For physical/testbed phases, Experiment 2 consumes the testbed already accepted by `deploy.sh`. It records the actual deployment hash, core, RAN, radio, nodes, UE bindings and slices as provenance rather than prescribing them in advance.

Calibration and confirmation also retain **read-only transport snapshots** from the accepted hosts. The snapshots include UE/interface counters, selected kernel IP/TCP/UDP counters, queue disciplines when exposed, relevant gNB/core process presence, Kubernetes pod identity/readiness/restart counts where exposed, host uptime/load/clock state, and the proved workload/competitor routes to the N6 endpoint. Confirmation records these around each session and reservation pause/resume boundary. The experiment does not restart, repair, power-cycle, or reconfigure those components to obtain telemetry.

This evidence can show infrastructure stability and support bottleneck diagnosis, but it is not automatically proof that an observed effect came from radio scheduling. A radio-specific claim still requires the corresponding scheduler/resource evidence to be available and aligned with the replay interval.

If reservation coverage is missing or expired, Experiment 2 stops; it never books or repairs infrastructure. If the same deployment and scientific design later have extended reservation coverage, rerunning `experiment.sh` resumes the incomplete campaign from retained run records. A different deployment or scientific design starts a separate campaign during qualification/full execution.

## Results

The frozen design retains the full study settings and calibration digest. Analysis validates the exact treatment matrix and uses that frozen study, including contrast-specific background validity, rather than current checkout settings. Clock probes are refreshed for each replay and retained as immutable evidence; the established NTP gate and read-only telemetry policy remain active.

Receiver readiness and successful sender startup are explicit. A replay is accepted only when the competing flow meets its achieved-rate/accounting rules and covers the publisher horizon and drain under the recorded clock bounds. Failed attempts are preserved under `failed-attempts/` before rerunning, so old victim summaries cannot be paired with new background traffic. Missing, interrupted, or failed required drift checkpoints stop resume for diagnosis.

After a calibration setup/probe execution failure or interrupted acquisition, choose qualification/full execution to create a fresh campaign while preserving the failed one. A valid sweep with no crossing, insufficient predecessor levels, or invalid generator/accounting evidence still needs diagnosis and an explicit scientific-design revision; the experiment does not silently retry until a crossing appears. Earlier frozen campaigns without the complete study/calibration provenance must be retained and replaced by a newly qualified campaign.

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
