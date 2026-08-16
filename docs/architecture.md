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
  |-- counted ingress ----------------------> UE-side Mosquitto bridge
  |-- central MQTT -------------------------> run-owned core broker
  |-- collector and validator -------------> JSONL + Parquet + report
  `-- run-scoped cleanup and evidence
```

SynthRAN owns the interfaces between these systems. Upstream repositories own their internal deployment, radio, simulation, and broker implementations.

Linux is the supported SynthRAN host platform. Development, repository hooks, GitHub Actions, and the network controller use the named Conda environment `synthran`. `environment.yml` is the complete environment definition and includes Ansible tooling; `pyproject.toml` remains package metadata.

## Why complete pinned checkouts are reused

`5g_ansible` behavior is distributed across its inventory variables, playbooks, roles, templates, Helm integration, and shell entry points. Extracting only a few files would silently inherit dependencies on the rest of the tree and make SynthRAN responsible for reconstructing upstream behavior.

A complete detached checkout preserves those relationships. SynthRAN executes only the Open5GS + srsRAN + RFSIM path through a narrow adapter. Contiki-NG follows the same rule: the upstream checkout remains complete and pinned while the SynthRAN sensor application stays out of tree under `deploy/iot/sensor/`.

This is composition, not a Git merge. `.deps/` is local and ignored. No upstream history or copied source tree is added to the SynthRAN repository.

## Golden-path data flow

1. Ten deterministic Cooja sensors join one RPL/6LoWPAN network.
2. A Cooja border router exposes its serial link through a deterministic Serial Socket.
3. Pinned Contiki-NG `tunslip6` creates `tun0` with `fd00::1/64` on the Linux controller.
4. Sensors publish run-scoped MQTT telemetry toward `fd00::1:1883`.
5. A counted controller-side TCP ingress forwards the MQTT byte stream through a strict SSH/kubectl port-forward to a temporary Mosquitto sidecar in the run-owned srsUE pod.
6. That Mosquitto sidecar shares the srsUE network namespace containing `tun_srsue1`. Its bridge binds to the accepted UE PDU address and targets a literal core-node address.
7. SynthRAN installs a run-specific `/32` route for the central broker through `tun_srsue1` before the bridge connection is accepted.
8. The srsRAN/Open5GS user plane transports the bridge traffic to a run-owned host-network Mosquitto broker on the core node.
9. A central collector subscribes only to the current run topic, validates events, and appends canonical JSONL.
10. PyArrow derives deterministic Parquet from the accepted JSONL record.
11. Route proof, `tun_srsue1` counters, broker receipt, message integrity, the accepted UPF route, and post-cleanup network reproof form the default path evidence.

The controller-side TCP ingress is an integration adapter, not the cellular proof boundary. The cellular bridge starts inside the srsUE network namespace because that is where `tun_srsue1` and the accepted PDU address exist.

## Control boundaries

Dependency synchronization, privacy scanning, schema validation, scenario rendering, and offline tests are local repository operations. Resource preparation and base-network deployment are separate explicit operator operations. Experiment execution assumes a valid operator-managed reservation and an existing `path-proven` supported network.

The Linux environment definition pins direct package versions and channels but still allows Conda to select platform-specific transitive builds. Reproducibility claims at the environment-artifact level require a reviewed Linux artifact lock in a later hardening step.

The experiment run command never reserves nodes, allocates nodes, images nodes, or deploys Open5GS/srsRAN. Its manifest records `reservation_action=none` and `network_deployment_action=none`.

## Accepted network boundary

The golden-path inventory contract accepts only Open5GS + srsRAN + RFSIM with monitoring disabled. Live execution narrows this further to separate core/RAN nodes, one srsUE, the default profile, and one slice.

The SLICES controller boundary requires the Linux Webshell or a documented SSH session to its management host. A read-only doctor verifies the active `synthran` Conda environment, exact locked Python and Ansible versions, POS 2.5.35, SLICES authentication, the selected project, and an existing experiment. SynthRAN never establishes authentication, changes projects, or creates experiments.

