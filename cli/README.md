# SynthRAN workbench

This directory contains the interactive terminal surface for SynthRAN.

The current implementation provides:

- one terminal workbench with Access → Configure → Resources → Network → Run → Evidence navigation;
- keyboard navigation with Tab, Shift+Tab, direct numeric shortcuts, and focused controls;
- an action palette opened with `/`;
- first-use workspace configuration inside the same workbench instead of a separate prompt sequence;
- sanitized discovery of existing controller profiles and private SSH identity references;
- read-only SLICES and optional R2Lab verification before first-use state is persisted;
- local state loaded through the versioned SynthRAN control service;
- cached SLICES and R2Lab access freshness without exposing key paths or fingerprints;
- editable reservation-duration and placement defaults stored atomically in the local workspace;
- durable experiment configuration, lifecycle, observations, next action, and block reasons;
- creation of a new immutable local experiment from the Configure view;
- virtual, physical, and automatic radio selection with compatible experiment intent choices;
- read-only discovery of SLICES experiments in the verified workspace project;
- explicit one-time binding of a selected, reverified SLICES experiment to the active local experiment;
- OBSERVE by default, with OPERATE used only for explicit local or live changes;
- Resources and Network views that review Reserve, Bring up, Verify, Recover, and Tear down against current provider-backed state;
- immutable action records, standard approval for controlled changes, separate destructive approval for teardown, explicit execution, pre-execution cancellation, and recent event rendering;
- exact provider inventory binding for resource-changing plans;
- virtual RFSIM execution for reservation, allocation, guarded resource preparation, network deployment, path verification, partial-allocation recovery, and exact owned teardown;
- completion markers derived from durable state rather than the selected screen;
- bounded startup, response-size, exact capability, protocol, provider-read, live-execution, and cancellation handling;
- `r` to reload local state;
- `q` or Ctrl+C to quit when no live provider action is running.

The terminal styling is intentionally restrained. Neutral text, modest emphasis, thin separators, whitespace, and semantic success/error color carry the hierarchy. Saturated accent colors, decorative terminal gradients, and neon dashboard styling are not used.

## First use

When no persistent workspace exists, the workbench opens Configure immediately. It can reuse an existing controller profile or create a new profile with a SLICES username and optional R2Lab slice plus SSH identity. SSH discovery reads only enough of files directly below `~/.ssh` to identify private-key files; the workbench receives normalized identity references, not key contents or fingerprints.

Initialization verifies SLICES project access and, when configured, the R2Lab SSH gateway before writing the profile, workspace, or access evidence. The existing workspace initialization service retains rollback behavior if verification or persistence fails. Reservation duration and placement are chosen in this view and become the workspace defaults.

First-use initialization is a local write and therefore requires OPERATE. Provider verification performed during initialization is read-only; no reservation, allocation, experiment creation, or deployment is performed.

## Configure

Creating an experiment configuration writes only SynthRAN's local workspace. It creates a new active experiment record and preserves older experiments as history. Reservation duration and placement can be changed independently through `Save workspace defaults`; those changes preserve workspace identity, project, profile, and strict ownership policy.

Provider discovery verifies the configured SLICES project before listing experiments. Binding rechecks the selected experiment and then records that exact name locally. A different provider experiment cannot replace an existing binding on the same local experiment.

Provider discovery is available in OBSERVE because it is read-only. First-use initialization, workspace-default updates, experiment creation, and provider binding require an explicit switch to OPERATE. Reloading, navigating away from Configure, or completing a local write returns the workbench to OBSERVE.

## Resources and Network

Resources and Network share the same state-sensitive action surface. Use ←/→ to choose Reserve, Bring up, Verify, Recover, or Tear down, then Enter to refresh provider state and review what the current state permits.

Review is read-only. It shows the current action, safety class, rationale, exact resource targets, and anything still required before an immutable action record can be created.

`p` prepares the selected action. Resource-changing plans require fresh provider inventory and bind the exact resource decision into the immutable plan. Verify is read-only and does not require approval. Controlled changes require standard approval with `a`. Tear down requires separate destructive approval with `d`.

Execution is deliberately separate from approval. Press `e` only after the operation is prepared and, when required, approved. Mutating execution requires OPERATE. The workbench rechecks current controller authority, provider state, resource ownership, and plan-bound inputs immediately before mutation.

Bring up advances only the single reconciliation action currently required. Allocation, resource preparation, and network deployment therefore remain separate approved actions rather than one hidden multi-step mutation. Preparation is prevented from creating a replacement reservation or allocation if either disappears after approval.

Recover currently handles an incomplete SynthRAN-owned allocation. Other recovery conditions remain blocked until a dedicated exact recovery executor exists.

Tear down removes only exact run-owned network state and the SynthRAN-owned allocation. It preserves the current reservation. `x` can cancel a prepared or approved action before live execution starts. Running provider work cannot currently be interrupted from the workbench because safe executor-specific cancellation is not yet connected.

The workbench displays durable operation events including approval, authorization, progress, failure, interruption, completion, and recovery requirements. Raw provider output is not copied into the interface.

The control protocol is version 6. Its handshake declares provider mutation only through the explicit `operation.execute` method. The client requires the exact expected method set and fails closed if extra capabilities are advertised. Earlier contract versions remain frozen in `contracts/`.

Live execution in this surface currently supports only the accepted virtual RFSIM path. Physical R2Lab execution, research runs, data collection, and evidence workflows remain outside this executor for now.

The npm package is marked `private` in `package.json` to prevent accidental publication while the interface is not yet released.

## Local preview

Run from the SynthRAN repository or any directory inside an initialized workspace:

```bash
cd cli
npm install
npm run typecheck
npm run build
npm test
npm start
```

Before a workspace exists, Configure supports:

- ↑/↓ to move focus;
- typing on profile, project, username, and R2Lab-slice rows when those rows are editable;
- ←/→ to choose an existing profile or a new profile, enable R2Lab, select a discovered SSH identity, adjust reservation duration, and change placement;
- `m` to switch between OBSERVE and OPERATE outside text-entry rows;
- Enter on `Initialize` in OPERATE to verify access and persist the local workspace.

After initialization, Configure supports:

- ↑/↓ to move focus;
- ←/→ to change intent, radio, reservation duration, placement, or a loaded provider selection;
- `m` to switch between OBSERVE and OPERATE;
- Enter on `Save workspace defaults` in OPERATE to persist reservation and placement choices;
- Enter on `Create configuration` in OPERATE to persist a new local experiment;
- Enter on `Provider experiment` in OBSERVE or OPERATE to load SLICES experiments when no provider is bound;
- ←/→ to select one of the loaded provider experiments;
- Enter on `Bind provider` in OPERATE to reverify and record the selected provider experiment locally.

On Resources or Network:

- ←/→ chooses the action;
- Enter refreshes provider state and reviews the action without mutation;
- `m` switches between OBSERVE and OPERATE;
- `p` creates an immutable action record when all required inputs are available;
- `a` records standard approval for a controlled change;
- `d` records destructive approval for teardown only;
- `e` executes the prepared action when its current state permits execution;
- `x` cancels prepared or approved local action state before provider execution.

Set `SYNTHRAN_PYTHON` when the desired Python executable is not available as `python` in the current environment.
