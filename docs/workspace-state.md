# Persistent workspace and identity model

SynthRAN separates durable controller identity, workspace configuration, experiment identity, requested state, observed provider/runtime facts, operation records, and measurement evidence. These records have different lifetimes and authority and must not be collapsed into one configuration file.

## Current on-disk model

```text
~/.config/synthran/
└── profiles/
    └── <profile>.toml

<repository>/.synthran/
├── workspace.toml
├── registry.sqlite3
├── active.json                         # present when an active experiment is selected
├── access/
│   ├── slices.json                     # cache only
│   └── r2lab.json                      # cache only when configured
├── experiments/
│   └── sran-YYYYMMDD-NNN/
│       ├── experiment.toml             # durable experiment identity/binding record
│       ├── desired.json                # detailed requested experiment state
│       ├── observed.json               # reconciled observation cache, when collected
│       ├── status.json                 # legacy WorkspaceSession/provider-summary cache when used
│       └── runs/
│           └── run-NNN[-label]/
│               └── run.json            # durable run identity record
├── operations/
│   ├── active-mutation.json            # only while mutation authority is held/recovery required
│   └── op-NNNNNN/
│       ├── operation.json
│       ├── plan.json
│       ├── state.json
│       ├── approval.json               # only when approval exists
│       └── events.jsonl
└── sessions/
    └── events.jsonl                    # created by the operation journal as needed
```

Legacy accepted `.synthran/preparations/`, `.synthran/runs/`, and historical experiment directories may coexist with this persistent model. First-launch adoption preserves those paths rather than migrating or renaming accepted evidence.

## Authority by information type

| Information | Durable/current location | Authority |
|---|---|---|
| Controller identity references | `~/.config/synthran/profiles/<name>.toml` | SynthRAN profile |
| Selected SLICES project and workspace policy | `.synthran/workspace.toml` | workspace configuration |
| Cached project/gateway access | `.synthran/access/*.json` | cache only; live provider verification wins |
| Active SynthRAN experiment pointer | `.synthran/active.json` | local selection only |
| Experiment identity and provider binding | `experiment.toml` | durable experiment record |
| Detailed requested experiment state | `desired.json` | desired-state authority |
| Current reconciled observation snapshot | `observed.json` | observation cache; source/freshness remain authoritative |
| Legacy provider-session summary | `status.json` | compatibility/summary cache only |
| Current reservation/allocation/lease/runtime facts | provider/direct observations | live truth when fresh |
| Operation identity/plan/status/approval/events | `.synthran/operations/<operation-id>/` | operation-control records |
| Run identity | experiment `runs/<run-id>/run.json` | durable run record |
| Legacy/live measurement evidence | existing run/evidence artifact locations | persisted research evidence |
| Counters and lookup index | `.synthran/registry.sqlite3` | atomic allocator/rebuildable index |

A cache never authorizes mutation by itself. Provider-facing policy must use the required fresh facts.

## Controller profile

A profile stores stable controller identity references such as:

```toml
schema = "synthran/profile/v1alpha1"
name = "controller-name"
created_at_utc = "2026-08-17T19:00:00Z"
updated_at_utc = "2026-08-17T19:00:00Z"

[slices]
username = "operator"

[r2lab]
slice = "slice-name"

[r2lab.ssh]
identity = "~/.ssh/id_r2lab"
fingerprint = "SHA256:..."
```

The private key is never copied. The profile stores the identity reference and public-key fingerprint. Profiles live outside the research repository so sharing/moving the workspace does not copy private key material.

## Workspace configuration

`workspace.toml` binds one profile to one SLICES project and stable workspace defaults:

```toml
schema = "synthran/workspace/v1alpha1"
profile = "controller-name"
project = "research-project"
created_at_utc = "2026-08-17T19:00:00Z"

[defaults]
reservation_minutes = 120
placement = "automatic"

[policy]
ownership = "strict"
```

Environment variables may provide defaults at setup/invocation boundaries, but an initialized workspace is the durable identity/configuration authority. Conflicting runtime authority must fail closed rather than silently retargeting the workspace.

## Access records

Slow-changing controller/gateway access can be cached with an explicit refresh boundary. These records accelerate startup but do not grant resource mutation authority.

SLICES access records retain subject/project verification metadata and provider expiry when available. R2Lab gateway evidence is additionally bound to the SSH identity fingerprint that was verified.

An active R2Lab lease is not treated as slow-changing cached mutation authority. It must be verified at the physical-resource boundary.

Provider experiment state is also short-lived enough to require current verification when a live operation depends on it.

## Experiment identity and desired state

Experiment IDs use UTC date plus a daily non-reusable ordinal:

