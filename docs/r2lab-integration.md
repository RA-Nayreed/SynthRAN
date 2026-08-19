# R2Lab integration branch and smoke gate

This document defines the development boundary for adding a physical R2Lab backend without weakening the accepted RFSIM path.

## Branch model

R2Lab development does not land directly on `main`.

```text
main
  |
  +-- r2lab-integration
        |
        +-- agent/r2lab-*
```

- `main` remains the accepted RFSIM integration truth while physical work is under validation.
- `r2lab-integration` is the temporary accumulation branch for reviewed R2Lab work.
- Each implementation checkpoint is developed on a separate feature branch and merged by pull request into `r2lab-integration`.
- The complete R2Lab change reaches `main` only after the accumulated branch passes offline regression checks and live physical acceptance.
- Existing RFSIM behavior remains a regression requirement throughout the work.

The integration branch is not a second product line. The intended final product supports both `rfsim` and `r2lab` as explicit radio backends.

## Current physical-support boundary

SynthRAN already models reviewed R2Lab resources and contains a fail-closed scripted resource controller. This is resource-control support, not physical 5G path acceptance.

The current accepted live network path remains:

```text
Open5GS + srsRAN + srsUE + RFSIM
```

A physical request such as `physical + r2lab + n300` must not be documented as accepted until a real radio/UE path has been exercised and its evidence has passed the physical acceptance ladder.

## PR 1 scope: resource smoke gate

The first R2Lab integration checkpoint freezes the current RFSIM behavior and establishes one exact resource-control smoke cycle around the existing public R2Lab API:

```text
doctor
  -> plan
  -> prepare
  -> release
```

This checkpoint deliberately does **not** deploy a physical gNB, attach a UE to Open5GS, move the IoT edge path, or claim physical research acceptance.

### Preconditions

The operator must already have:

- working public-key SSH access to `faraday.inria.fr` for the R2Lab slice;
- an active R2Lab lease that covers the smoke-test window;
- no unresolved SynthRAN R2Lab resource claim in the workspace;
- a reviewed resource pair. The first integration target is `n300 + qhat01`.

SynthRAN does not store an R2Lab password and the smoke gate does not book a lease automatically. Live R2Lab SSH uses the identity stored in the default SynthRAN profile when available. An operator may explicitly override that identity for the current process with `SYNTHRAN_R2LAB_IDENTITY`. The private identity path is used only in the live SSH argv and is not written to plans, manifests, logs, or public summaries.

### Operator smoke sequence

Set the R2Lab slice without committing it to repository files:

```bash
export SYNTHRAN_R2LAB_SLICE=YOUR_R2LAB_SLICE
export R2LAB_SMOKE_RUN=r2lab-smoke-001
```

If no verified R2Lab identity exists in the default SynthRAN profile, set an explicit private-key reference for the shell:

```bash
export SYNTHRAN_R2LAB_IDENTITY=~/.ssh/YOUR_R2LAB_PRIVATE_KEY
```

Run the read-only checks first:

```bash
python -m synthran r2lab doctor \
  --radio n300 \
  --ue qhat01

python -m synthran r2lab plan \
  --radio n300 \
  --ue qhat01 \
  --run-id "$R2LAB_SMOKE_RUN"
```

Only continue when the doctor reports `READY` and the rendered plan names exactly the selected radio and UE.

Then exercise the exact mutation boundary:

```bash
python -m synthran r2lab prepare \
  --radio n300 \
  --ue qhat01 \
  --run-id "$R2LAB_SMOKE_RUN"
```

After inspecting the resulting manifest and confirming the selected UE is management-reachable, release the exact run-owned pair:

```bash
python -m synthran r2lab release \
  --run-id "$R2LAB_SMOKE_RUN"
```

## Smoke acceptance criteria

The checkpoint passes only when all of the following are true:

1. `doctor` proves strict public-key SSH to Faraday and an active lease without mutation.
2. A configured R2Lab identity is bound with `IdentitiesOnly=yes`; its private path never appears in rendered or persisted evidence.
3. `plan` is non-executing, redacts the slice name, reuses the active lease, and never contains a password, `all-off`, or broad R2Lab cleanup.
4. `prepare` rechecks the active lease before every physical mutation.
5. `prepare` powers only the selected radio and selected UE.
6. The selected UE becomes management-reachable.
7. The run manifest reaches `ready` while the exact local resource claim is held.
8. `release` requires the matching run manifest and local claim.
9. `release` powers off only the exact selected UE and radio.
10. A successful release removes the active claim and persists manifest status `released` with `resource_claim` set to `released`.
11. A failed release retains the claim for explicit recovery rather than widening cleanup scope.
12. The complete existing RFSIM test suite remains green.

## Failure rules

Fail closed on any uncertainty.

- No active lease: stop before mutation.
- Faraday transport failure: do not infer provider state from missing output.
- Existing workspace claim: do not start another R2Lab resource operation.
- UE reachability failure after power actions: retain evidence; do not use broad cleanup.
- Release failure: retain the claim and retry only after inspecting exact current state.

Global power-off is forbidden in SynthRAN-controlled cleanup. In particular, upstream helpers that execute `all-off` are not an acceptable production cleanup boundary for this integration.

## Evidence produced by the smoke gate

A smoke run writes under:

```text
.synthran/r2lab/<run-id>/
  manifest.json
  r2lab.log
```

The workspace-level active claim is:

```text
.synthran/r2lab/active.json
```

These files are local execution evidence and must not contain the plain R2Lab slice name or the private SSH identity path. Generated live state remains untracked.

## Next checkpoint

After this gate is accepted, the next PR may make the network deployment adapter backend-aware while preserving the existing RFSIM implementation as its own accepted backend. Physical path acceptance remains deferred until the later deployment, runtime, verification, edge-path, research, and recovery checkpoints are complete.
