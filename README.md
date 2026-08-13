# SynthRAN

**A reproducible experiment platform joining emulated IoT workloads, programmable 5G/Open RAN, and intelligence-ready datasets.**

SynthRAN connects networked IoT simulation to a real 5G user plane and preserves enough evidence to prove what happened. Its first target is a deterministic stream of Contiki-NG/Cooja sensor measurements transported through an srsUE tunnel, an srsRAN gNB, and an Open5GS core into auditable JSONL and reproducible Parquet datasets.

SynthRAN is the integration and experiment-control layer. It reuses the upstream systems that already implement 5G deployment, radio access, constrained IoT networking, and MQTT instead of copying them into another fork.

## Why SynthRAN exists

IoT simulators can generate repeatable device behavior. Open 5G stacks can provide programmable radio and core networks. Neither side, by itself, answers the complete experimental question:

> Can a deterministic emulated IoT workload be transported through a provable 5G/Open RAN path and captured as a reproducible dataset suitable for later telemetry and policy synthesis research?

SynthRAN owns the missing experiment contract:

- immutable selection of upstream source and container dependencies;
- validation of one supported network configuration;
- explicit orchestration across IoT, edge, RAN, core, broker, and collector boundaries;
- run-scoped resource ownership and cleanup;
- route, interface, capture, broker, and message-integrity evidence;
- append-only raw records and reproducible analytical datasets.

## Golden path

```mermaid
flowchart LR
    subgraph IoT["Emulated IoT network"]
        S["10 deterministic Cooja sensors"] --> R["RPL / 6LoWPAN border router"]
    end

    R --> T["tunslip6 / tun0"]
    T --> E["Edge Mosquitto broker"]
    E --> U["srsUE / tun_srsue1"]
    U --> G["srsRAN gNB"]
    G --> C["Open5GS user plane"]
    C --> B["Central Mosquitto broker"]
    B --> D["JSONL audit data"]
    D --> P["Derived Parquet dataset"]

    O["SynthRAN control and evidence"] -. validates .-> T
    O -. pins and orchestrates .-> G
    O -. proves path .-> C
    O -. validates records .-> D
```

The initial experiment uses RFSIM rather than physical RF. One srsUE represents an IoT edge gateway serving ten constrained sensors. Sensor-to-edge MQTT uses QoS 0; the edge-to-core bridge uses QoS 1 and must bind to the UE PDU address.

## What is reused

| System | Responsibility | SynthRAN integration |
|---|---|---|
| `sopnode/5g_ansible` | SLICES node setup and 5G deployment | Complete detached checkout pinned to a commit; wrapped through a narrow adapter |
| Open5GS Kubernetes deployment | 5G core and UPF | Transitive repository pinned to a commit passed into Ansible |
| srsRAN Helm deployment | gNB, srsUE and RFSIM integration | Transitive repository pinned to a commit passed into Ansible |
| Contiki-NG and Cooja | RPL/6LoWPAN firmware and IoT simulation | Complete pinned checkout with a future out-of-tree SynthRAN application |
| Eclipse Mosquitto | Edge and central MQTT brokers | Containers pinned by digest with run-scoped configuration |

These repositories are not merged into SynthRAN, copied selectively, or tracked as submodules. Local detached checkouts live under ignored `.deps/` storage. See [dependency reuse and provenance](docs/dependencies.md) and [third-party licenses](THIRD_PARTY.md).

## Current status

SynthRAN is in early development. The repository foundation is complete, and the golden-path network implementation is offline-tested but not accepted on SLICES. The operator accepted the lean Linux preparation path's experimental bootstrap risk, so guarded live preparation is enabled; its upstream transitives remain version-pinned rather than artifact-locked.

| Capability | Status |
|---|---|
| Conda environment, immutable dependency metadata and privacy controls | Implemented and tested |
| Pinned upstream dependency synchronization | Implemented and tested |
| Open5GS + srsRAN + RFSIM inventory validation | Implemented and offline-tested |
| Redacted immutable `5g_ansible` deployment plan | Implemented and offline-tested |
| SLICES CLI controller, login, project and experiment verification | Implemented and offline-tested; SLICES acceptance pending |
| Explicit SLICES reservation, shared allocation, node imaging and Kubernetes preparation | Enabled for explicit operator-run Linux execution; SLICES acceptance pending |
| Lock-, inventory-, authority- and SLICES-context-bound live preflight | Implemented and offline-tested; SLICES acceptance pending |
| Isolated locked-worktree deployment and srsUE/UPF path proof | Implemented and offline-tested; operator execution pending |
| Cooja sensors and MQTT bridge | Planned after network-path acceptance |
| Dataset collection and path-proof report | Planned for later implementation milestones |
| A1/E2, RIC and generative intelligence | Deliberately deferred |

