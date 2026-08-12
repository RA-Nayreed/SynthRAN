# SynthRAN Architecture

## Responsibility boundary

SynthRAN is the experiment-control layer above existing systems:

```text
Operator
  |
  v
SynthRAN CLI and contracts
  |-- dependency lock and detached checkouts
  |-- 5g_ansible adapter ------------------> Open5GS + srsRAN + srsUE
  |-- Contiki adapter ----------------------> Cooja + tunslip6 + tun0
  |-- MQTT configuration ------------------> edge and central Mosquitto
  |-- collector and validator -------------> JSONL + Parquet + report
  `-- run-scoped cleanup and evidence
```

SynthRAN owns the interfaces between these systems. Upstream repositories own their internal deployment, radio, simulation, and broker implementations.

Linux is the only supported SynthRAN host platform. Development, repository hooks, GitHub Actions, and the network controller all use the named Conda environment `synthran`. `environment.yml` is the single complete definition and includes Ansible tooling; `pyproject.toml` remains package metadata. Interactive shells activate the environment once and invoke its tools directly; non-interactive hooks and CI select it explicitly and never fall back to an arbitrary host Python.

## Why complete pinned checkouts are reused

`5g_ansible` behavior is distributed across its inventory variables, playbooks, roles, templates, Helm integration, and shell entry points. Extracting only a few files would silently inherit dependencies on the rest of the tree and make SynthRAN responsible for reconstructing upstream behavior.

A complete detached checkout preserves those relationships. SynthRAN still executes only the Open5GS + srsRAN + RFSIM path and exposes it through a narrow adapter. Contiki-NG follows the same rule: the upstream checkout remains complete while the SynthRAN sensor application stays out of tree.

This is composition, not a Git merge. `.deps/` is local and ignored. No upstream history or source is added to the SynthRAN repository.

## Golden-path data flow

1. Ten deterministic Cooja sensors join an RPL/6LoWPAN network.
2. `tunslip6` exposes the border router through `tun0` at the edge.
3. Sensors publish MQTT telemetry to the edge broker.
4. The edge broker rewrites only the current run topic and binds its bridge connection to the srsUE PDU address on `tun_srsue1`.
5. The srsRAN/Open5GS user plane carries the bridge connection to a core-node broker address that cannot be reached through an alternate Kubernetes Service path.
6. The collector appends valid events to JSONL and derives Parquet deterministically.
7. Route lookup, interface counters, packet capture, broker receipt, and the selected UPF route provide path proof.

## Control boundaries

Dependency synchronization, privacy scanning, schema validation, and offline tests are local repository operations. Network deployment is a separate explicit operation. Experiment execution assumes a valid operator-managed reservation and an already healthy supported network.

The Linux environment definition pins direct package versions and channels but still allows Conda to select platform-specific transitive builds. Reproducibility claims at the environment-artifact level require a reviewed Linux `conda-lock` file in a later foundation hardening step.

`run` must never reserve nodes or deploy the network. Cleanup removes only resources carrying the requested run ID and does not tear down the base deployment.

## Golden-path adapter boundary

The golden-path inventory contract accepts only Open5GS + srsRAN + RFSIM with monitoring disabled. It hashes the inventory and exposes only redacted facts. Live execution narrows this further to separate core/RAN nodes, one srsUE, the default profile, a ready pre-existing cluster, and an absent Open5GS namespace.

The read-only live doctor verifies exact operator-supplied reservation and allocation identifiers, strict SSH identity, selected Kubernetes nodes, Multus/OVS/NAD support, exact subscriber-bootstrap packages, remote tools, and eight digest-addressed Linux AMD64 images. Authority identifiers are stored only as SHA-256 fingerprints. READY evidence is inventory-bound and expires after 15 minutes.

The deployment gate revalidates that evidence before creating `.synthran/runs/<run-id>/`. It creates a detached worktree at the locked `5g_ansible` commit, records the SynthRAN overlay hash, and applies an exact patch that removes upstream host-package installation, kubelet/CoreDNS restart, mutable tool download, WebUI deployment, and multi-slice expansion. The wrapper calls only the reviewed Open5GS and srsRAN roles. It never invokes interactive `deploy.sh` or upstream node boot/setup plays.

The wrapper passes immutable transitive Git commits, uses only the exact locked `kubernetes.core` collection, removes mutable Kustomize image transforms, pins every selected application/helper image by digest, and labels resources with the run ID from creation. Remote Open5GS and srsRAN checkouts live below a unique run-scoped directory and are refused if already present. Only slice one and `uesim01` enter the runtime graph. Output is sanitized before being written; failure leaves a partial manifest and log.

Deployment ends in `deployed-unverified`. A separate read-only verifier discovers exactly one run-owned gNB, srsUE, and slice-one UPF, checks the primary and helper image digests and running state, requires the gNB cell-activation signal, validates `tun_srsue1` and its PDU address/route, and verifies the UPF `ogstun` route. Only that proof changes the manifest to `path-proven`. SLICES acceptance remains an operator action and has not yet been claimed.

## Privacy boundary

Protection is layered:

1. Ignore rules prevent known generated and credential-bearing paths from entering Git status.
2. A local pre-push hook scans every outgoing commit before transport.
3. GitHub push protection can block supported credentials at the server boundary.
4. CI scans the complete checkout with SynthRAN privacy rules and Gitleaks.
5. Generated public text is produced through the deterministic redactor; raw sensitive artifacts remain local.

Checks fail closed. They report a rule and location without copying the detected value into terminal or Actions logs. Automatic source rewriting is intentionally avoided because it can corrupt code and conceal a leaked secret in earlier Git history.
