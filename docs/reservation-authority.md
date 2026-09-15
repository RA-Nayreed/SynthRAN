# Resource acquisition and POS preparation

SynthRAN is the single authority for external testbed acquisition and POS host preparation. This boundary is deliberately retained even as downstream host, Kubernetes, transport, core and RAN provisioning move toward the pinned 5g-Ansible implementation.

The resolved deployment snapshot must contain explicit, independent policy for provider context, POS calendar acquisition, host preparation and R2Lab acquisition **before any remote mutation occurs**. `synthran.scenario` canonicalizes older `enabled` booleans into these fields when loading a source scenario; the private resolved scenario written by `deploy.sh` is therefore explicit before `synthran.reservation` runs.

## Policy schema

```yaml
deployment:
  nodes:
    core: sopnode-f2
    ran: sopnode-f3
    broker: sopnode-f2

  provider:
    mode: require-existing       # create | require-existing | disabled
    project: post5g-beta
    experiment: synthran
    experiment_duration: 4h     # used only when create must create it

  reservation:
    mode: require-existing       # create | require-existing | disabled
    host_preparation: preserve   # fresh | preserve
    duration_minutes: 120
    image: ubuntu-jammy

  r2lab_reservation:
    mode: require-existing       # book | require-existing | disabled
    duration_minutes: 120
```

These choices are separate on purpose. Reusing a calendar or R2Lab lease never implies permission to reimage a host. Likewise, preserving host state does not weaken exact-resource coverage verification.

`reservation.mode=disabled` requires `host_preparation=preserve`. A destructive fresh preparation without proven POS calendar authority is rejected.

Legacy source scenarios are deterministic rather than interactive:

- POS `enabled: true` becomes `mode: create` and defaults host preparation to `fresh`.
- POS `enabled: false` becomes `mode: disabled` and defaults host preparation to `preserve`.
- R2Lab `enabled: true` becomes `mode: book`; `enabled: false` becomes `disabled`.
- A legacy `reservation.node_pool` is discarded because reservation handling is no longer allowed to substitute nodes.

New or edited scenarios should use the explicit modes directly.

## Exact-resource rule

The `deployment.nodes` role mapping is immutable inside reservation handling. Core, RAN and broker are deduplicated only to form the resource set sent to POS; the role mapping itself is preserved in evidence. There is no automatic substitution, manual replacement loop, `--asap` fallback or hidden calendar replacement.

For `require-existing`, SynthRAN requires exactly one caller-owned active POS calendar event whose node set exactly equals the selected resource set and whose end covers the requested duration. Missing or ambiguous coverage fails closed.

For `create`, exact already-sufficient caller-owned coverage may be reused; otherwise SynthRAN creates a reservation for exactly the selected nodes and verifies the returned event ID against provider-backed calendar evidence. It does not delete unrelated or earlier calendar events to make room for the request.

## Provider context

When provider mode is enabled, the order is:

1. select the requested SLICES project;
2. show the requested experiment;
3. when policy is `create`, create it only if missing;
4. query `post5g experiment prefix` with bounded retry;
5. require a JSON object containing non-empty `subnet`, `lb` and `expiration_time`.

`require-existing` never creates an experiment. Provider command errors remain visible in the failure evidence.

## POS host preparation

`preserve` performs zero allocation, image, boot-parameter, reset or readiness mutation.

`fresh` requires proven calendar authority first. For each exact selected resource the order is:

1. establish a fresh POS allocation owned by this deployment;
2. select the scenario-configured image with the reference staging mechanic;
3. apply the pinned 5g-Ansible SOP/N3xx boot parameters;
4. perform a blocking POS reset;
5. prove SSH readiness with a bounded retry.

If POS reports an already-active allocation, destructive reclaim with `pos allocations free -k` is allowed only in this explicit `fresh` path after exact calendar authority has been proven. The node is immediately reallocated, and image/reset is refused unless fresh allocation ownership is then proven. The configured image is never silently replaced with the image value from the reference repository.

## R2Lab authority

The R2Lab helper retains SynthRAN's credential and evidence semantics. Password material is read from stdin only when a `book` policy actually needs a booking or extension; it is never inserted into shared argv or logs. SSH identity-file and known-hosts support remain explicit.

- `require-existing`: exactly one owned lease must already cover the complete requested interval. No booking, extension or password read is allowed.
- `book`: an exact covering lease is reused; one compatible owned short lease may be extended and then verified by ID; otherwise a new lease may be booked and must be re-queried as exactly one covering lease.
- `disabled`: no provider access occurs.

Multiple covering leases or multiple owned overlapping leases fail closed rather than guessing which lease is authoritative.

## Evidence

Every reservation pass writes `results/<run>/reservation-authority.json` incrementally. It records the selected role/resource identity, explicit policies, provider context, POS calendar ID/coverage and host-preparation evidence. If a later mutation fails, earlier known ownership identifiers remain in that file together with the original error message.

`pos-selection.json` remains as a compatibility/evidence surface for the deployment runner, including POS coverage end used to constrain an R2Lab lease window. It no longer carries remapped node identities because reservation handling cannot remap them.

## Downstream 5g-Ansible boundary

A future pinned 5g-Ansible invocation after this layer must always use:

```yaml
provider:
  manage: false
reservation:
  enabled: false
  r2lab_mode: none
deployment:
  pos_manage_allocation: false
  extra_vars:
    no_boot: true
```

`tools/check_resource_authority_contract.py` proves that the pinned reference still honors this suppression boundary. This prevents a second provider, calendar, R2Lab, allocation or boot engine from becoming active later in the call graph.

## Validation boundary

`tools/check_reservation_authority.py` uses fake command responses and no physical testbed. It covers provider create/existing/retry/failure, exact POS create/require-existing/unavailable/ambiguous coverage, fresh ordering, guarded allocation conflict recovery, preserve zero-mutation behavior, R2Lab reuse/extension/booking failure/ambiguity/disabled behavior, password stdin-only transport, stdin-EOF safety and selected-node immutability.

Passing these checks proves the local contract only. Physical correctness and experiment eligibility belong to the later integrated acceptance issue.
