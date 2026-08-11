# SynthRAN

SynthRAN is a reproducible experiment platform joining emulated IoT workloads, programmable 5G/Open RAN infrastructure, and intelligence-ready datasets.

## Why this repository exists

`5g_ansible` can deploy several 5G core and RAN combinations on the target testbed. Contiki-NG can emulate constrained IoT networks. Neither project owns the experiment contract that connects deterministic IoT traffic to a provable 5G user-plane path and produces a versioned dataset.

SynthRAN owns that missing layer:

- immutable dependency selection;
- experiment and event contracts;
- adapters around upstream deployment and simulation systems;
- run-scoped orchestration and cleanup;
- privacy-aware artifact collection;
- path proof, validation, and reproducibility reporting.

SynthRAN does **not** copy or reimplement the upstream systems. Complete pinned checkouts are placed under the ignored `.deps/` directory and used through explicit adapters. This preserves upstream repository assumptions without turning SynthRAN into an unmaintainable fork.

## Initial golden path

```text
10 Contiki-NG/Cooja MQTT sensors
-> RPL/6LoWPAN border router
-> tunslip6/tun0
-> edge Mosquitto broker
-> MQTT bridge bound to tun_srsue1
-> srsRAN gNB
-> Open5GS UPF
-> central Mosquitto broker
-> JSONL audit data and derived Parquet data
```

The first prototype supports Open5GS, srsRAN, RFSIM, and one srsUE edge gateway. Physical radios, multiple UEs, formal O-RAN A1/E2 control, RIC integration, and generative models are deferred until this path is reproducible.

## Current status

The repository is establishing the `v0.0.1` foundation. The available code safely synchronizes pinned dependencies and scans or redacts sensitive text. It does not deploy a network or run an experiment yet.

## Conda environment

Miniforge or another Conda distribution is the only supported development and CI environment. Create the named environment from the repository root:

```sh
conda env create --file environment.yml
```

When `environment.yml` changes, reconcile an existing environment and remove packages that are no longer declared:

```sh
conda env update --file environment.yml --prune
```

All project commands use `conda run` so they do not depend on shell activation or a host Python installation. `pyproject.toml` remains Python package/build metadata; it is not a second environment manager.

`environment.yml` and `dependencies.lock.yml` pin every direct Conda dependency used by the current code. Conda still selects platform-specific transitive builds during the solve, so this foundation is deliberately marked `direct-versions-only`. Platform-specific `conda-lock` files are required before claiming artifact-level reproducibility.

## Dependency bootstrap

Preview dependency synchronization without changing the filesystem:

```sh
conda run --no-capture-output -n synthran python -m synthran deps sync --dry-run
```

Synchronize the direct dependencies into `.deps/` as detached checkouts:

```sh
conda run --no-capture-output -n synthran python -m synthran deps sync
```

Transitive repositories are locked for the deployment adapter but are not checked out by default. To inspect all locked Git repositories locally:

```sh
conda run --no-capture-output -n synthran python -m synthran deps sync --all
```

No dependency command merges a branch into SynthRAN.

## Privacy protection before publication

GitHub Actions runs only after a push reaches GitHub, so CI cannot be the only preventive control. Install the repository's local pre-push hook once per clone:

```sh
conda run --no-capture-output -n synthran python -m synthran hooks install --dry-run
conda run --no-capture-output -n synthran python -m synthran hooks install
```

The hook invokes the same named Conda environment as CI and development. It discovers Conda through `SYNTHRAN_CONDA_EXE`, then `CONDA_EXE`, then `PATH`. On Windows it also checks standard Anaconda, Miniconda, and Miniforge installation directories derived from environment variables, without storing a username or machine-specific absolute path. It fails closed when Conda or the environment is unavailable. `SYNTHRAN_CONDA_ENV` may select a deliberately equivalent environment, but the supported default is `synthran`.

Scan the current worktree manually:

```sh
conda run --no-capture-output -n synthran python -m synthran privacy scan --worktree
```

The hook scans every outgoing commit, including sensitive content added and removed in separate outgoing commits. The GitHub workflow repeats the repository scan and runs Gitleaks across full history. Findings identify the rule and location but do not print the detected value.

Source files are rejected rather than automatically changed. Generated text artifacts can be sanitized into a separate file:

```sh
conda run --no-capture-output -n synthran python -m synthran privacy redact input.txt sanitized.txt --dry-run
conda run --no-capture-output -n synthran python -m synthran privacy redact input.txt sanitized.txt
```

Redaction replaces local user homes, usernames, network-share prefixes, and private IP addresses with stable placeholders. Never use text redaction for packet captures, kubeconfigs, private keys, or binary credential stores; keep those untracked and publish only purpose-built sanitized derivatives.

GitHub push protection should remain enabled as a separate server-side safeguard. Do not bypass a real secret finding; remove the secret from every affected commit and rotate it if it was exposed.

## Operator boundary

The user runs reservations, compilation in the real toolchain, network deployments, experiments, and infrastructure teardown. Repository automation must never reserve a node, ignore a reservation conflict, silently deploy the network, or run an experiment on the user's behalf.

See [the architecture](docs/architecture.md), [third-party provenance](THIRD_PARTY.md), and [repository instructions](AGENTS.md) before extending the implementation.
