# Controller initialization contract

SynthRAN initialization establishes durable controller identity and one research workspace without changing provider resources.

The initialization service is deliberately separate from reservation, allocation, deployment, R2Lab power control, and experiment execution.

## Inputs

A new controller profile requires:

- profile name;
- SLICES username;
- SLICES project for the workspace;
- optional R2Lab slice plus an exact SSH private-key path;
- stable workspace defaults such as reservation duration and automatic/manual placement.

The private key is never copied. SynthRAN stores its path reference and public-key SHA256 fingerprint.

A later workspace can reuse an existing profile by profile name. Stable identity values are loaded from that profile rather than requested again. Reuse does not permit inline identity overrides; profile changes use the explicit profile-update path instead.

## Verify before persist

Initialization has two distinct actions.

### Read-only verification

Before creating local state, SynthRAN:

1. validates profile and project names;
2. checks that the target directory has no existing `.synthran` state;
3. reads and fingerprints the selected SSH identity when R2Lab is configured;
4. verifies SLICES authentication;
5. verifies that the currently selected SLICES project matches the requested workspace and confirms membership;
6. records provider project expiry when reported;
7. verifies strict public-key authentication to Faraday when R2Lab is configured;
8. checks that the key fingerprint accepted for R2Lab is the same fingerprint stored by the profile.

No profile, workspace, access cache, reservation, allocation, lease, or remote resource is changed during this action.

### Local persistence

Only after every requested read-only check succeeds, SynthRAN:

1. writes a new profile when the request is creating one;
2. creates `.synthran/workspace.toml` and workspace directories;
3. writes the SLICES access record produced by the successful check;
4. writes the R2Lab gateway access record when configured.

If local persistence fails, initialization removes only the new workspace state and new profile created by that same initialization attempt. A reused profile is never removed by rollback.

If the target workspace or profile appears between verification and persistence, initialization fails closed instead of overwriting it.

## Access records created at initialization

The SLICES access record contains:

- SLICES username;
- project;
- verification time;
- next refresh boundary;
- provider expiry when available.

The R2Lab access record contains:

- slice name;
- Faraday scope;
- verification time;
- next refresh boundary;
- exact SSH public-key fingerprint that was accepted.

These records accelerate later terminal startup but remain caches. They never authorize a resource mutation on their own.

## Later startup

After initialization, normal startup uses `open_workspace_session()`:

- local profile identity is checked first;
- matching fresh SLICES/R2Lab access evidence is reused;
- stale access evidence is refreshed read-only;
- a changed R2Lab SSH identity invalidates cached gateway evidence immediately;
- the active temporary provider experiment is rechecked every time it is resumed;
- live reservation, allocation, lease, and runtime network facts are obtained as needed by the requested operation.

This separates long-lived identity from short-lived provider state while keeping ordinary terminal startup fast.
