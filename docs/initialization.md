# Controller initialization contract

SynthRAN initialization establishes durable controller identity and one research workspace without changing provider resources.

The initialization service is deliberately separate from reservation, allocation, deployment, R2Lab power control, provider-experiment creation, and experiment execution.

## Production entrypoint

Persistent initialization is currently reached through the no-argument interactive terminal:

```sh
synthran
```

If no persistent `workspace.toml` exists, the terminal runs the verified initialization flow before constructing the normal application session.

There is currently no top-level scripted `synthran init` command. Do not document one unless the CLI parser actually adds and tests it.

## Inputs

A new controller profile requires:

- profile name;
- SLICES username;
- SLICES project for the workspace;
- optional R2Lab slice plus an exact SSH private-key path;
- stable workspace defaults such as reservation duration and automatic/manual placement.

The private key is never copied. SynthRAN stores only its normalized path reference and public-key SHA-256 fingerprint.

A later workspace can reuse an existing profile by profile name. Stable identity values are loaded from that profile rather than requested again. Reuse does not permit inline identity overrides.

## Verify before persist

Before creating persistent workspace state, initialization:

1. validates profile and project names;
2. verifies that no `workspace.toml` already exists;
3. inspects an existing `.synthran` directory for ambiguous partial new-format workspace state;
4. reads and fingerprints the selected SSH identity when R2Lab is configured;
5. verifies SLICES authentication and current selected project;
6. confirms requested project membership and records provider project expiry when reported;
7. verifies strict public-key authentication to Faraday when R2Lab is configured;
8. checks that the accepted R2Lab identity fingerprint matches the profile request.

These checks are read-only with respect to external resources. They do not create reservations, allocations, leases, provider experiments, deployments, or experiment workloads.

Only after verification succeeds does initialization persist local state:

- a new profile when required;
- `.synthran/workspace.toml` and missing managed directories;
- the verified SLICES access record;
- the R2Lab gateway access record when configured.

If persistence fails, rollback removes only local profile/workspace/access objects created by that attempt. A reused profile and pre-existing research artifacts are preserved.

If local state changes between verification and persistence, initialization fails closed instead of overwriting it.

## Adopting an existing experiment checkout

The persistent workspace may be introduced into a repository that already contains accepted SynthRAN artifacts such as:

```text
.synthran/preparations/
.synthran/runs/
.synthran/experiments/network-*/
.synthran/experiments/iot-*/
.synthran/experiments/pilot-*/
```

Initialization preserves those paths exactly. It does not move, rename, rewrite, index them as new-format experiments, or delete them.

The persistent registry recognizes its reviewed identifier forms (`sran-YYYYMMDD-NNN`, `run-NNN[-label]`, and `op-NNNNNN`), so historical acceptance/research directories can coexist with newer records.

Adoption fails closed when an existing `.synthran` appears to contain incomplete new-format workspace state without `workspace.toml`, for example:

- `registry.sqlite3`;
- `active.json`;
- persistent `access/slices.json` or `access/r2lab.json`;
- an `experiments/sran-YYYYMMDD-NNN/` directory;
- an `operations/op-NNNNNN/` directory.

Those are recovery cases rather than safe first-use adoption cases.

When `.synthran` existed before initialization, rollback never removes it recursively. Only exact local objects created by the failed initialization attempt may be removed.

## Access caches

Initialization can persist SLICES and optional R2Lab gateway access records with verification and refresh boundaries.

These records are caches. They do not become reservation/allocation/lease/runtime mutation authority.

A changed R2Lab identity invalidates identity-bound gateway evidence. Provider experiment, reservation, allocation, lease, and runtime facts remain short-lived state that must be verified when required by current application/provider policy.

## Production startup after initialization

The production interactive shell constructs `ApplicationController`. The controller resolves durable authority through the initialized workspace/profile/active-experiment records and loads desired/observed state as required for snapshots and operation planning.

The production shell does **not** currently use `open_workspace_session()` as its primary startup path.

The repository still contains `open_workspace_session()` as a lower-level workspace helper. That helper can:

- reuse or refresh cached SLICES project access;
- reuse or refresh R2Lab gateway access;
- recheck a bound provider experiment;
- persist its compact provider summary in `status.json`.

That helper remains distinct from the `ApplicationController` observed-state model, which uses `observed.json` for reconciled application observations.

Neither cached access records, `status.json`, nor `observed.json` can authorize provider mutation merely because they exist. Freshness, ownership, application policy, immutable operation approval, and final executor live checks remain required at their respective boundaries.

## Empty workspace experiment setup

After successful initialization, the workspace may have no active local SynthRAN experiment. The terminal can then create and activate a validated local experiment through `ApplicationController.create_experiment()`.

This creates durable experiment identity plus desired state only. It does not create the SLICES provider experiment or mutate provider resources.

A provider-experiment binding may be recorded when an existing provider experiment is known. If no provider binding exists, live-control planning remains fail-closed until one is durably bound and current authority is proven.

## Project-root discovery

First-use terminal initialization chooses the nearest existing SynthRAN/Git project root rather than creating nested workspace state from an arbitrary repository subdirectory.

A generic user home `.synthran` directory is not treated as a project root merely because it exists; the initializer prefers an actual project/workspace boundary.

This keeps long-lived identity, project-local requested state, short-lived provider facts, and historical research evidence separate while allowing compatible existing experiment checkouts to adopt the persistent workspace safely.