The supported live controller is the Linux SLICES Webshell, or an SSH session to that documented management host, with the `synthran` Conda environment active. SynthRAN verifies but never changes the SLICES login, selected project, or existing experiment. Resource preparation, network deployment, and experiment execution remain separate operator actions; no experiment command reserves nodes or silently deploys the network.

## Quick start

On Linux, create the complete environment and verify the repository:

```sh
conda env create --file environment.yml
conda activate synthran
python -c "import os; assert os.environ.get('CONDA_DEFAULT_ENV') == 'synthran'"
python -m unittest discover -s tests -v
```

Preview immutable dependency synchronization:

```sh
python -m synthran deps sync --dry-run
```

After synchronizing dependencies, validate a golden-path inventory without contacting SLICES:

```sh
python -m synthran doctor \
  --offline --inventory /path/to/hosts.ini
```

Generate the non-executing deployment plan:

```sh
python -m synthran network deploy \
  --dry-run --inventory /path/to/hosts.ini
```
On the SLICES controller, verify the active CLI context without changing it:

```sh
python -m synthran slices doctor \
  --slices-project PROJECT \
  --slices-experiment EXPERIMENT
```

The operator performs `slices auth login`, `slices project use PROJECT`, and experiment creation when needed. SynthRAN only performs read-only `show` checks.

On a SLICES controller, preview preparation of the default `sopnode-f2` core and `sopnode-f3` RAN pair:

```sh
python -m synthran network prepare \
  --dry-run --owner OPERATOR --run-id network-001
```

The non-executing preview reports `Bootstrap: READY` after the recorded operator acceptance. Remove `--dry-run` only from the verified Linux SLICES controller because live preparation may image and reset the selected nodes. Read the exact controller and safety boundary in the [operator guide](docs/operator-guide.md). The test fixture is not a real deployment inventory.

## Planned experiment output

Every experiment will produce a run-scoped evidence bundle containing:

- the validated scenario and a redacted manifest;
- exact dependency commits and container digests;
- append-only sensor messages in JSONL;
- Parquet derived reproducibly from the JSONL record;
- rejected-message and sequence-integrity reports;
- network metrics and route proof;
- a UE-tunnel packet capture retained locally by default;
- broker, Cooja, srsUE, gNB, and deployment logs;
- a final reproducibility and validation report.

The target baseline is 10 sensors publishing every 5 seconds for 600 seconds: 1,200 expected measurements after warm-up. At least 99% must arrive, and every loss, duplicate, malformed event, or sequence gap must be reported.

## Repository map

```text
synthran/                 CLI, validation, adapters and orchestration
contracts/                Versioned preparation, readiness, deployment and evidence schemas
deploy/                   SynthRAN-owned preparation and narrow deployment overlays
tests/                    Offline unit tests and sanitized fixtures
docs/                     Architecture, development, security and operator guides
dependencies.lock.yml     Immutable upstream and direct dependency record
environment.yml           Complete Linux Conda environment, including Ansible
THIRD_PARTY.md            License and provenance record
AGENTS.md                 Durable repository working contract
```

The current contracts cover resource preparation, golden-path readiness, deployment, and network evidence. Scenario and event contracts arrive with their implementation milestones. Upstream source remains outside this tree.

## Roadmap

| Milestone | Outcome |
|---|---|
| `v0.0.1` | Repository foundation, dependency lock, privacy controls and CI |
| `v0.0.2` | SLICES/`5g_ansible` adapter and verified srsUE tunnel |
| `v0.0.3` | Deterministic Contiki-NG/Cooja MQTT workload |
| `v0.0.4` | Edge-to-central Mosquitto bridge over the UE path |
| `v0.0.5` | JSONL/Parquet collector, integrity validation and path proof |
| `v0.1.0` | Reproducible one-command experiment lifecycle |
| `v0.2+` | Multi-UE/slice experiments, impairments, synthesis and later RIC adapters |

Formal O-RAN A1/E2 control and generative models are not shortcuts around the baseline. They begin only after the measured data path is reproducible and independently provable.

## Documentation

- [Architecture and responsibility boundaries](docs/architecture.md)
- [Operator guide and safety gates](docs/operator-guide.md)
- [Development environment and tests](docs/development.md)
- [Dependency reuse and update policy](docs/dependencies.md)
- [Security, privacy and artifact handling](docs/security.md)
- [Third-party provenance](THIRD_PARTY.md)

## License

Original SynthRAN code is licensed under the [Apache License 2.0](LICENSE). External dependencies retain their own licenses and are not relicensed by this repository.
