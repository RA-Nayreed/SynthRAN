# Standalone experiment-suite architecture

## Purpose

`experiment.sh` is the single user-facing scientific experiment runner. It is
separate from `deploy.sh` and deliberately consumes, rather than owns, deployed
testbeds.

The boundary is strict:

- `deploy.sh` provisions, repairs, reserves, verifies, and activates testbeds;
- `experiment.sh` plans and executes scientific campaigns;
- a physical experiment may attach to an already accepted deployment, but it
  must not mutate infrastructure in order to make an experiment pass;
- Experiment 1 is local-only and must not inspect or modify active deployment
  state at all.

Scientific studies live under `Experiments/`. Shared experiment control logic
lives in `synthran/experiments.py`. Accepted-testbed runtime mechanics are kept
under `synthran/experiment_runtime/` instead of being exposed as another public
runner.

## User-interface contract

The experiment frontend follows the presentation quality of `deploy.sh`: strict
shell execution, explicit argument validation, hierarchical sections, one
controller lock, a predictable local runtime, and a SynthRAN terminal banner.
The shell stays thin; structured experiment logic belongs in Python and study
manifests.

The public interface remains intentionally small:

```sh
./experiment.sh
./experiment.sh --experiment ex1 --phase qualification
./experiment.sh --experiment ex1 --phase all --dry-run
```

Parallel worker tuning is deliberately **not** a public option.

## Automatic parallel execution

Local scientific work should use available compute aggressively without changing
the experiment itself.

For independent run units, `synthran.experiments.parallel_map` automatically:

1. determines CPU capacity visible through process affinity;
2. respects a cgroup v2 CPU quota when present;
3. uses up to that many process workers, bounded by the number of run units;
4. constrains common numerical-library thread pools to one thread per worker so
   process-level parallelism is not multiplied by nested BLAS/OpenMP pools;
5. returns results in deterministic input order even if workers finish in a
   different order.

Scientific dependencies remain barriers. Qualification must finish before power
calibration; power calibration must finish before population calibration; the
confirmation design must be frozen before confirmation. The runner does not
cross those boundaries merely to increase utilization.

Physical experiments are different: runs sharing a UE/RAN/radio path are not
implicitly concurrent because that traffic would alter the network treatment.
Physical concurrency is allowed only when the experiment design explicitly
requires and isolates it.

## Experiment 1 v2 lifecycle

Experiment 1 is rebuilt as a qualified, calibrated, frozen, then confirmed
campaign:

1. **qualification** — prove sensing, energy, controller, transmission,
   receiver, SIC, event-lineage, and bundle semantics before scientific use;
2. **power calibration** — derive low, knee, and high harvested-power operating
   points from the current implementation rather than inheriting historical
   values;
3. **population calibration** — derive the contention-transition population
   rather than assuming the historical `N*=32` remains authoritative;
4. **freeze** — write an immutable confirmation design containing selected
   operating points, confirmation seeds, treatment definitions, and the
   implementation/dependency fingerprint;
5. **confirmation** — run only the prespecified frozen treatments and refuse to
   overwrite immutable run bundles;
6. **analysis** — calculate the energy, activation, contention, decode, and
   traffic-structure effects from the completed confirmation cohort.

The historical Experiment 1 campaign is preserved as prior evidence. It is not
silently rewritten or treated as the authoritative source of v2 calibration.

## Results and campaign identity

New campaign output will live under a deterministic hierarchy:

```text
results/
└── experiments/
    └── ex1/
        └── <campaign-id>/
            ├── campaign.json
            ├── source-revision.txt
            ├── qualification/
            ├── calibration/
            │   ├── power/
            │   └── population/
            ├── frozen-design.json
            ├── runs/
            └── analysis/
```

Individual run bundles remain immutable. Resume behavior validates completed
bundles, skips valid runs, and refuses corrupted or conflicting output instead
of overwriting it.

## S3 archival contract

Every scientifically successful run is archived independently after local
validation. The validated SLICES destination is:

```text
slices/ilabt.imec.be-project-post5g-beta/SynthRAN/experiments/
```

Experiment 1 uses:

```text
SynthRAN/experiments/ex1/<campaign-id>/...
```

The archive lifecycle is:

```text
run -> validate -> finalize -> checksum manifest -> upload -> remote verify
    -> write _ARCHIVED.json -> continue
```

Scientific success and archival success are separate states. If S3 is
unavailable after a valid stochastic run completes, the local immutable result
is retained and only the upload is retried. The experiment must never be rerun
merely because storage failed.

Credentials are not stored in the repository, experiment manifest, scientific
bundle, or provenance. The runner consumes the operator's preconfigured `mc`
alias. The repository records only the non-secret alias/bucket/prefix contract.

The S3 bucket has been exercised with an upload/list/download/SHA-256 comparison
round trip. Versioned deletion behavior was observed. New experiment code still
uses unique paths and refuses overwrite; bucket versioning is recovery defense,
not the normal immutability mechanism.

## Incremental implementation

Development is staged so scientific and engineering behavior can be reviewed
independently:

1. **Frontend and contract** — `experiment.sh`, Ex1 v2 manifest, result/archive
   contract and terminal UX.
2. **Control-plane cleanup** — plural `Experiments/` tree, consolidated
   `synthran.experiments`, internal physical runtime, automatic parallel policy.
3. **Qualification engine** — retained machine-readable semantic qualification
   artifacts and a hard gate before calibration.
4. **Power calibration** — parallel pilot sweep and explicit low/knee/high
   selection evidence.
5. **Population calibration** — parallel population pilot and explicit
   contention-transition selection.
6. **Freeze** — immutable confirmation design and implementation fingerprint.
7. **Confirmation** — frozen treatment matrix with immutable resume semantics.
8. **Analysis** — prespecified mechanism/traffic metrics and uncertainty.
9. **S3 archival** — per-run verified archival plus campaign-level results.
10. **Accepted-testbed attachment** — generic read-only compatibility checks for
    later physical experiments.

## Analysis interpretation

The source seed is the experimental unit. Sensors, packets, and adjacent time
windows are dependent observations within a run, not additional replicates.
New schema-2 analysis outputs include metric-specific valid/undefined sample
sizes, excluded seed pairs, silent-run indicators, empty-window fractions and
the longest observed interval without a decode. Undefined collision exposure
(no transmissions), Jain fairness (no decodes), Fano (zero mean count), and
activation synchrony (no onsets) remain `null`. Calibration's historical zero
conventions are unchanged. Do not replace undefined values with zero or silently
drop silent runs when describing reliability. Bootstrap intervals are pointwise
percentile intervals over complete seed pairs, not multiplicity-adjusted claims;
a single valid pair has no estimable bootstrap interval.

Measurement uses `[warmup, duration)` at each stage's own timestamp. Count bins
must tile that interval exactly; unequal partial bins are rejected. Analysis
recomputes stage counts and active time from raw evidence instead of trusting
unhashed wrapper metrics. Power correlation excludes the end boundary and
requires aligned sensor sample times.

The frozen burst rule describes **gap-connected components** of decoded events.
Dense continuous traffic can form one component spanning almost the entire
observation. Larger component size is therefore not necessarily greater
burstiness. Use Fano, peaks, empty windows, and temporal traces together; the
single-component indicator exposes this case. Longest observed silence includes
the leading and trailing boundary intervals, which are censored observations,
not complete outage durations.

Existing schema-1 analysis is preserved on resume. Updated code cannot resume
confirmation under an old implementation fingerprint. The analysis phase and retained-campaign inspection share one `analyze.py`
entry point. To write updated diagnostics separately, run:

```bash
python -m Experiments.Ex1_Energy_Correlation_and_Burst_Formation.analyze \
  --campaign /path/to/immutable/ex1/campaign \
  --output /path/to/new/separate/reanalysis
```

The output directory must not exist and must be outside the campaign. This
command checks the frozen design, complete unique condition/seed cohort, run
specifications, and every source bundle checksum. It records both the original
source revision and the analysis revision/source hashes. It never changes the
original analysis, campaign state, source bundles, or Ex2 handoff. Its results
are explicitly **exploratory reanalysis**, not newly prespecified findings.

Outputs are `summary.json`, `run-metrics.json`, and `run-diagnostics.json`.
Diagnostics include per-sensor realized input energy integrated using the
declared hold interpolation, mean input power, decoded counts including zero
service, and generation-cohort outcomes matched by event ID. Energy input is
not capacitor-stored energy, and the always-powered control bypasses gating.
Generation-cohort latency is conditional on decoding before the horizon; pending
and incomplete outcomes are retained rather than automatically classified as
permanent loss. Stage-rate ratios are not generation-cohort delivery probabilities.
Exploratory count-window sensitivity uses 0.1, 0.5, 1, 2 and 5 seconds where they
tile the horizon, and burst-gap sensitivity uses 0.1, 0.25, 0.5, 1 and 2 seconds.
These settings are reported in the output and must not be selected afterward
solely to obtain a favorable result.

For a larger study, version and freeze a new design **before** confirmation:

1. Assess warmup and longer observation horizons using calibration seeds;
   report duration in units of the input correlation time, without treating that
   ratio as an effective independent sample count.
2. Cross population with intermediate energy correlation and correlation time,
   keeping paired seed blocks and documenting which random inputs are shared.
3. Specify primary outcomes and contrasts, uncertainty precision goals and any
   multiplicity policy before choosing the confirmation seed count.
4. Keep per-run, per-sensor and time-window data separate; compare realized
   energy and activity before attributing throughput differences to collisions.
5. Validate transport and physical behavior in a separate experiment. Ex1
   measures model decoding, not end-to-end MQTT/5G delivery.

Do not change the current frozen 60-second duration to retrospectively address
short observation or add new treatments to an already completed cohort.

## Non-goals of Experiment 1

Experiment 1 does not provision R2Lab, reserve SOP nodes, power-cycle N3xx
radios, repair Kubernetes, switch core/RAN implementations, or change physical
UE configuration. Those remain deployment responsibilities.
