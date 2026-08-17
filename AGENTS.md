# SynthRAN Repository Instructions

## Purpose

SynthRAN is a reproducible experiment orchestrator joining emulated IoT workloads, programmable 5G/Open RAN infrastructure, and intelligence-ready datasets.

The supported golden path is:

```text
10 deterministic Contiki-NG/Cooja MQTT sensors on Duckburg
-> RPL/6LoWPAN border router
-> Cooja Serial Socket (127.0.0.1:60001)
-> loopback-only reverse SSH tunnel (-R 127.0.0.1:60001:127.0.0.1:60001)
-> root tunslip6/tun0 on remote core node (fd00::1/64)
-> counted TCP ingress on remote core node
-> Mosquitto bridge in the srsUE network namespace
-> tun_srsue1
-> srsRAN gNB
-> Open5GS UPF
-> run-owned central Mosquitto broker
-> canonical JSONL
-> deterministic Parquet
```

In controlled research workflows, this path is instrumented across fixed measurement windows with continuous RTT probing, synchronized multi-point network counter sampling (Ingress, UE `tun_srsue1`, UPF `ogstun`), and controlled background UDP load to assess the impact of 5G load on deterministic IoT telemetry.

SynthRAN owns orchestration, contracts, integration adapters, validation, artifact collection, cleanup, and reproducibility reporting. It does not reimplement Open5GS, srsRAN, Contiki-NG, Cooja, Mosquitto, or iperf3.

## Product Vocabulary and CLI

Development milestones are engineering history, not product architecture. Do not encode milestone numbers or temporary planning labels in public commands, module names, class names, schemas, Kubernetes labels, generated filenames, logs, documentation paths, or runtime statuses.

There is exactly one product executable: `synthran`.

SynthRAN provides a dual interaction interface sharing a single application and operation engine:

- **Interactive Terminal Workbench:** Launching `synthran` with zero arguments on an interactive TTY starts the prompt-toolkit terminal shell (`synthran.terminal`) with slash-command vocabulary (`/status`, `/inspect`, `/plan`, `/up`, `/run`, `/stop`, `/collect`, `/logs`, `/down`), dynamic status toolbar, and session mode governance (`OBSERVE` vs `OPERATE`).
- **Scriptable CLI Subcommands:** Passing explicit domain subcommands executes non-interactive, pipeline-friendly CLI operations, for example:

```text
synthran (interactive terminal shell)
synthran init [--project PROJECT] [--profile PROFILE]
synthran network prepare|deploy|verify
synthran experiment plan|run|verify
synthran experiment research plan|run|calibrate|campaign-plan|campaign-run|analyze
synthran deps sync
synthran privacy scan|redact
```

Do not create milestone-specific executables or compatibility aliases for unreleased temporary interfaces. Internal Python modules should describe their responsibility, such as `app`, `operations`, `resources`, `workspace`, `terminal`, `experiment`, `experiment_runtime`, `experiment_resources`, `research`, `research_collector`, `research_instrumentation`, `research_iperf`, `research_sampling`, `iot`, `mqtt_collector`, or `ingress`.

## Shared Application Controller and Interface Invariants

- `main` is the integration truth.
- Scripted CLI subcommands and the interactive terminal workbench MUST share the exact same underlying `ApplicationController` (`synthran.app.controller`) and operation engine (`synthran.operations`).
- The terminal layer must NEVER directly shell out to providers, execute ad-hoc mutations, or bypass application domain services.
- Desired state must NEVER contain discovered runtime values (e.g. allocated node hostnames, dynamically assigned PDU IPs, pod names).
- Desired state (`ExperimentDesiredState`) defines declared research intent; observed state (`ObservedState`) records testbed facts.

## Workspace, Profile, and Identity Architecture

- Global user profiles reside under `~/.config/synthran/profiles/<name>.toml` (mode 0600) with SHA-256 fingerprint verification of referenced private SSH keys.
- Project-local workspace configuration resides under `.synthran/workspace.toml` (mode 0600).
- SQLite registry (`.synthran/registry.sqlite3`) provides atomic sequential ID allocation (`sran-YYYYMMDD-NNN`, `run-NNN`, `op-NNNNNN`) in WAL mode. Filesystem folders (`experiments/`, `operations/`, `runs/`) remain durable source of truth and are rebuildable via `rebuild_from_experiment_folders` without counter reuse.
- Strict source-of-truth precedence: durable workspace state is authoritative. Environment variables provide defaults only when workspace values are unset; explicit conflicting values fail closed.

