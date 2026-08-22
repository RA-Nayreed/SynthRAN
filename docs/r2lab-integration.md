# R2Lab integration branch and smoke gate

This document defines the development boundary for adding a physical R2Lab backend without weakening the accepted RFSIM path.

## Branch model

R2Lab development does not land directly on `main` while physical acceptance is incomplete.

```text
main
  |
  +-- r2lab-integration
        |
        +-- r2lab-smoke-gate
        +-- r2lab-*
```

- `main` remains the accepted RFSIM integration truth while physical work is under validation.
- `r2lab-integration` is the temporary integration main for reviewed R2Lab work.
- Each implementation checkpoint is developed on a separate `r2lab-*` feature branch and merged by pull request into `r2lab-integration`.
- The complete R2Lab change reaches `main` only after the accumulated branch passes offline regression checks and live physical acceptance.
- Existing RFSIM behavior remains a regression requirement throughout the work.

The existing smoke-gate pull request was created before the branch-prefix convention changed, so its remote head may retain the older prefix until that PR is completed. New branches, documentation, and plans must use the `r2lab-*` convention without that prefix.

The integration branch is not a second product line. The intended final product supports both `rfsim` and `r2lab` as explicit radio backends.

## Current physical-support boundary

The accepted product path on `main` remains:

```text
Open5GS + srsRAN + srsUE + RFSIM
```

Live R2Lab smoke work has gone further than the original resource-only gate. `r2lab-smoke-002` accepted the SLICES/POS foundation, Open5GS, the N300-backed srsRAN gNB, and gNB-to-AMF N2/SCTP. A managed qfit UE was reachable, but it did not acquire the tested NR cells, so registration, PDU session, user plane, and the full SynthRAN workload remain unaccepted.

The detailed chronology, evidence, discoveries, cleanup decisions, and implementation consequences are recorded in [`docs/r2lab-smoke-002.md`](r2lab-smoke-002.md). The coding sequence and the reasoning that connected each observation to an implementation change are recorded in [`docs/r2lab-smoke-002-development-log.md`](r2lab-smoke-002-development-log.md).

A physical request such as `physical + r2lab + n300` must not be documented as accepted until a real radio/UE path has exercised the complete acceptance ladder and its evidence has passed review.

## Smoke-gate scope

The smoke-gate checkpoint freezes current RFSIM behavior and establishes the exact resource-control boundary around the public R2Lab API:

```text
doctor
  -> plan
  -> prepare
  -> inspect/recover
  -> release
```

The original offline gate covered `doctor -> plan -> prepare -> release`. Live smoke work exposed additional provider semantics that now belong in this checkpoint before it is ready to merge.

### Preconditions

The operator must already have:

- working public-key SSH access to `faraday.inria.fr` for the R2Lab slice;
- an active R2Lab lease that covers the smoke-test window;
- no unresolved SynthRAN R2Lab resource claim in the workspace;
- a reviewed radio and UE selection.

The historical first smoke target was `n300 + qhat01`. The first managed UE used for deeper physical diagnosis was `qfit07`; qfit resources are now first-class reviewed selections rather than an incidental operator workaround.

SynthRAN does not store an R2Lab password and the smoke gate does not book a lease automatically. Live R2Lab SSH uses the identity stored in the default SynthRAN profile when available. An operator may explicitly override that identity for the current process with `SYNTHRAN_R2LAB_IDENTITY`. The private identity path is used only in the live SSH argv and is not written to plans, manifests, logs, or public summaries.

### Operator smoke sequence

Set the R2Lab slice without committing it to repository files:

```bash
export SYNTHRAN_R2LAB_SLICE=YOUR_R2LAB_SLICE
export R2LAB_SMOKE_RUN=r2lab-smoke-NNN
```

If no verified R2Lab identity exists in the default SynthRAN profile, set an explicit private-key reference for the shell:

```bash
export SYNTHRAN_R2LAB_IDENTITY=~/.ssh/YOUR_R2LAB_PRIVATE_KEY
```

Run the read-only checks first:

```bash
python -m synthran r2lab doctor \
  --radio n300 \
  --ue qfit07

python -m synthran r2lab plan \
  --radio n300 \
  --ue qfit07 \
  --run-id "$R2LAB_SMOKE_RUN"
```

Only continue when the doctor reports `READY` and the rendered plan names exactly the selected radio and UE.

A physical mutation sequence must remain exact-resource only. It must not rely on broad provider cleanup or on the exit code of one hardware mutation as proof of resulting hardware state.

## Smoke acceptance criteria

The checkpoint passes only when all of the following are true:

1. `doctor` proves strict public-key SSH to Faraday and an active lease without mutation.
2. A configured R2Lab identity is bound with `IdentitiesOnly=yes`; its private path never appears in rendered or persisted evidence.
3. `plan` is non-executing, redacts the slice name, reuses the active lease, and never contains a password, `all-off`, or broad R2Lab cleanup.
4. `prepare` rechecks the active lease before every physical mutation.
5. `prepare` powers only the selected radio and selected UE.
6. The selected UE becomes management-reachable.
7. The run manifest holds the exact local resource claim while physical state remains active or unresolved.
8. PDU-backed radio state is accepted from an exact textual status observation, not from mutation return code alone.
9. Mutation timeout, missing status, or conflicting status preserves the claim and records unknown state.
10. `release` requires the matching run manifest and local claim.
11. `release` acts only on the exact selected UE and radio.
12. Release recovery is stage-aware: uncertainty in one cleanup action never widens cleanup scope.
13. The active claim is removed only after every run-owned physical resource is proven clean.
14. No physical gNB update permits overlapping owners of a single SDR.
15. The physical radio plan preserves carrier-center, SSB, Point-A, bandwidth, SCS, and antenna semantics instead of copying one ARFCN between unlike fields.
16. Physical acceptance records cell acquisition, registration, PDU session, user plane, and workload as distinct ordered stages.
17. The complete existing RFSIM test suite remains green.

## Provider-state rule discovered live

Rhubarbe PDU mutation return codes are not equivalent to resulting hardware state.

During `r2lab-smoke-002`, an exact N300 power-off operation reported the radio as `OFF` while the mutation command returned status `1`. An immediate exact-resource PDU status query again reported `OFF`.

SynthRAN therefore uses this rule:

```text
mutation rc = diagnostic evidence
exact provider status = resulting PDU state evidence
```

This rule is implemented in `synthran/network/r2lab_power.py` and `synthran/network/r2lab_operations.py`. The public R2Lab resource controller now consumes the verified transition result in both `prepare` and `release` rather than equating a non-zero mutation return code with a failed hardware transition.

## Timeout and claim rule discovered live

A transport timeout can happen after the provider has already acted. The controller therefore performs the exact post-mutation state query even when the mutation transport fails. If the exact status query proves the requested state, that state is accepted while the transport failure remains diagnostic evidence. If the status is missing, contradictory, or unavailable, the selected resource remains unknown.

The implementation now follows these rules:

- unknown provider state keeps the run claim;
- a release with an unresolved UE can still attempt exact radio cleanup after a fresh authority check;
- one unresolved resource never causes a global cleanup action;
- the workspace claim is removed only when both selected physical resources are proven off;
- sanitized cleanup evidence is persisted in the run manifest.

## qfit rule discovered live

`qfit07` was the first managed UE that reached the deeper physical diagnostic stage. qfit power control is not modeled as a qhat PDU operation. The controller uses the exact qfit helper for the selected UE and then independently verifies the corresponding R2Lab reboot-node state (`rebootNN:on|off`). Mutation timeout again does not suppress the exact provider-state query.

The qfit parser and verified operation live in `synthran/network/r2lab_qfit.py` and `synthran/network/r2lab_qfit_operations.py`.

## Failure rules

Fail closed on any uncertainty.

- No active lease: stop before mutation.
- Faraday transport failure: do not infer provider state from missing output.
- Existing workspace claim: do not start another R2Lab resource operation.
- PDU or qfit mutation timeout: query exact current state; retain the claim if unresolved.
- Status without an exact selected-resource observation: treat state as unknown.
- Conflicting status observations: stop and retain the claim.
- UE reachability failure after power actions: retain evidence; do not use broad cleanup.
- Release failure: retain the claim until all selected physical resources are proven clean.
- Physical gNB configuration failure: leave the exact gNB Deployment stopped.
- More than one matching physical gNB pod: request exact scale-to-zero recovery and do not report startup success.

Global power-off is forbidden in SynthRAN-controlled cleanup. In particular, upstream helpers that execute `all-off` are not an acceptable production cleanup boundary for this integration.

## Physical gNB lifecycle rule discovered live

A single physical N300 cannot safely be treated like a replica-friendly software service. During a live configuration change, an ordinary Kubernetes rolling restart briefly allowed the replacement gNB pod to compete with the terminating pod for the same UHD device.

Physical gNB updates must therefore be non-overlapping:

```text
stop current gNB
  -> prove pod count zero
  -> allow SDR claim release
  -> apply configuration
  -> start exactly one gNB
```

This rule is now executable in `synthran/network/r2lab_gnb_lifecycle.py`. The lifecycle controller scales only the exact `srsran-gnb` Deployment, queries all matching pods as JSON instead of relying on list order, counts terminating pods as still present, calls the configuration step only after zero pods are proven, and requires exactly one Running/ready pod after startup. If startup becomes ambiguous or overlapping owners are observed, it requests an exact scale-to-zero recovery and fails closed.

This controller is intentionally not yet wired to the live Helm adapter. Separating the ownership state machine from profile rendering lets both boundaries be reviewed independently before another RF mutation.

