# SynthRAN Repository Instructions

## Purpose

SynthRAN is a reproducible experiment orchestrator joining emulated IoT workloads, programmable 5G/Open RAN infrastructure, and intelligence-ready datasets.

The initial golden path is:

```text
10 Contiki-NG/Cooja MQTT sensors
-> RPL/6LoWPAN border router
-> tunslip6/tun0
-> edge Mosquitto broker
-> Mosquitto bridge bound to tun_srsue1
-> srsRAN gNB
-> Open5GS UPF
-> central Mosquitto broker
-> JSONL audit data and derived Parquet data
```

The repository owns orchestration, contracts, integration adapters, validation, artifact collection, and reproducibility reporting. It does not reimplement the 5G core, RAN, IoT operating system, simulator, or MQTT broker.

## Current Status and Acceptance

The `v0.0.1` repository foundation is published on `main`. The current golden-path network milestone has a SLICES CLI controller contract, an Open5GS + srsRAN + RFSIM inventory contract, offline and read-only live doctors, redacted immutable planning, evidence-gated isolated-worktree deployment, and gNB/srsUE/tunnel/UPF verification. The code is offline-tested. The operator accepted the lean Linux preparation path's version-pinned experimental bootstrap risk, so guarded live preparation is enabled; the milestone remains unaccepted until the operator supplies path-proven SLICES evidence.

The repository foundation is accepted only when it has:

- a clear README describing the problem, golden path, supported configuration, and deferred work;
- an Apache-2.0 license for original SynthRAN code;
- an immutable dependency lock;
- third-party license and provenance documentation;
- a concise architecture description showing ownership boundaries;
- repository ignore rules for generated, local, credential-bearing, and experimental artifacts;
- this `AGENTS.md` working contract;
- a local, untracked `decision.md` decision journal;
- lightweight validation proving the foundational documents are internally consistent and do not expose secrets.

Do not describe the foundation as accepted merely because directories or placeholder files exist. Do not begin deployment or experiment execution as part of foundation documentation work.

The golden-path network is accepted only when:

- current reservation and allocation ownership are verified for every selected node;
- SSH, Kubernetes, and required-image readiness checks fail closed;
- deployment uses an isolated detached worktree at the locked `5g_ansible` commit;
- the locked Open5GS Kubernetes and srsRAN Helm commits are passed to Ansible;
- network deployment remains an explicit operator command and produces redacted logs;
- the srsRAN gNB and srsUE are discovered and healthy;
- `tun_srsue1`, the UE PDU address, slice, and selected UPF route are verified;
- route/tunnel evidence is recorded without committing private captures or credentials;
- the operator executes the SLICES acceptance commands and supplies the evidence.

## Supported and Deferred Technology

The first supported configuration is deliberately narrow:

- core: Open5GS;
- RAN: srsRAN;
- radio: RFSIM;
- UE: one srsUE representing an IoT edge gateway;
- IoT workload: ten deterministic Contiki-NG/Cooja sensors;
- messaging: Mosquitto at the edge and core, with MQTT topic bridging;
- data products: append-only JSONL as the audit record and reproducible Parquet derived from JSONL.

The following are deferred until the golden path is reproducible and path-proven:

- multiple UEs and slices;
- physical radios;
- impairment campaigns;
- formal O-RAN A1 or E2 control;
- RIC integration;
- generative models;
- synthetic-telemetry generation;
- automated RAN-policy synthesis.

Do not introduce a deferred technology into the critical path without an explicit accepted decision recorded in `decision.md` and promoted here.

## Dependency Reuse and Pinning

SynthRAN composes existing projects through adapters and overlays.