## Desired State, Observed State, and Truth Hierarchy

- Truth ranking strictly governs reconciliation:
  1. **Live Provider Truth** (fresh live probes);
  2. **Persistent Run Evidence** (run-scoped manifests and receipts);
  3. **Cached Observation Snapshot** (non-authoritative local cache).
- Stale observations cannot authorize mutation. Observations expire after their configured TTL.
- Unknown, foreign, expired, or ambiguous provider ownership strictly fails closed.
- Reconciliation planning (`plan_reconciliation`) emits only the immediate next dependency step (`reserve` -> `allocate` -> `prepare` -> `deploy` -> `verify` -> `up`) and stops at the first unresolved boundary.

## Operation Control Plane, Risk Governance, and Teardown

- All mutating actions require an immutable `OperationPlan` bound to input, desired-state, and observed-state SHA-256 digests.
- `ApprovalGrant` is plan-specific and validates digest integrity.
- Execution requires a single-use `ExecutionPermit`.
- Operations are classified by risk:
  - **R0 (Read-Only):** `/help`, `/status`, `/inspect`, `/logs`, `verify`;
  - **R1 (Controlled Non-Destructive):** `/stop`, `/collect`, `plan`;
  - **R2 (Mutating Non-Destructive):** `/up`, `/run`, `deploy`;
  - **R3 (Destructive Teardown):** `/down`, `clean`.
- Destructive teardown (`/down`) is R3, requires explicit operator confirmation, and must be bound to exact target resources.
- Operation progress uses structured event journals (`OperationEvent`), never UI string parsing.

## Resource Selection and Composite Transactions

- Resource selection (`ResourceSelector`) is deterministic, capability-based, and non-executing. Unsafe or foreign nodes are represented in inventory models but never selectable.
- Composite transactions (`CompositeResourceTransaction`) execute multi-provider acquisitions in topological dependency order and roll back in exact reverse order upon failure.
- Workspace mutation claims are released ONLY upon proven rollback; partial rollback retains the claim for fail-closed operator intervention.

## Current Acceptance State

The repository foundation is accepted.

The supported Open5GS + srsRAN + RFSIM network baseline has completed live SLICES acceptance. A network run is accepted only when its manifest is `path-proven` after proving:

- one run-owned digest-locked gNB is Running and Ready;
- one run-owned digest-locked srsUE is Running and Ready;
- one run-owned digest-locked slice-one UPF is Running and Ready;
- gNB cell activation;
- `tun_srsue1` UP state;
- the expected UE PDU address/network;
- the UE route through `tun_srsue1`;
- the selected UPF route through `ogstun`.

Deployment success alone remains `deployed-unverified`.

The integrated deterministic IoT-to-5G experiment has completed live SLICES acceptance (`iot-acceptance-20260817-06`), persisting `Result: IOT-TO-5G PATH PROVEN` against the accepted base network `network-acceptance-20260817-04`.

Controlled research capabilities have completed live SLICES acceptance against the accepted base network `network-acceptance-20260817-04`:
- Reference capacity calibration: `calibration-20260817-02.json` persisting `67,253,028 bps` (~67.25 Mbps over `tun_srsue1`).
- Controlled baseline measurement: `pilot-20260817-03-baseline` (`READY FOR CAMPAIGN ANALYSIS`, `IOT-TO-5G PATH PROVEN`), proving 360/360 events across 10 sensors (100% delivery, 0 gaps, 0 duplicates), 180 RTT probe samples (0 timeouts), complete transport path sampling, clean instrumentation, and verified base-network cleanup reproof.

## Supported and Deferred Technology

The supported configuration is deliberately narrow:

- core: Open5GS;
- RAN: srsRAN;
- radio: RFSIM;
- UE: one srsUE representing the IoT edge gateway;
- slice: one slice, SST 1, DNN `internet`;
- IoT: exactly ten deterministic Contiki-NG/Cooja sensors;
- edge networking: Cooja Serial Socket plus pinned `tunslip6/tun0`;
- messaging: digest-pinned Mosquitto at the UE edge and core;
- load generation: run-owned UDP iperf3 client (in UE) and server (on core node);
- probing: continuous ICMP RTT probing bound to `tun_srsue1`;
- data: append-only JSONL, deterministic Parquet, and structured research summaries.

