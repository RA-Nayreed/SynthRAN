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

SynthRAN owns orchestration, contracts, integration adapters, validation, artifact collection, cleanup, and reproducibility reporting. It does not reimplement Open5GS, srsRAN, Contiki-NG, Cooja, or Mosquitto.

## Product Vocabulary and CLI

Development milestones are engineering history, not product architecture. Do not encode milestone numbers or temporary planning labels in public commands, module names, class names, schemas, Kubernetes labels, generated filenames, logs, documentation paths, or runtime statuses.

There is exactly one product executable: `synthran`.

Stable command groups are named for domains and operations, for example:

```text
synthran network prepare|deploy|verify
synthran experiment plan|run|verify
synthran deps sync
synthran privacy scan|redact
```

Do not create milestone-specific executables or compatibility aliases for unreleased temporary interfaces. Internal Python modules should describe their responsibility, such as `experiment`, `experiment_runtime`, `experiment_resources`, `iot`, `mqtt_collector`, or `ingress`.

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

The integrated deterministic IoT-to-5G experiment is implemented repository-side but is not accepted until an operator-run live experiment persists `IOT-TO-5G PATH PROVEN`.

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
- data: append-only JSONL and deterministic Parquet derived from JSONL.

The following remain deferred unless an explicit accepted decision promotes them:

- multiple UEs or slices;
- physical radios;
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

## Cleanup and Ownership

Every runtime resource carries the experiment run ID where supported.

Cleanup must:

- target only resources proven to belong to the requested run;
- use exact labels or exact known resource names, never broad guessed deletion;
- terminate run-owned local and remote process groups;
- explicitly terminate exact run-scoped remote processes (matching run workspace, UE pod, and central deployment);
- remove run-created/partially-created `tun0` on the core node and verify its absence postcondition;
- remove the run-scoped workspace `/tmp/synthran/<run-id>/` on the core node and verify its absence postcondition;
- verify host runtime postconditions (reserved ports `60001`, `18883`, and `18885` free, `tun0` absent, workspace absent);
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

- `contracts/`: versioned scenario, telemetry, readiness, deployment, and evidence schemas;
- `synthran/`: CLI, orchestration, adapters, collection, validation, evidence, and reporting;
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

An agent may author repository code/config/tests/docs, inspect repository/dependency state read-only, run safe offline validation, prepare non-mutating plans, and analyze operator-provided evidence.

An agent must not reserve SLICES resources, silently deploy the network, run the live experiment, ignore reservation conflicts, or make external infrastructure changes unless the user explicitly changes this rule.

## Decision Journal

`decision.md` is local and intentionally untracked through `.git/info/exclude`, not tracked `.gitignore`.

Record material architecture, dependency, interface, security, workflow, and scope decisions there. Promote durable rules into `AGENTS.md`. Never put credentials, subscriber data, packet contents, or kubeconfigs in the journal.

## Repository Commands

Run from the repository root after activating `synthran`.

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