- Use `sopnode/5g_ansible` as an external, complete, pinned checkout. Do not copy or vendor it.
- Use Contiki-NG as an external, complete, pinned checkout and keep the SynthRAN application out of tree. Do not copy or vendor Contiki-NG.
- Treat Open5GS Kubernetes and srsRAN Helm repositories used by `5g_ansible` as transitive dependencies and resolve every mutable branch reference to an immutable commit.
- Pin container images by digest, not only by tag.
- Linux is the only supported SynthRAN host platform for development, hooks, CI, and live operation.
- Use the named Conda environment `synthran` everywhere. `environment.yml` is the single complete Linux definition and includes deployment tooling. `pyproject.toml` is package/build metadata only.
- Use only `conda-forge` followed by `nodefaults`. Pin every direct Conda package to one exact version in `environment.yml` and the project lock.
- Interactive instructions must explicitly activate `synthran` before invoking `python` or environment tools directly. Repository hooks and CI may use `conda run` because they do not inherit an interactive shell. Never fall back to a global Python or `venv`.
- Treat the current Conda dependency record as direct-version locking, not a complete platform artifact lock. Generate and validate platform-specific `conda-lock` files before claiming artifact-level environment reproducibility.
- Keep downloaded dependencies in ignored local storage such as `.deps/`.
- Never rely on a mutable branch at experiment runtime.
- Prefer configuration, overlays, patches, and stable upstream interfaces. Fork only when a maintained upstream modification is unavoidable.
- Vendor source only after confirming its license permits redistribution and recording why pinned external reuse is no longer practical.
- Preserve copyright, license, provenance, and modification notices for copied material.
- Do not publish derivative `5g_ansible` source until its licensing has been clarified; its reviewed pinned tree had no top-level license.

Update dependencies one at a time. A dependency update is accepted only after its version, license, compatibility impact, and golden-path validation are recorded.

`dependencies.lock.yml` intentionally uses the JSON-compatible subset of YAML so the bootstrap command can validate it without a YAML parser. `synthran deps sync` creates detached checkouts under `.deps/`; it never merges an upstream branch into SynthRAN. Direct dependencies are synchronized by default and `--all` is required to include transitive repositories for local inspection.

The golden-path adapter uses direct `ansible-galaxy` and `ansible-playbook` calls against isolated locked worktrees. Do not wrap interactive `5g_ansible/deploy.sh`; it contains reservation prompts and bypass behavior outside SynthRAN's control boundary. The first native preparation path is deliberately version-pinned rather than artifact-reproducible: it pins `5g_ansible`, `kubernetes.core`, `community.general`, `ansible.posix`, direct remote Python packages, Helm, and yq, while accepting upstream apt, chart, manifest, and installer transitives. Do not install the legacy `community.kubernetes` collection unless a locked graph contains an actual call to it. The operator accepted the remaining experimental risk in `decision.md`, and `resource_bootstrap.status=ready` enables only the guarded Linux preparation path. Syntax checks must pass before POS mutation. The separate deployment wrapper remains gated by fresh matching live-doctor evidence and pins the selected runtime inputs more narrowly.

The Linux SLICES Webshell, or an SSH session to its documented management host, is the only supported live controller. Every live prepare, doctor, deploy, and verify operation requires an active `synthran` Conda environment, exact locked Python and Ansible versions, POS 2.5.35, a valid SLICES login, an explicitly selected project, and an existing experiment. Standalone read-only controller probes use a 60-second per-command timeout. SynthRAN must never run `slices auth login`, change the active project, or create the experiment; those are operator actions. Public evidence stores only project and experiment fingerprints plus controller versions and the exact dependency-lock digest.

The preparation boundary patch must apply cleanly to the locked upstream commit before Ansible runs. It removes upstream per-node allocation changes and prevents preparation from entering Open5GS or srsRAN roles. Remote dependency checkouts must be unique and run-scoped. Live preflight, not deployment, owns tool readiness; deployment must fail rather than install a missing tool. The runtime graph remains exactly one slice and one srsUE.

## Repository Boundaries

Use these top-level ownership boundaries when implementation begins:

- `contracts/`: versioned scenario, event, metric, and manifest schemas;
- `synthran/`: CLI, orchestration, adapters, collection, validation, and reporting;
- `deploy/`: SynthRAN-owned Ansible roles, Kubernetes overlays, container definitions, and run-scoped configuration;
- `docs/`: architecture and operator documentation;
- `tests/`: offline tests and test fixtures that contain no real credentials or captured private traffic.