The following remain deferred unless an explicit accepted decision promotes them:

- multiple UEs or slices;
- physical radios;
- TCP controlled load mode (research load protocol is UDP only);
- impairment campaigns;
- formal O-RAN A1 or E2 control;
- RIC integration;
- generative models;
- synthetic-telemetry generation;
- automated RAN-policy synthesis.

## Immutable Dependency Boundary

- Reuse `sopnode/5g_ansible` as a complete external pinned checkout. Do not vendor it.
- Reuse Contiki-NG as a complete external pinned checkout. Keep SynthRAN sensor source out of tree under `deploy/iot/`.
- Treat Open5GS Kubernetes and srsRAN Helm repositories as pinned transitive dependencies.
- Pin selected runtime container images by digest.
- Keep dependency trees below ignored `.deps/` storage.
- Never merge an upstream dependency branch into SynthRAN merely to consume it.
- Prefer configuration, exact overlays, reviewed patches, and stable upstream interfaces.
- Preserve third-party license and provenance records.

The accepted network contract must not regress:

- the Open5GS runtime remains compatible with the locked v2.7-style configuration schema;
- remote srsRAN tasks inherit `/opt/synthran-venv/bin/python`, never the controller `ansible_playbook_python`;
- Helm image-pin rewrites preserve source indentation;
- generated ownership helpers render valid Helm/YAML;
- generated srsUE charts pass `helm lint` and `helm template` before installation.

## Environment and Controller Contract

Linux is the supported host platform for CI, hooks, live network control, and live experiment execution.

Use the named Conda environment `synthran`. `environment.yml` is the complete Linux environment definition (including Python 3.12.13 and OpenJDK 21.0.9 for Cooja); `pyproject.toml` is package/build metadata. Never fall back to an arbitrary host Python or `venv`.

The Linux SLICES Webshell, or a documented SSH session to its management host, is the supported live controller. SynthRAN must never perform `slices auth login`, change the active project, or create the SLICES experiment. Those are operator actions.

A controller-probe timeout is not proof of a network failure. Keep controller/context failures distinct from radio/core path proof. Live acceptance guidance may use additional timeout headroom when required.

## Network Lifecycle and Safety

Resource preparation, network deployment, network verification, experiment execution, and network teardown are separate operations.

- Resource preparation is explicit and may reserve, jointly allocate, image, reset, and configure only the reviewed node pair. It stops before 5G deployment.
- Network deployment is explicit and requires fresh matching live-preflight evidence.
- Deployment uses an isolated detached worktree at the locked `5g_ansible` commit.
- The supported runtime graph is exactly one slice and one srsUE.
- Network verification is read-only with respect to provider authority and does not redeploy the network. Verification probes entering the srsUE pod explicitly target container `ue` (`-c ue`).
- Failed or orphaned preparation/deployment run IDs are immutable evidence and are never reused.
- Provider ownership is fail-closed: unknown/foreign owner, expired authority, partial/split allocation, missing reservation, or provider schema drift prevents mutation.

## Integrated Experiment Boundary

The experiment consumes an existing `path-proven` network. It never reserves nodes, allocates nodes, images nodes, or deploys the base network. Its run manifest records:

```text
reservation_action = none
network_deployment_action = none
```

The deterministic scenario is:

- exactly ten sensor motes, IDs 1 through 10;
- one non-sensor RPL border-router mote;
- fixed Cooja seed and topology;
- Java 21 verified before any live Kubernetes/5G mutation;
- `deploy/iot/sensor/project-conf.h` enables Contiki-NG TCP socket support (`#define UIP_CONF_TCP 1`);
- preparation installs host runtime packages (`net-tools` for `ifconfig`);
- pre-run stale runtime recovery automatically reclaims only provably orphaned (PPID 1) processes matching exact SynthRAN signatures (edge port-forward `18883:1883`, central port-forward `18885:18884`, `ingress.py`, `tunslip6`), while active, foreign, or ambiguous ownership remains strictly fail-closed;
- host preflight verifies reserved remote ports `60001`, `18883`, and `18885` are available;
- Cooja Serial Socket listening on Duckburg (127.0.0.1:60001);
- strict loopback-only reverse SSH tunnel forwarding Duckburg port 60001 to core node port 60001;
- root `tunslip6` built and executed on the selected core node (`inventory.core_node`) creating `tun0` at `fd00::1/64` without local controller `sudo`;
- sensors publish run-scoped MQTT telemetry to the `fd00::1` edge address;
- a counted TCP ingress running on the core node forwards the raw MQTT stream to the UE-side broker;
- the real edge Mosquitto bridge runs as a temporary sidecar in the run-owned srsUE pod, sharing the network namespace containing `tun_srsue1`;
- the bridge binds to the dynamically discovered live UE PDU address;
- a central-broker route is explicitly selected through `tun_srsue1`;
- a digest-pinned run-owned central broker runs on the core node;
- the collector subscribes only to the current run topic.

Controller `sudo` is never invoked: privileged TUN network creation is strictly isolated to the root core node. Do not move the cellular bridge to the controller: `tun_srsue1` and its PDU address exist in the srsUE pod network namespace.

For the supported RFSIM path, Kubernetes `Ready` is not sufficient evidence that the UE runtime exists. The pinned srsUE pod is kept alive independently of the GNU Radio broker and `srsue` process, so every experiment-caused srsUE Deployment rollout must reconcile the process-level runtime before network reproof. Reconciliation is limited to resources already owned by the accepted network run and follows this order: stop stale srsUE/broker processes, restart the run-owned gNB while the broker is absent, wait for fresh gNB cell activation, start GNU Radio, start srsUE, wait for `tun_srsue1`, restore routes, then verify the accepted network path. The UE host address inside the accepted PDU network may change during this recovery; discover the live address from `tun_srsue1` and use it for bridge binding and experiment evidence rather than assuming a historical host address. This recovery does not authorize reservation, allocation, imaging, or base-network deployment.

Experiment acceptance requires all of:

- deterministic Cooja/Serial Socket startup;
- `tunslip6/tun0` readiness;
- all ten sensor identities crossing the counted ingress;
- bridge binding to the live dynamically discovered UE PDU address;
- `tun_srsue1` traffic-counter growth during telemetry delivery;
- accepted UPF path remaining valid;
- all ten streams received centrally;
- contiguous sequence windows with no duplicates or gaps;
- valid JSONL;
- deterministic Parquet;
- exact-run remote process cleanup and verified host absence postconditions;
- successful network reproof after cleanup.

Running pods or brokers alone are not acceptance.

## Controlled Research Boundary and Rules

Controlled research builds upon the accepted base network and deterministic experiment lifecycle:

1. **Protocol and Load Validity:** Controlled background load uses UDP only. A loaded run is valid only when `0.90 <= measured_bps / target_bps <= 1.10`. Baseline runs have background load disabled (`load_target_achieved = true`).
2. **Single RFSIM Reconciliation and State Handoff:** The base experiment runtime performs RFSIM reconciliation once, discovers the live PDU address, updates scenario inputs, and proves the network path. That exact reconciled UE/PDU state is handed to the research collector. The research collector must NOT perform a second RFSIM reconciliation.
3. **Controlled Sidecar Readiness Barrier:** When refreshing the edge MQTT bridge configuration, the sidecar restart wrapper reads the current `synthran-edge-mqtt` container `restartCount`, triggers termination, and waits for `restartCount` to increment alongside container Running, container Ready, and pod Ready states within a bounded timeout. Fixed-delay sleep assumptions are prohibited.
4. **Temporary Target Route Lifecycle:** When a probe/load target requires routing through `tun_srsue1`, the runtime inspects the current routing table. If already routed via `tun_srsue1`, it is reused without ownership. Otherwise, an exact target `/32` route is added (`ip route add`) and proven. Upon teardown, only the SynthRAN-created route is removed, and prior routing state is verified restored. Unknown or conflicting routes fail closed. Operators must never be instructed to manually install routing hacks.
5. **Owned iperf3 Server Lifecycle:** The research server runs under an exact run-scoped workspace `/tmp/synthran-research/<run-id>/` with a pidfile (`iperf3-<port>.pid`). Startup automatically reaps only provably orphaned (PPID 1) matching processes. Stop explicitly terminates the process group, reaps the remote process, deletes the pidfile, and removes the workspace with verified absence.
6. **Network Sampling Cadence:** The synchronized network sampler performs sequential remote queries (Ingress snapshot, UE `tun_srsue1` counters, UPF `ogstun` counters) before sleeping `sample_interval_seconds`. Because remote round-trips add to the interval, `sample_interval=1` yields ~51 samples over 180s rather than 180 samples. Throughput is computed from `(last - first) / actual_elapsed_time` and remains accurate. Do not assume 1 Hz sample cadence.
7. **Metrics and Latency Terminology:** Document RTT latency only (mean, median, p95, p99, jitter). Do not invent one-way latency claims without synchronized cross-host clocks.
8. **Campaign Methodology:** The run is the statistical unit. Multi-run campaigns use deterministic blocked randomization across seeds. Offline analysis (`synthran experiment research analyze`) derives bootstrap paired differences from persisted run summaries without live access. Do not claim a campaign is complete without persisted run summaries for all scheduled runs.
9. **Separate Acceptance Concepts:** Base 5G path proof (`path_acceptance_ready`) and research validity (`ready_for_campaign_analysis`) are distinct and must not be conflated.
10. **Preserve Failed Runs and Recover Without Redeployment:** Failed research runs (such as `pilot-20260817-03-load50`) are immutable diagnostic evidence; their run IDs are never reused. An invalid loaded run where the underlying 5G/RFSIM transport failed before load injection must not be cited as congestion evidence. If radio attachment stalls or `tun_srsue1` drops, recover the base network via process-level RFSIM reconciliation rather than tearing down and redeploying the base network.

## Cleanup and Ownership

Every runtime resource carries the experiment run ID where supported.

Cleanup must:

- target only resources proven to belong to the requested run;
- use exact labels or exact known resource names, never broad guessed deletion;
- terminate run-owned local and remote process groups;
- explicitly terminate exact run-scoped remote processes (matching run workspace, UE pod, central deployment, and research iperf3);
- remove run-created/partially-created `tun0` on the core node and verify its absence postcondition;
- remove the run-scoped workspace `/tmp/synthran/<run-id>/` and `/tmp/synthran-research/<run-id>/` on the core node and verify absence postconditions;
- verify host runtime postconditions (reserved ports `60001`, `18883`, `18885`, and load ports free, `tun0` absent, workspace absent);
- remove the temporary UE-side sidecar/config without replacing the base UE container;
- remove run-labeled central broker/config objects;
- wait for the srsUE Deployment to recover and reconcile RFSIM runtime if needed;
- re-run accepted-network verification;
- fail closed if any cleanup step, host postcondition, or base deployment reproof cannot be verified.

Experiment cleanup never tears down the base 5G deployment. A failed experiment retains its run-scoped manifest and available logs, and its run ID is not reused.

## Data Contract

JSONL is the append-only audit record. Parquet is derived and reproducible from accepted JSONL.

Telemetry accepts only `sensor-01` through `sensor-10`. Each event contains schema identifier, experiment run ID, sensor ID, positive sequence number, sensor time, and deterministic integer measurement.

Malformed messages never enter valid JSONL/Parquet. Rejected-event artifacts may record validation reason and topic but do not copy raw untrusted payloads by default.

Sequence acceptance detects missing sensors, gaps, and duplicates rather than relying only on aggregate counts.

## Repository Boundaries

- `contracts/`: versioned scenario, telemetry, readiness, deployment, research, and evidence schemas;
- `synthran/`: CLI, orchestration, adapters, collection, research, validation, evidence, and reporting;
- `deploy/`: SynthRAN-owned Ansible overlays plus out-of-tree IoT source/configuration;
- `docs/`: architecture, operator, experiment, dependency, development, and security documentation;
- `tests/`: offline tests and sanitized fixtures containing no real credentials or private captures.

Do not commit dependency checkouts, generated inventories, run artifacts, firmware build products, packet captures, kubeconfigs, private authority files, or copied upstream repositories.

## Credentials and Privacy

Never commit IMSIs, authentication keys, OPC values, subscriber credentials, SLICES tokens, kubeconfigs, private keys, secret-bearing `.env` files, unsanitized captures/logs, private authority files, dependency worktrees, or generated run directories.

