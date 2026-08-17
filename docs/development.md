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

## Research contract and test expectations

Unit tests are strictly offline and validate safety-critical interfaces across multiple domains:

- **Research schemas:** `tests/test_research_schema.py` and `tests/test_research.py` verify that all research record schemas (`synthran/research-experiment/v1alpha1`, `research-campaign`, `research-summary`, `research-measurement-window`, `research-probe`, `research-network-sample`, `research-load-result`, `research-capacity`) conform to the unified research domain model.
- **RFSIM handoff and sidecar readiness:** `tests/test_rfsim_runtime.py` and `tests/test_research_runtime.py` verify that RFSIM reconciliation occurs once in base execution, handing reconciled UE/PDU state cleanly to the research collector, and that the sidecar restart barrier tracks `restartCount` and pod Ready conditions before proceeding.
- **Temporary route and iperf lifecycle:** `tests/test_research_safety.py` and `tests/test_research_runtime.py` verify that transient target `/32` routes are proven and cleanly removed without residual routing table mutations, and that owned `iperf3` servers maintain run-scoped workspaces and pidfiles with automatic orphan recovery.
- **Synchronized sampling:** `tests/test_research_sampling.py` verifies multi-point interface delta derivations (Ingress, UE `tun_srsue1`, UPF `ogstun`) and ensures incomplete path samples fail research validity.
- **Campaign generation and analysis:** `tests/test_research.py` verifies deterministic blocked randomization, schedule immutability, and paired difference bootstrap estimation.
- **Research validity and failure boundaries:** Tests must verify that runs with failed load injection (`load_target_achieved = false`), missing telemetry, or lost RTT probes are correctly classified as `ready_for_campaign_analysis = false` and `INVALID` while preserving all diagnostic artifacts.
- **RFSIM stall regression testing:** Future test additions should model RFSIM sample stream stalls (where processes are alive and ZMQ TCP connections are established, but sample progression is zero) to ensure robust recovery and fast-fail health probing.

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