Do not commit dependency checkouts, generated inventories, run artifacts, firmware build products, packet captures, kubeconfigs, or copied upstream repositories.

Keep root `README.md` as the public project landing page: purpose, research problem, architecture, ownership, current status, concise quick start, outputs, repository map, and roadmap. Put detailed setup, security, dependency, and operator procedures in focused files under `docs/`.

Generated run data belongs under a run-scoped ignored location. Every created runtime resource must carry the run ID wherever the target system supports labels or equivalent metadata.

## User and Codex Responsibilities

The user is the experiment operator. The user performs:

- repository creation and external account administration;
- explicit testbed resource preparation, including reservations and allocations;
- Conda installation and the first environment solve on the operator machine;
- compilation when it requires the real toolchain or testbed;
- network deployment;
- experiment execution;
- destructive or infrastructure-wide teardown.

Codex may, when requested:

- author and edit repository code, schemas, configuration, tests, and documentation;
- perform read-only repository and dependency inspection;
- run safe offline validation that does not reserve nodes, deploy infrastructure, or conduct the experiment;
- explain each command the user should run and interpret the output the user provides.

Codex must not run live resource preparation or the SynthRAN experiment on the user's behalf. It must not reserve SLICES nodes, ignore reservation conflicts, silently deploy the 5G network, or make external infrastructure changes unless the user explicitly changes this rule.

## Lifecycle and Safety Rules

- Network deployment is always a separate, explicit operation.
- Resource preparation is an explicit operator command that may reserve, jointly allocate, image, reset, and configure only the selected reviewed node pair. It must stop before 5G deployment.
- An experiment run never reserves nodes and never silently deploys the network.
- Preflight must fail when the required reservation, allocation, SSH access, Kubernetes state, dependency, or image is unavailable.
- Reservation failure is terminal for preflight and can never be ignored automatically.
- Every modifying command must support a dry-run mode where technically meaningful.
- Cleanup targets only resources proven to belong to the requested run ID.
- Experiment cleanup does not tear down the base 5G deployment unless the operator requests network teardown separately.
- Cleanup must be idempotent and verify that the original base deployment shape remains operational.
- A failed run must still produce a partial manifest, available logs, and a failure report.
- Never use broad deletion targets, unresolved globs, or guessed resource names for cleanup.

## Data, Credentials, and Artifacts

Never commit:

- generated inventories;
- IMSIs, authentication keys, OPC values, or subscriber credentials;
- SLICES credentials or reservation tokens;
- kubeconfigs;
- private keys;
- `.env` files containing secrets;
- unsanitized packet captures;
- raw testbed logs containing credentials or private addresses that have not been approved for publication;
- dependency worktrees or generated run directories.

Manifests and reports must redact secrets while retaining reproducibility facts such as dependency hashes, image digests, scenario hashes, node roles, non-secret route evidence, timestamps, and validation status.

JSONL is the append-only audit record. Parquet is derived output and must be reproducible from JSONL. Malformed events go to a rejected-events artifact and never enter the valid Parquet dataset.

## Privacy Guardrails

Privacy protection is layered because GitHub Actions runs after content reaches GitHub:

1. tracked ignore rules keep known local, generated, credential-bearing, and capture paths out of normal Git status;
2. the tracked `.githooks/pre-push` hook scans every outgoing commit before transport after the operator activates it;
3. GitHub push protection remains enabled as an independent server-side control;
4. the privacy workflow scans source context and runs Gitleaks with full history;
5. generated public text is produced as a separate sanitized derivative using deterministic placeholders.

Source scanning fails instead of rewriting files. It reports only the rule and location and must not print the detected value into a terminal or CI log. Fix a true finding in every affected commit and rotate an exposed credential; do not add a blanket allowlist or bypass merely to make CI pass.

The text redactor may sanitize local user homes, usernames, network-share prefixes, and private IP addresses. It must never rewrite its input in place. Do not attempt to text-redact packet captures, kubeconfigs, private keys, databases, or other binary/structured credential stores; keep them local and create purpose-built sanitized derivatives.

