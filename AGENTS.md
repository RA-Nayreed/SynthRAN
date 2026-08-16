# SynthRAN Repository Instructions

## Purpose

SynthRAN is a reproducible experiment orchestrator joining emulated IoT workloads, programmable 5G/Open RAN infrastructure, and intelligence-ready datasets.

The supported golden path is:

```text
10 deterministic Contiki-NG/Cooja MQTT sensors
-> RPL/6LoWPAN border router
-> Cooja Serial Socket
-> tunslip6/tun0
-> counted controller ingress
-> Mosquitto bridge in the srsUE network namespace
-> tun_srsue1
-> srsRAN gNB
-> Open5GS UPF
-> run-owned central Mosquitto broker
-> canonical JSONL
-> deterministic Parquet
```

SynthRAN owns orchestration, contracts, integration adapters, validation, artifact collection, cleanup, and reproducibility reporting. It does not reimplement Open5GS, srsRAN, Contiki-NG, Cooja, or Mosquitto.

## Current Status and Acceptance

The repository foundation is accepted and published on `main`.

The supported Open5GS + srsRAN + RFSIM network baseline has completed live SLICES acceptance. The accepted run reached `path-proven` only after proving:

- one run-owned digest-locked gNB is Running and Ready;
- one run-owned digest-locked srsUE is Running and Ready;
- one run-owned digest-locked slice-one UPF is Running and Ready;
- the gNB cell activated;
- `tun_srsue1` is UP;
- the UE has an address in the expected `12.1.0.0/16` PDU network;
- the UE route selects `tun_srsue1`;
- the selected UPF routes the PDU network through `ogstun`.

Deployment success alone remains `deployed-unverified`. Only the separate read-only network verifier may promote a matching manifest to `path-proven`.

The active implementation milestone is the integrated deterministic IoT-to-5G experiment. Its repository-side implementation includes the ten-sensor Cooja workload, RPL border-router path, MQTT ingress, UE-side bridge, central broker, collector, JSONL/Parquet pipeline, evidence, exact-run cleanup, and accepted-network reproof. Do not describe this experiment milestone as accepted until an operator-run live experiment persists `IOT-TO-5G PATH PROVEN`.

## Supported and Deferred Technology

The first supported configuration is deliberately narrow:

- core: Open5GS;
- RAN: srsRAN;
- radio: RFSIM;
- UE: one srsUE representing the IoT edge gateway;
- slice: one slice, SST 1, DNN `internet`;
- IoT: exactly ten deterministic Contiki-NG/Cooja sensors;
- edge networking: Cooja Serial Socket plus pinned `tunslip6/tun0`;
- messaging: digest-pinned Mosquitto at the UE edge and core;
- data: append-only JSONL as the audit record and deterministic Parquet derived from JSONL.

The following remain deferred through the integrated golden-path milestone unless an explicit accepted decision promotes them:

- multiple UEs or slices;
- physical radios;
- impairment campaigns;
- formal O-RAN A1 or E2 control;
- RIC integration;
- generative models;
- synthetic-telemetry generation;
- automated RAN-policy synthesis.

Path-proven network acceptance does not automatically promote any deferred feature.

## Immutable Dependency Boundary

SynthRAN composes existing projects through pinned checkouts, adapters, and overlays.

- Reuse `sopnode/5g_ansible` as a complete external pinned checkout. Do not vendor it.
- Reuse Contiki-NG as a complete external pinned checkout. Keep SynthRAN sensor source out of tree under `deploy/iot/`.
- Treat Open5GS Kubernetes and srsRAN Helm repositories as transitive dependencies and resolve mutable upstream refs to immutable commits.
- Pin selected runtime container images by digest, not only by tag.
- Keep dependency trees below ignored `.deps/` storage.
- Never merge an upstream dependency branch into SynthRAN merely to consume it.
- Prefer configuration, exact overlays, reviewed patches, and stable upstream interfaces. Fork only when a maintained upstream change is unavoidable.
- Preserve third-party license and provenance records.
- Do not publish derivative `5g_ansible` source until its licensing is clarified.

The accepted network runtime/configuration contract must not regress:

- the Open5GS runtime must remain compatible with the locked v2.7-style configuration schema; do not restore the incompatible v2.6.4-aio runtime;
- remote srsRAN Ansible tasks inherit `/opt/synthran-venv/bin/python`; never leak `ansible_playbook_python` from the controller into a remote task;
- Helm image-pin rewrites preserve the source indentation rather than hardcoding indentation;
- ownership helpers render valid Helm/YAML and must not double-quote a value already passed through Helm `quote`;
- generated srsUE charts must pass `helm lint` and `helm template` before `helm upgrade --install`.

Update dependencies one at a time and record version, license, compatibility impact, and golden-path validation.

## Environment and Controller Contract

Linux is the only supported SynthRAN host platform for repository hooks, CI, live network control, and live experiment execution.

Use the named Conda environment `synthran`. `environment.yml` is the complete Linux environment definition; `pyproject.toml` is package/build metadata. Interactive instructions activate the environment once and invoke its tools directly. Hooks and CI may use `conda run` because they do not inherit an interactive shell. Never fall back to an arbitrary host Python or `venv`.

Use only `conda-forge` followed by `nodefaults`. Direct package versions must match `dependencies.lock.yml`. The current lock is direct-version locking, not a complete platform artifact lock; do not claim artifact-level environment reproducibility until platform-specific artifact locks exist.

The Linux SLICES Webshell, or a documented SSH session to its management host, is the only supported live controller. Live network operations require:

- active `synthran` environment;
- exact locked Python and Ansible versions;
- POS 2.5.35;
- valid SLICES authentication;
- explicitly selected project;
- existing experiment.

SynthRAN must never perform `slices auth login`, change the active project, or create the SLICES experiment. Those are operator actions.

A SLICES controller-probe timeout is not evidence that the 5G path failed. Keep controller/context failure distinct from radio/core path proof. The accepted live network verification required additional controller timeout headroom; operator guidance may use `--timeout 120` for acceptance verification until controller and path-proof timeouts are independently modeled.

## Network Lifecycle and Safety

Network resource preparation, deployment, verification, experiment execution, and network teardown are separate operations.

- Resource preparation is explicit and may reserve, jointly allocate, image, reset, and configure only the reviewed node pair. It stops before 5G deployment.
- Network deployment is explicit and requires fresh matching live-preflight evidence.
- Deployment uses an isolated detached worktree at the locked `5g_ansible` commit and passes immutable Open5GS/srsRAN commits to the wrapper.
- Live preflight owns readiness. Deployment must fail instead of installing an unproven missing runtime dependency.
- The supported runtime graph is exactly one slice and one srsUE.
- Network verification is read-only with respect to provider authority and does not redeploy the network.
- A failed or orphaned preparation/deployment run ID is immutable evidence and is never reused.
- A verification attempt that aborts before writing network evidence does not invalidate an already successful `deployed-unverified` run.

Provider ownership is fail-closed. Unknown owner, foreign owner, expired authority, partial allocation, split allocation, missing reservation, or provider schema drift prevents mutation.

## Integrated IoT Experiment Boundary

The integrated experiment consumes an existing `path-proven` network. It must never reserve nodes, allocate nodes, image nodes, or deploy the base network. Its run manifest records:

```text
reservation_action = none
network_deployment_action = none
```

The deterministic initial scenario is:

- exactly ten sensor motes, IDs 1 through 10;
- one non-sensor RPL border-router mote;
- fixed Cooja seed and topology;
- Cooja Serial Socket on the run contract port;
- `tunslip6` creates `tun0` with `fd00::1/64`;
- sensors publish run-scoped MQTT telemetry to the `fd00::1` edge address;
- a counted controller TCP adapter forwards the raw MQTT stream to the run-owned UE-side broker;
- the real edge Mosquitto bridge runs as a temporary sidecar in the run-owned srsUE pod so it shares the network namespace containing `tun_srsue1`;
- the bridge binds to the accepted UE PDU address;
- a run-specific central-broker route is explicitly selected through `tun_srsue1`;
- a digest-pinned run-owned central Mosquitto broker runs on the selected core node;
- the collector subscribes only to the current run topic.

Do not move the cellular bridge to the controller: `tun_srsue1` and its PDU address exist in the srsUE pod network namespace, so a controller-local Mosquitto process cannot truthfully prove UE-interface binding.

The experiment is accepted only when all required evidence passes, including:

- deterministic Cooja/Serial Socket startup;
- `tunslip6/tun0` readiness;
- all ten sensor identities crossing the counted edge ingress;
- bridge configuration bound to the accepted UE PDU address;
- `tun_srsue1` traffic-counter growth during telemetry delivery;
- accepted slice-one UPF path still valid;
- all ten streams received centrally;
- required contiguous sequence windows with no duplicate or missing sequence numbers;
- valid JSONL;
- deterministic Parquet;
- exact-run cleanup;
- successful accepted-network reproof after cleanup.

Running pods or brokers alone are not experiment acceptance.

## Cleanup and Ownership

Every runtime resource must carry the experiment run ID wherever the target supports labels or equivalent metadata.

Cleanup must:

- target only resources proven to belong to the requested run;
- use exact resource labels or exact known resource names, never broad guessed deletion;
- terminate run-owned local process groups;
- remove the temporary UE-side broker sidecar and config volume without replacing the base UE container;
- remove run-labeled central broker/config objects;
- wait for the srsUE Deployment to recover;
- re-run accepted-network verification;
- fail closed if the original base deployment cannot be reproven.

Experiment cleanup does not tear down the base 5G deployment. Network teardown remains a separate explicit operator action.

A failed experiment must retain a run-scoped manifest and available local logs. Never reuse the failed experiment run ID.

## Data Contract

`JSONL` is the append-only audit record. Parquet is derived and must be reproducible from accepted JSONL.

The initial telemetry schema accepts only `sensor-01` through `sensor-10`. Each event contains:

- schema identifier;
- experiment run ID;
- sensor ID;
- positive sequence number;
- sensor time;
- deterministic integer measurement.

Malformed messages never enter valid JSONL/Parquet. Rejected-event artifacts may record validation reason and topic but must not copy raw untrusted payloads by default.

Sequence acceptance must detect missing sensors, gaps, and duplicates rather than relying only on aggregate counts.

## Repository Boundaries

Use these top-level ownership boundaries:

- `contracts/`: versioned scenario, telemetry, readiness, deployment, and evidence schemas;
- `synthran/`: CLI, orchestration, adapters, collection, validation, evidence, and reporting;
- `deploy/`: SynthRAN-owned Ansible overlays plus out-of-tree IoT source/configuration;
- `docs/`: architecture, operator, dependency, development, and security documentation;
- `tests/`: offline tests and sanitized fixtures containing no real credentials or private captures.

Do not commit dependency checkouts, generated inventories, run artifacts, generated firmware products, packet captures, kubeconfigs, private authority files, or copied upstream repositories.

Keep root `README.md` as the public landing page. Detailed procedures live under `docs/`.

## Credentials, Privacy, and Public Artifacts

Never commit:

- IMSIs, authentication keys, OPC values, or subscriber credentials;
- SLICES tokens or credentials;
- kubeconfigs;
- private keys;
- secret-bearing `.env` files;
- unsanitized packet captures;
- private authority files;
- unsanitized testbed logs;
- dependency worktrees;
- generated run directories.

Public manifests retain reproducibility facts without credentials: dependency hashes, image digests, scenario hashes, node roles, non-secret route facts, timestamps, and validation status.

Privacy protection is layered:

1. ignore rules exclude generated and credential-bearing paths from normal Git status;
2. the local pre-push hook scans outgoing commits before transport;
3. GitHub push protection remains an independent server-side control;
4. CI runs the SynthRAN source scanner and Gitleaks over full history;
5. public derivatives are sanitized separately rather than rewriting source in place.

Never bypass a true secret finding merely to pass CI. Rotate exposed credentials and remove them from every affected commit.

The default integrated acceptance does not require a packet capture. Route proof, interface counters, broker receipt, message integrity, and the accepted UPF path are preferred because they avoid unnecessary raw-capture privacy risk.

## User and Agent Responsibilities

The user is the live experiment operator. The user performs:

- external account administration;
- explicit testbed reservations and allocations;
- live resource preparation;
- network deployment;
- live experiment execution;
- destructive or infrastructure-wide teardown.

An agent may, when requested:

- author/edit repository code, contracts, configuration, tests, and documentation;
- inspect repository/dependency state read-only;
- run safe offline validation;
- prepare non-mutating plans;
- explain operator commands and analyze returned evidence.