The explicit resource-preparation boundary uses reviewed node mappings from the locked upstream tree, rejects conflicting allocations, allocates both nodes together, syntax-checks the isolated patched worktree before POS mutation, and stops before 5G deployment. Provider identifiers are persisted in a mode-`0600` ignored authority file; public manifests and logs contain only fingerprints and sanitized output.

The deployment gate revalidates fresh live evidence before creating `.synthran/runs/<run-id>/`, creates a detached worktree at the locked `5g_ansible` commit, records the SynthRAN overlay hash, and applies a reviewed boundary patch. The wrapper calls only the supported Open5GS and srsRAN roles and never invokes interactive `deploy.sh`.

The wrapper passes immutable transitive Git commits, uses the exact locked Ansible collections, removes mutable image transforms, pins selected application/helper images by digest, validates generated srsUE Helm YAML before deployment, and labels runtime resources with the network run ID. Deployment ends in `deployed-unverified`.

A separate read-only verifier discovers exactly one run-owned gNB, srsUE, and slice-one UPF, checks digest-locked running containers, requires gNB cell activation, validates `tun_srsue1` and its PDU address/route, and verifies the UPF `ogstun` route. Only that proof changes the network manifest to `path-proven`. The accepted network is the prerequisite for the integrated IoT workflow.

## Experiment mutation boundary

The experiment makes only narrow, reversible changes on top of the accepted network:

- create two run-labeled Mosquitto ConfigMaps;
- create one run-labeled central Mosquitto Deployment on the selected core node;
- strategic-patch the existing run-owned srsUE Deployment with one digest-pinned Mosquitto sidecar and one run-owned config volume;
- add one temporary route inside the srsUE pod network namespace;
- run local Cooja, `tunslip6`, strict SSH port-forward and counted ingress processes.

The sidecar patch does not replace the UE container, its image, credentials, or radio configuration. After the route is installed the edge sidecar is restarted so its bridge reconnects against the proven route.

Cleanup is fail-closed and run-scoped. Local process groups are terminated, the sidecar and volume are removed by exact strategic patch, run-labeled Kubernetes objects are deleted by the exact experiment run label, the srsUE rollout is allowed to recover, and the accepted network verifier is run again. A cleanup or network-reproof failure prevents `iot-to-5g-path-proven` status.

## Data boundary

The telemetry contract is `synthran/telemetry/v1alpha1`. The initial topology accepts only `sensor-01` through `sensor-10`. Every event carries the run ID, sensor ID, positive sequence, sensor time, and deterministic integer measurement.

Valid records are appended to JSONL in canonical JSON form. Malformed messages never enter the accepted dataset. Rejection records contain validation reason and topic but intentionally do not copy the raw payload. Parquet is a deterministic derivative of the JSONL record and is not a second source of truth.

The default acceptance window requires all ten sensor identities plus a contiguous, duplicate-free sequence window for each sensor. Missing sensors, gaps, duplicates, malformed data, missing tunnel growth, broker-delivery failure, cleanup failure, or an invalid accepted-network reproof prevents the final ready state.

## Privacy boundary

Protection is layered:

1. Ignore rules prevent dependency trees, generated experiments and credential-bearing paths from entering normal Git status.
2. A local pre-push hook scans every outgoing commit before transport.
3. GitHub push protection can block supported credentials at the server boundary.
4. CI scans the complete checkout with SynthRAN privacy rules and Gitleaks.
5. Generated public text is produced through the deterministic redactor; raw sensitive artifacts remain local.

Checks fail closed. They report a rule and location without copying the detected value into terminal or Actions logs. The default integrated acceptance does not require a packet capture: route proof, interface counters, broker receipt and the accepted UPF path provide evidence without introducing raw-capture privacy risk.
