# Pinned 5g-Ansible execution contract

SynthRAN's rework uses `RA-Nayreed/5g-Ansible` commit `6c9cb3a90c5cd88e1de3386c7eed76f25aa581d3` as the deployment-behavior reference. This pin is an execution/comparison contract, not a replacement for the historical derivation record in `third_party/sopnode-5g-ansible/SOURCE.json`.

The machine entrypoint is `bin/fiveg`. Before any migration step relies on it, run:

```bash
python3 tools/check_5g_ansible_contract.py --reference /path/to/5g-Ansible
```

The checker is intentionally local and non-hardware. It verifies the exact commit, capabilities, generated inventory assumptions, the `plan` playbook sequence, physical-UE attachment remaining outside `up`, unsupported `host_vars` behavior, qhat23 capability mismatch, named-profile enforcement, and the pinned resume-spec-integrity behavior. It also executes a normalized-spec/inventory/plan matrix covering co-located and split nodes, OAI, srsRAN, UERANSIM, qhat, qfit, and both pinned named profiles (`default` and `scenario1`). A failed check means the reference changed or an assumption is no longer true; re-audit instead of adding a fallback.

## Ownership rule

There must be one provisioning owner. The target architecture is for the pinned 5g-Ansible implementation to own testbed provisioning wherever its contract is sufficient, while SynthRAN owns source resolution, fail-closed translation, scientific identity/evidence, acceptance beyond upstream `ready`, and Experiment behavior. The current local `deployment/` tree remains active until the dependent migration issues prove each replacement; #51 does not introduce a second selectable deployment engine.

## Source-to-reference mapping

| SynthRAN source | Pinned machine field | Contract |
| --- | --- | --- |
| `deployment.core` | `core.type` | Direct. |
| `deployment.ran` | `ran.type` | `srsran` maps to `srsRAN`; `oai` and `ueransim` are unchanged. |
| `deployment.platform` | `platform.type` | Direct. |
| `deployment.ru` | `platform.ru` | Direct for R2Lab; reference derives `rfsim` for RFSIM. |
| `deployment.nodes.core` / `.ran` | `core.node` / `ran.node` | Direct only for supported reference node names. |
| `deployment.ues` | `ues.qhats/qfits` and `deployment.selected_ues` | Two concerns: physical inventory selection versus subscriber/profile selection. Physical attachment is not part of `fiveg up`. |
| `deployment.network_profile` | `profile` | Conditional. The machine accepts a repository-named profile. Effective/custom profile parity must be proven before delegation. |
| `deployment.ansible_vars` | `deployment.extra_vars` | Conditional. Only variables already owned by the pinned reference may pass through; dependent issues must prove their rendered effect. |
| `deployment.r2lab_username` | `r2lab.username` | Direct. |
| `deployment.host_vars` | none | Blocking until reconciled. The pinned machine derives node IP/storage/NIC from `NODE_FACTS`. |
| `R2LAB_IDENTITY_FILE` / `r2lab_ssh.identity_file` | none | Blocking when an explicit identity file is required. |
| SynthRAN `active`/accepted state | reference `ready` | Not equivalent. SynthRAN acceptance requires its own fresh evidence. |

The machine-readable form is `third_party/sopnode-5g-ansible/EXECUTION_REFERENCE.json`. Its `validation_matrix` records the no-hardware combinations that the checker must normalize, render, and plan successfully at the pinned SHA.

## Confirmed gaps and owners

- **Reservation/provider policy — #52.** The reference can own SLICES provider context, POS reservation and R2Lab authority, but SynthRAN must select exactly one owner before migration. External ownership maps to `provider.manage=false`, `reservation.enabled=false`, and `reservation.r2lab_mode=none`.
- **Host facts/bootstrap — #53.** The machine interface reconstructs its supported schema and does not map SynthRAN `host_vars`; its inventory uses fixed `NODE_FACTS` for node IP, storage and NIC.
- **OAI N320 — #55.** SynthRAN's current N320-specific OAI adaptation is not represented by the generic machine contract and must be justified or migrated independently.
- **Physical UE lifecycle — #56.** `deploy_r2lab.yml` powers/prepares selected UEs, but `fiveg up` does not invoke `test-ue-connect.yml`. The pinned `test-ue-connect.yml` also ignores individual connection errors. `qhat23` is present in the default profile but absent from machine `QHATS` capabilities.
- **srsRAN — #60.** Chart/profile/log adaptations need rendered comparison before lifecycle delegation.
- **Core/effective profiles — #61.** The machine validates a named `5g_profile_<name>.yaml`. `deployment.extra_vars` is a possible adapter surface because it has Ansible extra-var precedence, but effective SynthRAN profile parity must be proven from rendered configuration rather than assumed.
- **Acceptance/resume — #57.** Reference `ready` means its provisioning playbooks completed. It is not SynthRAN experiment eligibility. The pinned `up --resume` also rewrites runtime files from the newly supplied spec without first rejecting digest drift, so a future SynthRAN caller must compare normalized identity before resume.

## What later issues may delete

Once the corresponding dependent issue proves reference parity or a minimal required adaptation, remove the parallel SynthRAN deployment implementation for that responsibility. Do not keep the local role and reference role as long-term selectable engines. Do not add fallback chains that silently return to local provisioning.