An agent must not reserve SLICES resources, silently deploy the network, run the live experiment, ignore reservation conflicts, or make external infrastructure changes unless the user explicitly changes this rule.

## Decision Journal Procedure

`decision.md` is a local, intentionally untracked engineering journal. It is excluded through `.git/info/exclude`, not the tracked `.gitignore`.

At the start of substantial work:

1. read `AGENTS.md`;
2. read relevant local `decision.md` entries;
3. inspect Git status and the active milestone;
4. record material architecture/dependency/interface/security/workflow decisions locally.

At the end:

1. complete affected decision entries;
2. promote durable rules into `AGENTS.md`;
3. confirm `decision.md` remains untracked;
4. report durable contract changes.

The journal contains engineering rationale, not hidden reasoning, credentials, subscriber data, packet contents, or kubeconfigs.

## Repository Commands

Run commands from the repository root after activating `synthran`.

- `conda env create --file environment.yml`: create the complete Linux environment.
- `conda env update --file environment.yml --prune`: reconcile an existing environment.
- `conda activate synthran`: activate the supported interactive environment.
- `python -m synthran deps sync --dry-run`: preview direct dependency synchronization.
- `python -m synthran deps sync`: synchronize clean detached direct dependencies.
- `python -m synthran deps sync --all`: also synchronize locked transitive dependencies for inspection.
- `python -m synthran privacy scan --worktree`: scan tracked/unignored source.
- `python -m synthran privacy scan --history`: scan complete Git history with SynthRAN rules.
- `python -m synthran hooks install --dry-run`: preview pre-push hook activation.
- `python -m synthran doctor --offline --inventory PATH`: validate static network inputs.
- `python -m synthran slices doctor --slices-project PROJECT --slices-experiment EXPERIMENT`: read-only controller/context verification.
- `python -m synthran network prepare --dry-run --owner OWNER --run-id RUN_ID`: preview resource preparation.
- `python -m synthran network prepare ...`: operator-only guarded live preparation.
- `python -m synthran doctor --inventory PATH ... --evidence-out PATH`: live read-only preflight.
- `python -m synthran network deploy --dry-run --inventory PATH`: non-executing network deployment plan.
- `python -m synthran network deploy ... --run-id RUN_ID`: operator-only explicit network deployment.
- `python -m synthran network verify --inventory PATH --run-id RUN_ID --timeout 120`: read-only accepted-network proof.
- `synthran-phase3 plan --network-run-id NETWORK_RUN_ID --run-id EXPERIMENT_RUN_ID`: non-mutating integrated scenario plan.
- `synthran-phase3 run --inventory PATH --network-run-id NETWORK_RUN_ID --run-id EXPERIMENT_RUN_ID`: operator-only integrated experiment.
- `synthran-phase3 verify --run-id EXPERIMENT_RUN_ID`: read-only persisted experiment-evidence rendering.
- `python -m unittest discover -s tests -v`: offline unit suite.

Modifying operations retain dry-run behavior where technically meaningful. The integrated experiment has a separate `plan` command rather than pretending its live `run` is a dry-run.

## Git Workflow

- Do not create a branch for every small task.
- Use a feature branch for substantial/risky integrated work that benefits from review.
- Keep commits coherent and explain intent.
- Never discard unrelated user changes.
- Do not merge substantial live-orchestration changes merely because offline CI is green; require the appropriate operator acceptance evidence.
- Before publishing, inspect the complete diff and confirm no generated or secret-bearing artifacts are included.

## Validation Required Before Completion

Before declaring repository work complete:

- inspect the intended diff/file set;
- run applicable schemas, unit, syntax, build, lint, and offline integration checks;
- run privacy scanning;
- confirm immutable dependency identifiers;
- confirm generated and credential-bearing paths remain ignored;
- test safety-critical failure paths;
- ensure documentation matches implemented interfaces;
- confirm `decision.md` remains local/untracked;
- explicitly report checks not run and why.

Before declaring the accepted network complete, require operator-provided `path-proven` evidence.

Before declaring the integrated IoT-to-5G experiment complete, require operator-provided live evidence ending in `IOT-TO-5G PATH PROVEN`. Offline CI, Cooja compilation alone, or Running Kubernetes resources are insufficient.