The pre-push hook must execute the privacy scanner with `conda run --no-capture-output -n synthran`. On Linux it may locate Conda through `SYNTHRAN_CONDA_EXE`, `CONDA_EXE`, or `PATH`, and may accept `SYNTHRAN_CONDA_ENV` as an explicit environment override. Never store a username or machine-specific absolute installation path in the hook. It must never fall back to an arbitrary host Python and must fail closed when Conda or the selected environment is unavailable.

All third-party GitHub Actions must be pinned to full commit SHAs and run with the minimum token permissions. Privacy workflows use read-only repository contents and do not upload finding reports that could reproduce sensitive values.

## Decision Journal Procedure

`decision.md` is a local, intentionally untracked engineering journal. It is excluded through `.git/info/exclude`, not the tracked `.gitignore`.

At the start of every task:

1. Read this file.
2. Read the relevant entries in `decision.md`.
3. Inspect Git status and the current project milestone.
4. Record any material new decision before implementing it.

Record every nontrivial choice affecting architecture, dependencies, interfaces, repository structure, testing, security, workflow, scope, deployment, or data handling. Each entry must state context, options, the chosen decision, concise rationale, evidence or assumptions, consequences, affected components, and follow-up.

Do not place credentials, subscriber data, kubeconfigs, packet contents, or other secrets in the journal. The journal documents explicit engineering rationale; it is not a transcript of hidden internal reasoning.

At the end of every task:

1. Complete or update the affected decision entries.
2. Promote durable conclusions and operational constraints into this file.
3. Confirm `decision.md` remains untracked.
4. Report which durable rules changed.

Temporary observations remain in `decision.md`. Update `AGENTS.md` only when a durable rule, command, interface, milestone, ownership boundary, safety constraint, or repository invariant changes.

## Repository Commands

Run commands from the repository root. Create or reconcile the environment, activate it once, confirm its name, and then invoke its tools directly.

- `conda env create --file environment.yml`: create the complete Linux `synthran` environment for a new clone.
- `conda env update --file environment.yml --prune`: reconcile the Linux environment after a definition change.
- `conda activate synthran`: activate the required environment in the current shell.
- `python -c "import os; assert os.environ.get('CONDA_DEFAULT_ENV') == 'synthran'"`: fail if the wrong environment is active.
- `python -m synthran deps sync --dry-run`: validate and preview direct dependency synchronization.
- `python -m synthran deps sync`: create or update clean detached direct-dependency checkouts under `.deps/`.
- `python -m synthran deps sync --all`: also synchronize locked transitive repositories for inspection.
- `python -m synthran privacy scan --worktree`: scan tracked and unignored source without printing detected values.
- `python -m synthran privacy scan --history`: apply SynthRAN privacy rules to all commits.
- `python -m synthran privacy redact INPUT OUTPUT --dry-run`: preview creation of a sanitized text derivative.
- `python -m synthran hooks install --dry-run`: preview activation of `.githooks` for the current clone.
- `python -m synthran doctor --offline --inventory PATH`: validate the static golden-path inventory, dependency lock, and pinned checkout without contacting SLICES.
- `python -m synthran slices doctor --slices-project PROJECT --slices-experiment EXPERIMENT`: verify the supported SLICES shell, login, project, experiment, and exact controller versions without changing provider state.
- `python -m synthran network prepare --dry-run --owner OWNER --run-id RUN_ID`: preview reservation, shared allocation, imaging, Kubernetes setup, and version-pinned tool installation without contacting POS; report the current bootstrap gate.
- `python -m synthran network prepare --owner OWNER --slices-project PROJECT --slices-experiment EXPERIMENT --run-id RUN_ID`: operator-only guarded live preparation; it may reserve, jointly allocate, image, reset, and configure only the reviewed node pair and must stop before 5G deployment.
- `python -m synthran doctor --inventory PATH --slices-project PROJECT --slices-experiment EXPERIMENT --owner OWNER --reservation-id RESERVATION --allocation-id ALLOCATION --evidence-out PATH`: run read-only live readiness checks and write sanitized evidence.
- `python -m synthran network deploy --dry-run --inventory PATH`: emit the redacted immutable deployment plan without reserving, booting, or deploying.
- `python -m synthran network deploy --inventory PATH --owner OWNER --reservation-id RESERVATION --allocation-id ALLOCATION --preflight-evidence PATH --run-id RUN_ID`: explicitly deploy the network from fresh matching evidence; operator use only.
- `python -m synthran network verify --inventory PATH --run-id RUN_ID`: read-only verification of run-owned gNB, srsUE, `tun_srsue1`, PDU address, and UPF route evidence.
- `python -m unittest discover -s tests -v`: run the offline unit test suite.