```text
sran-YYYYMMDD-NNN
```

Issuance creates a durable experiment folder/record. The local `experiment.toml` contains identity, profile/project association, coarse network intent/radio mode, label when present, and optional binding to an existing provider experiment.

Detailed current requested state is stored separately in:

```text
desired.json
```

That separation is intentional. `experiment.toml` is the durable issued identity/binding record; `desired.json` is the validated detailed requested state consumed by application policy.

Runtime-assigned values such as PDU addresses, pod names, reservations, allocations, and leases do not become desired state merely because they were observed once.

Provider experiment creation remains an operator action. A stored provider binding names an already-existing provider experiment and does not create one.

## Observed and status caches

The current application reconciliation cache is:

```text
observed.json
```

It stores the best selected observation for each collected dimension, including source, state, timestamp/freshness, ownership, resource ID when available, and bounded facts/detail.

A separate older `WorkspaceSession` helper can persist a compact provider-experiment summary in:

```text
status.json
```

`status.json` is not the `ApplicationController` observed-state model and must not be confused with `observed.json`. Both are local cache/evidence surfaces; neither overrides current provider truth.

Persisting `observed.json` does not promote it above its underlying source authority. The current truth order remains:

```text
provider
> observation
> evidence
> manifest
> cache
```

A previously persisted provider observation becomes stale after its freshness boundary and can no longer authorize mutation.

## Active experiment

`.synthran/active.json` points to the current local SynthRAN experiment. Changing this pointer changes which local desired/observed state the application loads; it does not change the selected SLICES project or mutate the provider experiment.

An initialized workspace with no active experiment is represented as lifecycle `EMPTY` by `ApplicationController.snapshot()`.

The interactive first-launch flow can create/activate a local experiment record and detailed desired state. That action is local only.

## Run identity

Runs are experiment-local and use:

```text
run-NNN
run-NNN-label
```

A run directory is created under:

```text
.synthran/experiments/<experiment-id>/runs/<run-id>/
```

`run.json` is the durable run identity record. A valid issued run directory still consumes its ordinal even if interruption occurs before all records/artifacts are completed.

Historical pre-workspace acceptance/research runs may use older directory locations/names. They remain preserved evidence and are not retroactively renamed into the new ID scheme.

## Operation identity

Operations are workspace-wide and use:

```text
op-NNNNNN
```

Operation directories live directly under `.synthran/operations/`, not inside an experiment directory.

Each normal operation may contain durable identity, immutable plan, mutable state, optional approval, and append-only event records. A valid issued operation directory consumes its ID even if creation is interrupted.

## Registry behavior

`.synthran/registry.sqlite3` provides atomic ID allocation, concurrency control, and lookup. It is not the only copy of issued identity.

Recovery inspects durable filesystem records/directories so counters cannot move backward after SQLite loss. Incomplete but syntactically valid issued directories still consume their ordinals.

Current counters are independent for:

- experiment IDs per UTC date;
- run IDs per experiment;
- operation IDs per workspace.

SQLite connections are explicitly closed after use; WAL mode is an implementation detail of the allocator, not a replacement for durable filesystem provenance.

## First launch and existing evidence

The no-argument interactive terminal discovers the nearest existing SynthRAN/Git project root. In an uninitialized checkout it runs read-only controller verification before persisting local workspace/profile/access state.

An existing `.synthran` directory containing legacy accepted run evidence is adoptable. Initialization does not move, rename, rewrite, or recursively delete those artifacts.

Initialization fails closed when `.synthran` contains ambiguous partial new-format state without `workspace.toml`, such as registry/active/access records, `sran-*` experiment folders, or `op-*` operation folders.

There is currently no top-level scripted `synthran init` command. The persistent initialization UX is the no-argument terminal startup flow.

## Startup and reconciliation

The production interactive shell constructs `ApplicationController`, which resolves durable workspace/profile/active-experiment authority. Status may use persisted `observed.json` for rendering; provider-facing operation policy requires the fresh facts dictated by the relevant policy.

The repository also contains `open_workspace_session()` as a lower-level helper that can refresh cached SLICES/R2Lab access and recheck a bound provider experiment, persisting its compact `status.json` summary. The production terminal shell does not currently use that helper as its primary application startup path.

Neither path treats cached access/observed/status records as permission to mutate remote resources indefinitely. Freshness and ownership are rechecked at the appropriate boundary, and concrete executors must still perform final live provider checks.

## Credential boundary

Profiles/workspaces contain only reviewed references/fingerprints and non-secret control metadata. Never store private key bytes, subscriber credentials, tokens, kubeconfigs, or raw authority payloads in tracked source, public docs, or operation event attributes.