## Radio-configuration rule discovered live

The failed UE scans from `r2lab-smoke-002` are evidence for the exact configurations that were tested, not proof of a broken RF path.

A post-run review of the known R2Lab OAI reference showed that it explicitly distinguishes SSB placement, Point A, carrier bandwidth, and antenna count. The live srsRAN experiment did not reproduce all of those semantics.

`r2lab_radio_profile.py` now carries that distinction further than the initial semantic tag. For the reviewed reference grid it derives the resource-grid carrier center from Point A, preserves the expected SSB separately, maps the 162-PRB/30-kHz reference to a nominal 60 MHz carrier, and requires the reviewed 2x2 antenna counts. The resulting helper produces an explicitly `offline-reference-aligned-candidate` intent. It still does **not** claim that this candidate has passed live RF acceptance.

The important relationship encoded for offline review is:

```text
Point A ARFCN 620040
  + half of the 162 PRB x 12 subcarriers x 30 kHz grid
  -> carrier-center ARFCN 621984

expected SSB remains independently represented as ARFCN 621312
```

This prevents the exact smoke-002 mistake where the SSB value was reused as the carrier-center value.

## Separate physical deployment boundary

The existing `synthran.fiveg_ansible` adapter remains deliberately RFSIM-only. Physical support is not implemented by changing its `SUPPORTED_RADIO` constant.

`synthran/network/r2lab_physical_deployment.py` now provides a separate non-executing physical deployment plan. For the current checkpoint it fails closed to the reviewed `sopnode-f2` core, `sopnode-f3` RAN, and `n300` radio topology. The plan requires the reference-aligned radio intent, keeps TX/RX gains within the reviewed checkpoint range, requires `Recreate`/singleton gNB ownership, and explicitly leaves the srsUE-specific CORESET/PRACH overrides unset.

The plan is still `offline-plan-only`. The remaining adapter work is to map this reviewed canonical plan into the pinned physical Helm/chart inputs and verify the rendered configuration before execution.

## Ordered physical acceptance state

`synthran/network/r2lab_acceptance.py` now models physical acceptance as a monotonic sequence rather than a single success flag:

```text
resource authority
  -> SLICES foundation
  -> Kubernetes
  -> Open5GS
  -> gNB/N2
  -> UE management
  -> cell acquisition
  -> registration
  -> PDU session
  -> user plane
  -> workload
```

Stages cannot be skipped. A failed stage blocks later stages, and unreached stages remain explicitly `not-reached`. This is the software representation of why smoke 002 is a failed physical acceptance even though its lower-layer bring-up succeeded.

## Evidence produced by the smoke gate

A smoke run writes generated evidence under:

```text
.synthran/r2lab/<run-id>/
  manifest.json
  r2lab.log
  evidence/
```

The workspace-level active claim is:

```text
.synthran/r2lab/active.json
```

These files are local execution evidence and must not contain the plain R2Lab slice name, private SSH identity path, subscriber secrets, or other credentials. Generated live state remains untracked.

Tracked documentation records sanitized conclusions and cryptographic hashes of selected local evidence when useful for later review.

## Implementation status after smoke 002

Implemented in the current smoke-gate branch:

- exact PDU text parsing and verified transitions;
- live rc=1/OFF semantics as a regression case;
- timeout-aware post-mutation state resolution;
- fail-closed claim retention and exact stage-aware release;
- qfit selection, mutation, and independent provider-state verification;
- sanitized cleanup assessment in manifests;
- semantic separation of carrier, SSB, and Point-A ARFCNs;
- reference-grid derivation of the offline carrier-center/bandwidth/2x2 candidate;
- a separate fail-closed physical deployment-plan boundary that does not loosen the virtual adapter;
- executable non-overlapping singleton gNB lifecycle with zero-pod and exactly-one-ready proof;
- explicit ordered physical acceptance stages;
- regression coverage for the above while retaining the RFSIM golden-path test.

Still required before physical backend acceptance:

- map the physical deployment plan into the pinned physical srsRAN Helm/chart values and inspect the fully rendered result;
- wire the non-overlapping gNB lifecycle to that exact live physical adapter and strict SLICES SSH boundary;
- add qfit cell-acquisition, registration, PDU-session, and user-plane observations as sanitized runtime evidence;
- connect those observations to the ordered acceptance model and persisted run evidence;
- run another controlled live acceptance attempt only after the offline suite and rendered physical profile are green.

## Merge boundary

The smoke-gate pull request remains targeted at `r2lab-integration`, not `main`, and remains draft.

The resource controller, physical planning boundary, offline radio semantic checks, singleton gNB lifecycle, and ordered acceptance model now encode the main lessons from smoke 002. The PR remains draft while the final physical chart/render/runtime wiring is implemented and reviewed, and the accepted RFSIM path must stay green throughout.
