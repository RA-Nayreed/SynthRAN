# Persistent workspace and identity model

SynthRAN separates durable identity, research-workspace configuration, temporary provider authority, experiment configuration, observed live state, and measurement evidence. These records have different lifetimes and must not be collapsed into one configuration file.

## Truth by information type

| Information | Durable location | Authority |
|---|---|---|
| Controller identity references | `~/.config/synthran/profiles/<name>.toml` | SynthRAN profile |
| Selected SLICES project and workspace policy | `.synthran/workspace.toml` | workspace configuration |
| Cached project or gateway access | `.synthran/access/*.json` | cache only; live provider wins |
| Requested experiment configuration | `.synthran/experiments/<experiment-id>/experiment.toml` | experiment folder |
| Current reservation, allocation, lease, pods, interfaces, PDU address | provider queries | live provider |
| Last observed experiment state | `.synthran/experiments/<experiment-id>/status.json` | observation cache only |
| Operation history | `.synthran/operations/<operation-id>/` | persisted operation evidence |
| Measurement runs and datasets | experiment `runs/`, `evidence/`, and `datasets/` | persisted research artifacts |
| Counters and lookup index | `.synthran/registry.sqlite3` | atomic allocator and rebuildable index |

A cache is never authority for a mutation. Any resource-changing operation must refresh the provider facts required by its safety policy.

## Controller profile

A profile records information that is expected to remain stable for months or years:

```toml
schema = "synthran/profile/v1alpha1"
name = "controller-name"
created_at_utc = "2026-08-17T19:00:00Z"
updated_at_utc = "2026-08-17T19:00:00Z"

[slices]
username = "operator"

[r2lab]
slice = "slice_name"

[r2lab.ssh]
identity = "~/.ssh/id_r2lab"
fingerprint = "SHA256:..."
```

The profile stores only an SSH identity reference and its public-key fingerprint. Private key bytes are never copied into the profile, workspace, experiment folder, logs, or evidence.

Profiles live outside the research repository so moving or sharing a workspace does not copy personal credentials.

## Workspace configuration

A workspace binds one profile to one SLICES project and stable operator defaults:

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

The project is not part of personal identity. The same profile may be used in another workspace for another project.

## Access freshness

Slow-changing authorization is cached with both a verification timestamp and an explicit refresh boundary. Provider expiry is stored when available.

```json
{
  "schema": "synthran/access/v1alpha1",
  "provider": "slices",
  "subject": "operator",
  "scope": "research-project",
  "verified_at_utc": "2026-08-17T19:00:00Z",
  "refresh_after_utc": "2026-08-18T07:00:00Z",
  "access_until_utc": "2026-10-22T23:59:00Z",
  "detail": "authenticated project membership verified"
}
```

The default refresh interval is 12 hours. The refresh boundary is clipped to provider expiry. Access may still be revoked before a published expiry, so the expiry is never treated as permission to skip periodic verification indefinitely.

R2Lab gateway authentication follows the same 12-hour cache policy. Its cached access record is bound to the SSH public-key fingerprint that was actually verified. A changed identity forces another gateway authentication check even when the old cache has not reached its time refresh boundary. An active R2Lab lease is not cached as mutation authority; it is checked live before every R2Lab resource mutation.

Provider experiments are temporary and are checked when an experiment is resumed or before any operation that depends on them.

## Experiment identity

Experiment IDs use UTC dates and a monotonically increasing daily ordinal:

```text
sran-YYYYMMDD-NNN
```

Examples:

```text
sran-20260817-001
sran-20260817-002
sran-20260818-001
```

Once issued, an ID is consumed. Failed initialization leaves its directory or registry entry as evidence and the ID is never recycled.

The experiment folder is self-describing:

```text
.synthran/experiments/sran-20260818-001/
├── experiment.toml
├── status.json
├── providers/
├── operations/
├── runs/
├── evidence/
└── datasets/
```

`experiment.toml` describes requested configuration. Runtime-assigned values such as pod IPs, service IPs, interface names, UE PDU addresses, reservations, allocations, and leases do not become desired configuration merely because they were observed once.

A SLICES experiment binding may be recorded in `experiment.toml`, but SynthRAN does not create the provider experiment under the current controller contract. The binding refers to an existing operator-created provider experiment and must be reverified when used.

## Run identity

Runs are measurements within one experiment and have an experiment-local ordinal:

```text
run-NNN
run-NNN-label
```

Examples:

```text
run-001-baseline
run-002-load025
run-003-load050
```

Each issued run directory contains a small `run.json` identity record. The directory name itself is sufficient to preserve the consumed ordinal if a failure occurs before `run.json` can be written. Run IDs are therefore never reused after registry recovery.

## Operation identity

Operations are workspace-wide control actions and use a monotonically increasing ordinal:

```text
op-NNNNNN
```

Examples:

```text
op-000041
op-000042
```

Each issued operation directory contains `operation.json`. As with runs, an incomplete but valid operation directory still consumes its ordinal. An operation may be associated with an experiment, but infrastructure inspection and other workspace actions may exist without one.

## Registry behavior

`.synthran/registry.sqlite3` provides atomic ID allocation, concurrency control, and fast lookup. It is not the only copy of research identity or experiment configuration.

The filesystem preserves every issued identifier. Registry recovery scans:

- experiment directory names and `experiment.toml` / `status.json`;
- run directory names and `run.json`;
- operation directory names and `operation.json`.

A valid directory without its record is treated as an interrupted issuance and still consumes the identifier. This prevents experiment, run, or operation ID reuse after SQLite loss.

The registry maintains independent counters for:

- experiment IDs per UTC date;
- run IDs per experiment;
- operation IDs per workspace.

The index rows can be rebuilt where durable records exist, while the highest observed valid directory ordinal restores each non-reuse counter even for interrupted records.

## Startup behavior

A normal terminal startup should perform local checks first:

1. discover the workspace;
2. load the selected profile;
3. validate local profile structure and SSH identity fingerprint;
4. read cached access records;
5. refresh only access records whose refresh boundary has passed or whose identity binding changed;
6. load the active experiment pointer;
7. check the provider experiment because provider experiments are short-lived;
8. reconcile live reservation, allocation, lease, Kubernetes, core, RAN, UE, PDU, and experiment state only when required by the selected operation or status view.

This keeps startup fast without allowing stale authorization to control physical or remote resources.

## Container boundary

Profiles and workspaces remain on the host and are mounted into the disposable SynthRAN runtime. The future launcher may map an identity into the container or forward an SSH agent, but the container image never contains user credentials.

The persistent boundary is therefore:

```text
host
├── ~/.config/synthran/profiles/
└── research-project/.synthran/

container
└── SynthRAN application and pinned toolchain
```

A new container version can be used without losing experiment identity, operation history, or research artifacts.
