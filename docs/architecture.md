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
  |-- research instrumentation ------------> iperf3 load + RTT probe + network sampler
  |-- campaign scheduler and analyzer ------> blocked schedules + paired difference analysis
  `-- run-scoped cleanup and evidence
```

SynthRAN owns the interfaces between these systems. Upstream repositories own their internal deployment, radio, simulation, and broker implementations.

Linux is the supported SynthRAN host platform. Development, repository hooks, GitHub Actions, and the network controller use the named Conda environment `synthran`. `environment.yml` is the complete environment definition and includes Ansible tooling; `pyproject.toml` remains package metadata.

## Why complete pinned checkouts are reused

`5g_ansible` behavior is distributed across its inventory variables, playbooks, roles, templates, Helm integration, and shell entry points. Extracting only a few files would silently inherit dependencies on the rest of the tree and make SynthRAN responsible for reconstructing upstream behavior.

A complete detached checkout preserves those relationships. SynthRAN executes only the Open5GS + srsRAN + RFSIM path through a narrow adapter. Contiki-NG follows the same rule: the upstream checkout remains complete and pinned while the SynthRAN sensor application stays out of tree under `deploy/iot/sensor/`.

This is composition, not a Git merge. `.deps/` is local and ignored. No upstream history or copied source tree is added to the SynthRAN repository.

## Golden-path data flow

1. Ten deterministic Cooja sensors join one RPL/6LoWPAN network on Duckburg.
2. A Cooja border router exposes its serial link through a deterministic Serial Socket on Duckburg (`127.0.0.1:60001`).
3. A strict loopback-only reverse SSH tunnel forwards Duckburg port 60001 to the root core node's `127.0.0.1:60001`.
4. Pinned Contiki-NG `tunslip6`, built remotely on the root core node (`inventory.core_node`), creates `tun0` with `fd00::1/64` as root without requiring controller `sudo`.
5. Sensors publish run-scoped MQTT telemetry toward `fd00::1:1883`.
6. A counted TCP ingress running on the core node forwards the MQTT byte stream through a kubectl port-forward to a temporary Mosquitto sidecar in the run-owned srsUE pod.
7. That Mosquitto sidecar shares the srsUE network namespace containing `tun_srsue1`. Its bridge binds to the dynamically discovered live UE PDU address and targets a literal core-node address.
8. SynthRAN installs a run-specific `/32` route for the central broker through `tun_srsue1` before the bridge connection is accepted.
9. The srsRAN/Open5GS user plane transports the bridge traffic to a run-owned host-network Mosquitto broker on the core node.
10. A central collector subscribes only to the current run topic, validates events, and appends canonical JSONL.
11. PyArrow derives deterministic Parquet from the accepted JSONL record.
12. Route proof, `tun_srsue1` counters, broker receipt, message integrity, the accepted UPF route, and post-cleanup network reproof form the default path evidence.

The TCP ingress is an integration adapter, not the cellular proof boundary. The cellular bridge starts inside the srsUE network namespace because that is where `tun_srsue1` and the live PDU address exist. Controller `sudo` is never required: privileged TUN creation is strictly isolated to the root core node.

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
- run local Cooja and strict SSH reverse/forward tunnel processes on Duckburg, and execute `tunslip6`, `tun0`, `CountedTcpIngress`, and remote edge port-forward in an isolated run workspace on the root core node.

Before live mutation, SynthRAN automatically scans `/proc` on the core node to reclaim provably orphaned SynthRAN background processes (`18883:1883`, `18885:18884`, `ingress.py`, `tunslip6`) and verifies reserved ports `60001`, `18883`, and `18885` are free, while foreign or active processes fail closed.

The sidecar patch does not replace the UE container, its image, credentials, or radio configuration. After the route is installed the edge sidecar is restarted so its bridge reconnects against the proven route.

Cleanup is fail-closed and run-scoped. Local and remote process groups are terminated, exact run-scoped remote processes are reaped, run-created/partially-created `tun0` and the isolated run workspace are removed on the core node with verified absence postconditions, host postconditions (ports free, tun0 absent, workspace absent) are verified, the sidecar and volume are removed by exact strategic patch, run-labeled Kubernetes objects are deleted by the exact experiment run label, the srsUE rollout is allowed to recover, RFSIM runtime is reconciled, and the accepted network verifier is run again. A cleanup, host postcondition, or network-reproof failure prevents `iot-to-5g-path-proven` status.

## Controlled research architecture

Controlled research builds upon the deterministic experiment lifecycle by wrapping execution in a fixed measurement window with active load generation and multi-layer instrumentation:

```text
+--------------------------------------------------------------------------------+
| srsUE Pod (open5gs namespace)                                                  |
|  - tun_srsue1 [Live PDU] ---------------------------------------------------+  |
|  - synthran-edge-mqtt (sidecar)                                             |  |
|  - RTT probe: ping -D -I tun_srsue1 <core-target>                           |  |
|  - Background load client: iperf3 -u -b <rate> -B <PDU> <core-target>       |  |
+-----------------------------------------------------------------------------|--+
                                                                              |
                                                              5G RFSIM / UPF Path
                                                                              |
+-----------------------------------------------------------------------------|--+
| Root Core Node                                                              v  |
|  - Ingress: /tmp/synthran/<run-id>/ingress-snapshot.json                       |
|  - Background load server: iperf3 -s -1 -p <port> -I <pidfile> <------------+  |
|  - Central Mosquitto broker                                                    |
|  - Synchronized Sampler: Ingress snapshot + UE tun_srsue1 + UPF ogstun counters|
+--------------------------------------------------------------------------------+
```

### 1. Reconciled PDU state handoff

The base experiment runtime performs RFSIM reconciliation once, discovers the live PDU address, updates scenario inputs, and proves the network path. That exact reconciled state (`ue_pod`, `gnb_pod`, `pdu_address`) is handed directly to the research collector. The research collector reuses the handed-off state and does not execute a second RFSIM reconciliation, preventing redundant gNB/srsUE restarts and subsequent PDU drift.

### 2. Controlled sidecar readiness barrier

When the edge MQTT bridge configuration is rewritten with the discovered live PDU address, the sidecar container must restart cleanly. To eliminate race conditions where pod verification executes during container recreation:
- the wrapper records the container's pre-restart `restartCount`;
- sends `kill -TERM 1` to the sidecar;
- polls until `restartCount` increments;
- verifies the sidecar container reaches `Running=True` and `Ready=True`;
- verifies the overall srsUE pod reaches `Ready=True` within a bounded timeout.

### 3. Temporary target route lifecycle

When background load or RTT probes target a core IP address outside the default subnet, the destination must resolve through `tun_srsue1`:
- the runtime queries `ip route get <target> from <pdu_address>`;
- if already resolving via `dev tun_srsue1`, the route is reused without claiming ownership;
- otherwise, an exact target `/32` route is added (`ip route add <target>/32 dev tun_srsue1`) and ownership is claimed;
- after measurement completes, only the owned route is removed, and prior routing table state is verified restored;
- conflicting or unexpected routes fail closed.

### 4. Owned iperf3 server lifecycle

The core-node `iperf3` server lifecycle is strictly managed:
- allocated an isolated workspace `/tmp/synthran-research/<run-id>/` and pidfile `iperf3-<port>.pid`;
- pre-run recovery reclaims only provably orphaned (PPID 1) matching processes;
- started in single-client mode (`-1`);
- stop explicitly terminates the local SSH wrapper, reaps the remote PID, removes the pidfile, and verifies absence of the workspace directory.

### 5. Synchronized network sampling

The network sampler runs in a dedicated background thread during the measurement window. Each sample captures:
- `IngressSnapshot` (accepted connections, upstream bytes, downstream bytes);
- UE interface statistics (`rx_bytes`, `tx_bytes`, `rx_packets`, `tx_packets`, `rx_dropped`, `tx_dropped` on `tun_srsue1`);
- UPF interface statistics (corresponding counters on `ogstun`).

Because each sampling iteration performs sequential remote SSH queries before sleeping `sample_interval_seconds`, the effective cadence reflects remote query latency plus the sleep interval. Throughput rates are computed from boundary counter deltas divided by actual elapsed time `(last_counter - first_counter) / elapsed_seconds`.

### 6. Research artifact provenance and verification

Controlled research runs persist structured evidence with SHA-256 artifact hashing:
- `experiment-spec.json`: immutable run specification;
- `measurement-window.json`: exact UTC start and end bounds of the active measurement window;
- `probe.jsonl` / `probe.parquet`: sequence-aligned RTT samples, timestamps, and timeout flags;
- `network-samples.jsonl` / `network-samples.parquet`: synchronized interface and ingress counter samples;
- `load.jsonl` / `load.parquet`: background load throughput records;
- `research-summary.json`: consolidated research metrics, validity flags, and SHA-256 digests of all source artifacts (`synthran/research-summary/v1alpha1`).

Base 5G path acceptance (`path_acceptance_ready`) and research analysis readiness (`ready_for_campaign_analysis`) remain distinct validation concepts.

### 7. Base network resilience and process-level RFSIM recovery

The accepted 5G network baseline is decoupled from experiment and research execution lifecycles. If an experiment or research measurement encounters radio-layer stalls or interface drops (such as RFSIM sample stream stalls where processes and TCP connections remain alive but sample progress stops), SynthRAN restores the network via process-level RFSIM reconciliation:
- terminates stale `srsue` and GNU Radio broker processes;
- restarts the run-owned gNB pod while the broker is absent;
- waits for fresh gNB cell activation;
- restarts the GNU Radio broker and `srsue`;
- awaits `tun_srsue1` tunnel creation;
- rediscovers the live PDU address and restores required pod routes;
- verifies the accepted network path (`[PASS] ue-tunnel`, `Result: PATH PROVEN`).

This recovery restores the operational baseline without requiring destructive teardown or full redeployment of Open5GS or Kubernetes.

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
