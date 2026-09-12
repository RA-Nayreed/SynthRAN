# Contributing to SynthRAN

SynthRAN is research software. Contributions should improve the codebase without
weakening deployment safety, provenance, reproducibility, or the separation
between testbed infrastructure and scientific experiments.

## Repository boundaries

Keep changes in the layer that owns them:

- `deploy.sh`, `scenarios/`, and `deployment/` own testbed deployment.
- `synthran/` contains Python support modules used by the platform.
- `Experiment/` contains scientific studies and experiment work in progress.
- `third_party/` and `THIRD_PARTY_NOTICES.md` preserve upstream provenance and
  licensing information.
- `results/` and `.synthran/` are runtime state and evidence, not source code.

The supported public entry point is `./deploy.sh`. Internal Python commands may
exist for development or unfinished experiment work, but should not be promoted
as stable public interfaces unless the repository explicitly adopts them.

## Before changing deployment behavior

Deployment changes can affect shared infrastructure and physical hardware.
Before opening a pull request:

1. Identify whether the change touches SynthRAN-original code or an
   upstream-derived deployment file.
2. Preserve upstream attribution and update provenance records when the origin
   of a retained file changes.
3. Avoid broad cleanup operations, wildcard resource deletion, guessed
   ownership, or radio mutations outside the selected deployment authority.
4. Keep scenario files infrastructure-only. Scientific experiment parameters do
   not belong in generic deployment scenarios.
5. Do not hard-code user-specific credentials, slice identities, SSH keys,
   tokens, host secrets, or temporary reservation identifiers.

## Validation

Run the smallest validation set that actually covers the change. At minimum,
repository-level documentation or control-flow changes should not break basic
syntax checks:

```bash
bash -n deploy.sh
python3 -m compileall -q synthran
```

For scenario or deployment changes, also exercise the relevant configuration
path with `--dry-run` where the required hostname and dependency environment is
available:

```bash
./deploy.sh --config scenarios/<scenario>.yml --dry-run
```

A dry run is not a substitute for physical acceptance when a change affects
R2Lab hardware, radio behavior, modem bring-up, or live network state. Report
exactly what was and was not exercised.

## Pull requests

Prefer focused pull requests with a clear purpose. A useful PR description
includes:

- the problem being solved;
- the boundary being changed;
- why the change is necessary;
- validation performed;
- hardware/testbed acceptance performed, if any;
- known limitations or follow-up work.

Do not describe planned behavior as implemented, implemented behavior as
validated, or one successful run as a general scientific result.

## Research and experiment contributions

The scientific experiment layer is under active construction. Experiment work
should keep the research question, treatments, seeds/configuration, workload
identity, deployment identity, measurements, and produced evidence traceable.

Do not move unfinished experiment commands into the root quick start merely to
make them visible. The root README should document the stable public workflow;
experiment-specific documentation can live beside the study until its interface
is ready.

## Generated artefacts and sensitive material

Do not commit:

- private SSH keys;
- tokens or passwords;
- subscriber secrets that are not intentionally public test values;
- `.r2lab_config` or other machine-specific access files;
- local `.synthran/` authority state;
- large generated run directories unless a research artefact is deliberately
  being versioned and reviewed.

If logs are needed for a bug report, reduce them to the smallest useful bundle
and redact secrets and personal infrastructure identifiers first.

## Licensing and provenance

The root BSD 3-Clause license applies to SynthRAN-original code. Third-party and
upstream-derived material remains subject to the conditions described in
`THIRD_PARTY_NOTICES.md` and the records under `third_party/`.

Do not remove upstream copyright or license notices. If a contribution imports
or adapts external code, include its source revision and licensing status in the
same pull request.