Dependency synchronization, resource preparation, hook installation, and redaction are modifying commands and must retain functional `--dry-run` behavior.

Live `network prepare` is enabled only while the reviewed bootstrap lock is `ready`. It must validate the pinned checkout and Ansible syntax before POS mutation, reject foreign/partial/split allocations, persist private recovery authority immediately as provider IDs become known, create or verify one current reservation, allocate both selected nodes together, use run-scoped trust-on-first-use for newly imaged SSH hosts and reject later key changes, preserve partial sanitized artifacts on failure, and never invoke a 5G deployment role. Native run evidence must record observed versions because upstream bootstrap transitives are not artifact-locked. Live `doctor` must remain read-only and require SLICES project, experiment, owner, reservation, allocation, and evidence output. Evidence must match the exact dependency-lock digest, complete successful check set, inventory, authority, controller versions, and SLICES context. Live `network deploy` and `network verify` must revalidate the supported controller and matching context before stateful or proof work. Deployment supports only separate core/RAN nodes, `profile=default`, one srsUE, monitoring disabled, and an empty ready cluster. `network verify` may mark a matching `deployed-unverified` manifest `path-proven` only after every proof passes.

The verified POS 2.5.35 reservation interface is `pos calendar list --filter owner=OWNER --json`. It returns an array with numeric `id`, `owner`, `nodes`, `start_date`, and `end_date`; SynthRAN must select exactly one requested ID and verify ownership, node coverage, and the current UTC window. Reservation creation uses `pos calendar create -d MINUTES -s now CORE RAN` and requires one numeric ID. Preparation inspects `pos allocations list --json`, allocates both nodes in one command, and verifies each with `pos allocations show NODE` using the returned string `id` and `owner`. Provider command or schema drift is terminal and must be adapted against operator-supplied value-free structural evidence.

## Git Workflow

- Do not create a branch for each milestone, task, or document section.
- Small, safe, coherent changes may be committed directly to `main` when the user chooses to publish them.
- Use one feature branch only for genuinely substantial or risky work that benefits from isolated review.
- Keep commits coherent and explain their intent.
- Never commit or push automatically merely because files were edited.
- Preserve unrelated user changes and never reset or discard them without explicit approval.
- Before publishing, inspect the complete diff, verify the intended file set, and confirm no secret or generated artifact is included.

## Validation Required Before Completion

Use validation proportional to the change. Before declaring repository work complete:

- inspect Git status and the full relevant diff;
- run applicable schema, unit, lint, formatting, build, or offline integration checks;
- confirm pinned dependencies use immutable identifiers;
- confirm `environment.yml` matches the Linux platform, direct package versions, channels, and environment name in `dependencies.lock.yml`;
- run validation inside `synthran` when Conda is available and report explicitly when the environment could not be solved or exercised;
- confirm generated and secret-bearing paths are ignored;
- confirm failure paths are tested where behavior is safety-critical;
- confirm documentation matches implemented interfaces and commands;
- confirm `decision.md` is ignored locally and not tracked;
- report tests not run and the reason;
- do not claim deployment or experiment success without operator-provided evidence from the real environment.

For the final SLICES acceptance run, the user executes the commands and supplies results. Codex may guide the run and analyze evidence but does not operate it.
