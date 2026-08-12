# Development Guide

## Environment

SynthRAN supports Linux only. Local development, repository hooks, CI, and the live controller use one named Conda environment, `synthran`. `environment.yml` is the single complete definition and includes Ansible tooling. `pyproject.toml` contains package and build metadata only.

Create the environment:

```sh
conda env create --file environment.yml
```

Reconcile it after a dependency update:

```sh
conda env update --file environment.yml --prune
```

Activate the environment once per shell, verify its name, and then invoke its tools directly:

```sh
conda activate synthran
python -c "import os; assert os.environ.get('CONDA_DEFAULT_ENV') == 'synthran'"
python -m unittest discover -s tests -v
```

Direct package versions are exact. Conda still selects platform-specific transitive builds during a solve, so the current environment is not an artifact-level lock. Reviewed platform-specific `conda-lock` files are required before making that stronger reproducibility claim.

## Git hooks

Activate the tracked hook once per clone:

```sh
python -m synthran hooks install --dry-run
python -m synthran hooks install
```

The pre-push hook runs the outgoing-commit privacy scan in `synthran`. It checks explicit Conda variables and `PATH`. Nonstandard Linux installations can set `SYNTHRAN_CONDA_EXE` locally.

Do not bypass a real finding. Remove it from every affected outgoing commit and rotate an exposed credential.

## Validation

Before considering a change complete:

```sh
python -m unittest discover -s tests -v
python -m synthran privacy scan --worktree
```

Also inspect:

```sh
git status --short
git diff --check
git diff
```

Tests are intentionally offline. SLICES credentials must never be placed in GitHub Actions.