Privacy protection is layered through ignore rules, the local pre-push scanner, GitHub push protection, CI source scanning, and Gitleaks. Never bypass a true secret finding merely to pass CI.

The default experiment acceptance does not require packet capture; route proof, interface counters, broker receipt, message integrity, and accepted UPF proof are preferred.

## User and Agent Responsibilities

The user is the live operator and performs external account administration, reservations/allocations, live resource preparation, network deployment, live experiment execution, and destructive/infrastructure-wide teardown.

Duckburg/Linux is the supported live experiment controller. Live experiments must not be run from the Windows development clone.

An agent may author repository code/config/tests/docs, inspect repository/dependency state read-only, run safe offline validation, prepare non-mutating plans, and analyze operator-provided evidence.

An agent must not reserve SLICES resources, silently deploy the network, run the live experiment, ignore reservation conflicts, commit or push without explicit authorization, or make external infrastructure changes unless the user explicitly changes this rule.

## Decision Journal

`decision.md` is local and intentionally untracked through `.git/info/exclude`, not tracked `.gitignore`.

Record material architecture, dependency, interface, security, workflow, and scope decisions there. Promote durable rules into `AGENTS.md`. Never put credentials, subscriber data, packet contents, or kubeconfigs in the journal.

## Repository Commands

Run from the repository root after activating `synthran`.

- `synthran` (launch interactive terminal workbench)
- `python -m synthran init` (initialize controller profile and project workspace)
- `python -m synthran deps sync --dry-run`
- `python -m synthran deps sync`
- `python -m synthran privacy scan --worktree`
- `python -m synthran privacy scan --history`
- `python -m synthran doctor --offline --inventory PATH`
- `python -m synthran slices doctor --slices-project PROJECT --slices-experiment EXPERIMENT`
- `python -m synthran network prepare --dry-run --owner OWNER --run-id RUN_ID`
- `python -m synthran network prepare ...`
- `python -m synthran network deploy --dry-run --inventory PATH`
- `python -m synthran network deploy ... --run-id RUN_ID`
- `python -m synthran network verify --inventory PATH --run-id RUN_ID --timeout 120`
- `synthran experiment plan --network-run-id NETWORK_RUN_ID --run-id EXPERIMENT_RUN_ID`
- `synthran experiment run --inventory PATH --network-run-id NETWORK_RUN_ID --run-id EXPERIMENT_RUN_ID`
- `synthran experiment verify --run-id EXPERIMENT_RUN_ID`
- `python -m synthran experiment research calibrate --inventory PATH --network-run-id NETWORK_RUN_ID --target CORE_IP --duration-seconds 10 --out PATH`
- `python -m synthran experiment research plan --campaign-id ID --network-run-id NETWORK_RUN_ID --run-id RUN_ID --condition baseline`
- `python -m synthran experiment research run --inventory PATH --campaign-id ID --network-run-id NETWORK_RUN_ID --run-id RUN_ID --condition baseline --probe-target CORE_IP`
- `python -m synthran experiment research campaign-plan --campaign-id ID --network-run-id NETWORK_RUN_ID --seeds 424242,424243 --conditions baseline,load50:0.5 --campaign-seed 12345 --out PATH`
- `python -m synthran experiment research campaign-run --campaign PATH --inventory PATH --target CORE_IP --reference-capacity-bps CAPACITY`
- `python -m synthran experiment research analyze --campaign PATH --out PATH`
- `python -m unittest discover -s tests -v`

The experiment has a separate non-mutating `plan` command rather than pretending live `run` is a dry-run.

## Git and Validation

Use a feature branch for substantial/risky integrated work. Keep commits coherent. Never discard unrelated user changes or merge substantial live-orchestration changes merely because offline CI is green.

Before completion:

- inspect the full diff and intended file set;
- run applicable unit/schema/lint/build checks;
- run privacy scanning;
- confirm dependency pins remain immutable;
- confirm generated and secret-bearing paths stay ignored;
- test safety-critical failure paths;
- confirm docs match implemented commands;
- confirm `decision.md` remains untracked;
- report anything not exercised in the real environment;
- never claim live experiment success without operator-provided evidence.
