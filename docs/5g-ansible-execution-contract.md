# Pinned 5g-Ansible execution contract

SynthRAN's rework uses `RA-Nayreed/5g-Ansible` commit `6c9cb3a90c5cd88e1de3386c7eed76f25aa581d3` as the deployment-behavior reference. This pin is an execution/comparison contract, not a replacement for the historical derivation record in `third_party/sopnode-5g-ansible/SOURCE.json`.

The machine entrypoint is `bin/fiveg`. Before any migration step relies on it, run:

```bash
python3 tools/check_5g_ansible_contract.py --reference /path/to/5g-Ansible
python3 tools/check_resource_authority_contract.py --reference /path/to/5g-Ansible
```

The first checker verifies the exact commit, capabilities, generated inventory assumptions, the `plan` playbook sequence, physical-UE attachment remaining outside `up`, unsupported `host_vars` behavior, qhat23 capability mismatch, named-profile enforcement, the pinned resume-spec-integrity behavior, and the co-located/split validation matrix. The second checker proves that a downstream plan preserves SynthRAN's external resource authority and that the pinned POS role still honors the suppression surfaces used by that boundary. A failed check means the reference changed or an assumption is no longer true; re-audit instead of adding a fallback.

## Ownership rule

There must be one owner for each responsibility. Issue #52 makes the resource boundary authoritative: **SynthRAN alone owns SLICES provider context, POS calendar coverage, POS allocation/image/boot/reset/readiness, and R2Lab lease acquisition/evidence.** The pinned 5g-Ansible implementation remains the preferred downstream provisioning owner wherever later migration issues prove its contract is sufficient.

Every future reference invocation after SynthRAN resource preparation must normalize to all of these values:

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

These controls are complementary. `provider.manage=false` prevents SLICES project/experiment mutation. `reservation.enabled=false` prevents a second POS calendar reservation. `reservation.r2lab_mode=none` prevents reference R2Lab authority. `pos_manage_allocation=false` suppresses the pinned POS role's allocation free/allocate commands, while `no_boot=true` suppresses image, boot-parameter, reset and readiness work in that role. Removing any one of them reopens a dual-owner path and is a contract failure.

SynthRAN's `reservation-authority.json` is evidence of its own resource decisions. It is not a reference `ready` manifest and does not make a deployment experiment-eligible; acceptance remains a separate SynthRAN responsibility.

## Source-to-reference mapping

| SynthRAN source | Pinned machine field | Contract |
| --- | --- | --- |
| `deployment.core` | `core.type` | Direct. |
| `deployment.ran` | `ran.type` | `srsran` maps to `srsRAN`; `oai` and `ueransim` are unchanged. |
| `deployment.platform` | `platform.type` | Direct. |
| `deployment.ru` | `platform.ru` | Direct for R2Lab; reference derives `rfsim` for RFSIM. |
| `deployment.nodes.core` / `.ran` | `core.node` / `ran.node` | Direct only for supported reference node names. Resource acquisition never remaps them. |
| `deployment.ues` | `ues.qhats/qfits` and `deployment.selected_ues` | Two concerns: physical inventory selection versus subscriber/profile selection. Physical attachment is not part of `fiveg up`. |
| `deployment.network_profile` | `profile` | Conditional. The machine accepts a repository-named profile. Effective/custom profile parity must be proven before delegation. |
| `deployment.ansible_vars` | `deployment.extra_vars` | Conditional. Only variables already owned by the pinned reference may pass through; dependent issues must prove their rendered effect. Resource-authority suppression variables are mandatory. |
| `deployment.r2lab_username` | `r2lab.username` | Direct. |
| `deployment.host_vars` | none | Blocking until reconciled. The pinned machine derives node IP/storage/NIC from `NODE_FACTS`. |
| `R2LAB_IDENTITY_FILE` / `r2lab_ssh.identity_file` | none | Blocking when an explicit identity file is required. |
| SynthRAN `active`/accepted state | reference `ready` | Not equivalent. SynthRAN acceptance requires its own fresh evidence. |

The machine-readable form is `third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json`. Its `external_resource_authority` object is the authoritative machine-readable boundary, and its validation matrix records the no-hardware combinations the reference checker must normalize, render and plan successfully at the pinned SHA.

## Resource acquisition retained by SynthRAN

The retained code is intentional integration policy rather than a second downstream deployment engine. It provides semantics that the pinned machine interface does not provide as one contract: exact selected-resource immutability, calendar/allocation ownership separation, explicit create/require-existing/disabled acquisition, explicit fresh/preserve preparation, credential-safe R2Lab mutation over stdin, explicit SSH identity-file support, exact single-lease verification, provider-backed evidence, and fail-closed ambiguous-ownership handling.

For fresh POS preparation SynthRAN keeps the configured image choice, but adopts the pinned reference's supported SOP/N3xx mechanics: prove allocation authority, select the image, apply the reference boot parameters, reset, then prove post-reset SSH readiness. Preserve mode performs none of those mutations.

## Confirmed gaps and owners

- **Host facts/bootstrap — #53.** The machine interface reconstructs its supported schema and does not map SynthRAN `host_vars`; its inventory uses fixed `NODE_FACTS` for node IP, storage and NIC.
- **OAI N320 — #55.** SynthRAN's current N320-specific OAI adaptation is not represented by the generic machine contract and must be justified or migrated independently.
- **Physical UE lifecycle — #56.** `deploy_r2lab.yml` powers/prepares selected UEs, but `fiveg up` does not invoke `test-ue-connect.yml`. The pinned `test-ue-connect.yml` also ignores individual connection errors. `qhat23` is present in the default profile but absent from machine `QHATS` capabilities.
- **srsRAN — #60.** Chart/profile/log adaptations need rendered comparison before lifecycle delegation.
- **Core/effective profiles — #61.** The machine validates a named `5g_profile_<name>.yaml`. `deployment.extra_vars` is a possible adapter surface because it has Ansible extra-var precedence, but effective SynthRAN profile parity must be proven from rendered configuration rather than assumed.
- **Acceptance/resume — #57.** Reference `ready` means its provisioning playbooks completed. It is not SynthRAN experiment eligibility. The pinned `up --resume` also rewrites runtime files from the newly supplied spec without first rejecting digest drift, so a future SynthRAN caller must compare normalized identity before resume.

Reservation/provider/POS ownership is no longer an unresolved migration gap: the owner is SynthRAN, and the reference is downstream-only for this responsibility.

## What later issues may delete

Once the corresponding dependent issue proves reference parity or a minimal required adaptation, remove the parallel SynthRAN deployment implementation for that downstream responsibility. Do not delete `synthran.reservation` as generic duplication: it is the authoritative resource boundary established by #52. Do not keep local and reference downstream roles as long-term selectable engines, and do not add fallback chains that silently return to local provisioning.
