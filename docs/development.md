# Development Guide

## Environment

SynthRAN supports Linux for the reviewed development/CI/live-control path. Repository hooks, CI, and the live controller use the named Conda environment `synthran`. `environment.yml` is the complete supported Linux environment definition and includes Ansible tooling. `pyproject.toml` contains package/build metadata and the console entrypoint.

Create the environment:

```sh
conda env create --file environment.yml
```

Reconcile it after a direct dependency update:

```sh
conda env update --file environment.yml --prune
```

Activate the environment once per shell, verify its name, and invoke tools directly:

```sh
conda activate synthran
python -c "import os; assert os.environ.get('CONDA_DEFAULT_ENV') == 'synthran'"
python -m unittest discover -s tests -v
```

Direct package versions are exact. Conda still selects platform-specific transitive builds during solving, so the current environment is not an artifact-level lock. A reviewed platform artifact lock would be required before making that stronger claim.

When adding or changing a direct dependency, keep `environment.yml` and the authoritative direct dependency metadata in `dependencies.lock.yml` synchronized. Do not weaken the dependency-consistency tests to accommodate drift.

## Git hooks

Activate the tracked hook once per clone:

```sh
python -m synthran hooks install --dry-run
python -m synthran hooks install
```

The pre-push hook runs the outgoing-commit privacy scan in `synthran`. It checks explicit Conda variables and `PATH`. Nonstandard Linux installations can set the documented local Conda executable override.

Do not bypass a true privacy/secret finding. Remove the sensitive content from every affected outgoing commit and rotate an exposed credential when applicable.

## Architecture-sensitive test expectations

Offline tests protect both the accepted experiment path and the newer persistent application/terminal control plane.

Important areas include:

- **Workspace identity and reconstruction:** workspace/profile initialization, legacy `.synthran` adoption, non-reusable IDs, registry reconstruction, authority conflicts, and safe rollback.
- **Desired/observed separation:** desired-state validation, source truth ordering, freshness, ownership, lifecycle derivation, and fail-closed reconciliation.
- **Operation control:** immutable plan hashes, approval binding, drift rejection, mutation claims, interruption/recovery semantics, and structured operation events.
- **Resource selection/transactions:** deterministic capability placement, fresh/complete inventory requirements, exact `ResourceDecision` binding, provider ordering, exact rollback scope, and recovery-required behavior on unknown partial failure.
- **Terminal:** strict slash-command parsing, OBSERVE/OPERATE gates, registry-backed completion/help, no-argument launcher behavior, first-launch initialization, EMPTY-workspace experiment creation, router/application integration, and structured event rendering.
- **Research schemas and validity:** research specifications/campaigns/summaries, measurement windows, probes, network samples, load results, artifact digests, and invalid-run classification.
- **RFSIM resilience:** one-time reconciled UE/PDU handoff, delayed tunnel readiness, dead-process distinction, repeated zero-sample stall detection, complete retry attempts, and route/ownership restoration.
- **Research load safety:** temporary target-route ownership, owned iperf3 lifecycle, control-connection readiness, load-target achievement, synchronized sampling, path reproof, and cleanup.
- **Campaign analysis:** deterministic blocked randomization, run immutability, paired differences, and bootstrap confidence intervals.

Do not interpret an offline unit test as live SLICES acceptance. Live-accepted claims require run evidence from the real environment.

## Terminal development rule

The current terminal can inspect application state and create immutable workflow plans, but terminal provider/domain executors are not yet connected.

When extending terminal execution:

1. do not call the existing scripted CLI secretly;
2. reuse `ApplicationController`, `OperationController`, current policy/reconciliation, exact target/input binding, and structured events;
3. authorize before execution;
4. perform final provider/domain live checks inside the executor;
5. preserve mutation claims on unknown partial failure;
6. keep provider output out of trusted terminal state unless mapped to the structured event model.

Tests must prove both success and fail-closed boundaries.

## Documentation rule

Documentation is part of the correctness surface. Before completion, compare docs against current code rather than PR intent.

In particular:

- command lists must match `synthran.terminal.commands.COMMANDS`;
- no top-level CLI command may be documented unless `_parser()` actually registers it;
- terminal planning must not be described as live provider execution;
- source truth order must match `SOURCE_PRIORITY`;
- workflow risks/gates must match the registry and application policy;
- live-accepted, offline-tested, and deferred capabilities must remain clearly separated.

## Validation

Before considering a change complete:

```sh
python -m unittest discover -s tests -v
python -m synthran privacy scan --worktree
git diff --check
git status --short
```

When available, also run the repository/Git-history secret scan used by CI.

Inspect the complete diff manually. Tests are intentionally offline and must not require SLICES credentials in CI.
