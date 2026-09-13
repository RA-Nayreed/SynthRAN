# Standalone experiment-suite architecture

## Purpose

`experiment.sh` is the user-facing scientific experiment runner. It is separate
from `deploy.sh` and deliberately consumes, rather than owns, deployed testbeds.

The boundary is strict:

- `deploy.sh` provisions, repairs, reserves, verifies, and activates testbeds.
- `experiment.sh` plans and executes scientific campaigns.
- a future physical experiment may attach to an already accepted deployment,
  but it must not mutate infrastructure in order to make an experiment pass.
- Experiment 1 is local-only and must not inspect or modify active deployment
  state at all.

## User-interface contract

The experiment frontend mirrors the presentation style of `deploy.sh`: strict
shell execution, explicit argument validation, hierarchical section headings,
one controller lock, and a predictable local runtime. The shell remains thin;
structured experiment logic lives in Python and experiment manifests.

The initial public interface is:

```sh
./experiment.sh
./experiment.sh --experiment ex1 --phase qualification
./experiment.sh --experiment ex1 --phase all --dry-run
```

The first development increment implements planning only. Scientific execution
is added phase-by-phase in later commits so every behavior change remains
reviewable and independently testable.

## Experiment 1 v2 lifecycle

Experiment 1 is rebuilt as a qualified, calibrated, frozen, then confirmed
campaign:

1. **qualification** — prove current sensing, energy, controller, transmission,
   receiver, SIC, event-lineage, and bundle semantics before scientific use;
2. **power calibration** — derive low, knee, and high harvested-power operating
   points from the current implementation rather than inheriting the historical
   500/1000/2000 µW choices;
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

A scientific success and an archival success are separate states. If S3 is
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

## Planned incremental implementation

The development PR is intentionally staged. Each stage receives its own commit
and the PR description is updated after the stage is completed.

1. **Frontend and contract** — add `experiment.sh`, the internal manifest
   planner, the Ex1 v2 manifest, and this architecture document.
2. **Qualification engine** — implement retained machine-readable semantic
   qualification artifacts and block calibration until they pass.
3. **Power calibration** — run a pilot sweep and select low/knee/high using
   explicit criteria.
4. **Population calibration** — run the population pilot at the selected knee
   and select the contention-transition population.
5. **Freeze** — generate and validate the immutable confirmation design.
6. **Confirmation execution** — execute the frozen primary treatments with safe
   resume semantics.
7. **Analysis** — produce the prespecified mechanism/traffic metrics and
   uncertainty summaries.
8. **S3 archival** — archive every successful run and campaign-level result,
   verify the remote copy, and support upload-only retry.
9. **Accepted-testbed attachment** — only after Experiment 1 is complete, add
   the generic read-only deployment attachment needed by later physical
   experiments.

## Non-goals of the Experiment 1 implementation

This work does not provision R2Lab, reserve SOP nodes, power-cycle N3xx radios,
repair Kubernetes, switch core/RAN implementations, or change physical UE
configuration. Those remain deployment responsibilities.
