# Contributing to SynthRAN

SynthRAN is research software. Contributions should improve the codebase without
weakening deployment safety, provenance, reproducibility, or the separation
between testbed infrastructure and scientific experiments.

## Repository boundaries

Keep changes in the layer that owns them:

- `deploy.sh` and `deployment/` own testbed deployment.
- `synthran/model/` and `synthran/ambient_iot/` contain the Ambient-IoT model and its integration.
- `synthran/configs/reference.yml` is the single bundled scientific reference configuration.
- `synthran/` contains the remaining Python support modules used by the platform.
- `Experiment/` contains scientific studies and experiment work in progress.
- `third_party/` preserves upstream provenance and component-specific notices.
- `results/` and `.synthran/` are runtime state and evidence, not source code.

The project is converging on `./deploy.sh` as the supported public workflow. Internal Python commands may exist for development or unfinished experiment work, but should not be promoted as stable user interfaces unless the repository explicitly adopts them.

## Before changing deployment behavior

Deployment changes can affect shared infrastructure and physical hardware. Before opening a pull request:

1. Identify whether the change touches SynthRAN-original code or upstream-derived deployment material.
2. Preserve upstream attribution and update provenance records when the origin of retained code changes.
3. Avoid broad cleanup operations, wildcard resource deletion, guessed ownership, or radio mutations outside the selected deployment authority.
4. Keep infrastructure configuration separate from scientific model and experiment parameters.
5. Do not hard-code user-specific credentials, slice identities, SSH keys, tokens, host secrets, or temporary reservation identifiers.

## Validation

Run the smallest validation set that actually covers the change. At minimum, repository-level documentation or control-flow changes should not break basic syntax checks:

```bash
bash -n deploy.sh
python3 -m compileall -q synthran
```

For deployment changes, also exercise the relevant configuration path with `--dry-run` where the required hostname and dependency environment is available. A caller-supplied deployment file can be tested with:

```bash
./deploy.sh --config path/to/deployment.yml --dry-run
```

A dry run is not a substitute for physical acceptance when a change affects R2Lab hardware, radio behavior, modem bring-up, or live network state. Report exactly what was and was not exercised.

## Pull requests

Prefer focused pull requests with a clear purpose. A useful PR description includes:

- the problem being solved;
- the boundary being changed;
- why the change is necessary;
- validation performed;
- hardware/testbed acceptance performed, if any;
- known limitations or follow-up work.

Do not describe planned behavior as implemented, implemented behavior as validated, or one successful run as a general scientific result.

## Research and experiment contributions

The scientific experiment layer is under active construction. Experiment work should keep the research question, treatments, seeds/configuration, workload identity, deployment identity, measurements, and produced evidence traceable.

Do not move unfinished internal commands into the root quick start merely to make them visible. The root README should document the intended public workflow; experiment-specific material can live beside the study until the integration is ready.

## Generated artefacts and sensitive material

Do not commit:

- private SSH keys;
- tokens or passwords;
- subscriber secrets that are not intentionally public test values;
- `.r2lab_config` or other machine-specific access files;
- local `.synthran/` authority state;
- large generated run directories unless a research artefact is deliberately being versioned and reviewed.

If logs are needed for a bug report, reduce them to the smallest useful bundle and redact secrets and personal infrastructure identifiers first.

## Licensing and provenance

The root project license governs SynthRAN-original material according to its terms. Provenance and component-specific notices for retained upstream material live under `third_party/`.

Do not remove upstream copyright or license notices. If a contribution imports or adapts external code, include its source revision and licensing status in the same pull request.
