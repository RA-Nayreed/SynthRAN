<div align="center">

# SynthRAN

**Reproducible virtual and physical 5G testbeds for research experimentation.**

`RFSIM` · `R2Lab` · `srsRAN` · `Open5GS` · `OAI` · `free5GC`

</div>

SynthRAN is a research-software platform for **configuring, provisioning, verifying, and recording programmable 5G testbeds**. It turns a testbed description into an auditable deployment: resources are selected, infrastructure is prepared, the mobile network is brought up, UEs are verified, and deployment evidence is persisted for later experiments.

The supported public entry point is deliberately simple:

```bash
./deploy.sh
```

Scientific experiment orchestration is being developed on top of accepted SynthRAN deployments. That layer lives under [`Experiment/`](Experiment/) and is **under active construction**; internal Python commands are therefore not presented here as a stable user interface.

---

## Why SynthRAN?

A 5G experiment is more than starting a core network and a gNB. A useful research run also needs to answer questions such as:

- Which exact testbed resources were used?
- Which core, RAN, radio path, UE set, and network policy were selected?
- Was the network actually usable before the experiment began?
- Can the deployment be reconstructed later?
- What evidence belongs to the run that produced a result?

SynthRAN treats those questions as part of the system rather than as manual lab notes.

```text
scenario or interactive choices
            │
            ▼
       ./deploy.sh
            │
            ├── resolve configuration
            ├── reconcile reservations
            ├── prepare hosts
            ├── deploy core / RAN / radio path
            ├── activate and verify UEs
            ├── attest the live deployment
            └── persist provenance and logs
            │
            ▼
    accepted 5G testbed
            │
            ▼
   scientific experiments
      (under construction)
```

The deployment and scientific layers are intentionally separated in the repository. `deploy.sh`, `deployment/`, and `scenarios/` own testbed infrastructure. `Experiment/` owns evolving research studies and scientific artefacts.

---

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/RA-Nayreed/SynthRAN.git
cd SynthRAN
```

### 2. Inspect the deployment interface

```bash
./deploy.sh --help
```

Bare deployment opens the interactive testbed wizard:

```bash
./deploy.sh
```

The wizard guides the user through the deployment choices available to the current platform, including network components, SOP-node placement, radio path, UE selection, network profile, slice assignment, and reservation settings.

### 3. Preview a versioned scenario

A scenario can be resolved without provisioning hardware:

```bash
./deploy.sh \
  --config scenarios/r2lab-reference-oai-srsran.yml \
  --dry-run
```

A real non-interactive deployment uses the same scenario:

```bash
./deploy.sh \
  --config scenarios/r2lab-reference-oai-srsran.yml \
  --no-input
```

Useful launcher options:

| Option | Purpose |
| --- | --- |
| `--config <file>` | Load a versioned infrastructure scenario. |
| `--interactive` | Use the supplied scenario as defaults, then open the wizard. |
| `--no-input` | Deploy an explicit scenario without the configuration wizard. |
| `--no-reservation` | Skip POS/R2Lab booking while retaining normal infrastructure setup. |
| `--dry-run` | Resolve configuration and inventory without provisioning hardware. |
| `--verbose` | Show additional deployment output. |

`--no-input` requires `--config`. `--interactive` and `--no-input` are mutually exclusive.

---

## What SynthRAN deploys

The repository currently ships the following **editable reference scenarios**:

| Scenario | Core | RAN | Radio / platform | UE selection |
| --- | --- | --- | --- | --- |
| [`rfsim-sidecars-3ue.yml`](scenarios/rfsim-sidecars-3ue.yml) | Open5GS | srsRAN | RFSIM | Three software UEs |
| [`r2lab-reference-oai-srsran.yml`](scenarios/r2lab-reference-oai-srsran.yml) | OAI | srsRAN | R2Lab / N320 | Two QHATs |
| [`r2lab-n300-qhats-sdr.yml`](scenarios/r2lab-n300-qhats-sdr.yml) | Open5GS | srsRAN | R2Lab / N300 | Three QHATs |
| [`r2lab-n320-mixed-ues-dual-sdr.yml`](scenarios/r2lab-n320-mixed-ues-dual-sdr.yml) | free5GC | srsRAN | R2Lab / N320 | QHAT and QFIT modems |

These files are **presets, not a certification matrix**. Their presence means the configuration is represented in the repository; it does not by itself claim that every combination has passed a current physical acceptance run.

R2Lab physical deployment is intentionally constrained to the N300 and N320 networked-USRP paths. Software-radio scenarios use the virtual RFSIM path.

See [`scenarios/README.md`](scenarios/README.md) for the scenario contract and current catalog.

---

## Deployment configuration

Infrastructure scenarios describe the testbed, not the scientific experiment. A typical physical scenario has this shape:

```yaml
deployment:
  core: oai
  ran: srsran
  platform: r2lab
  ru: n320
  network_profile: default

  nodes:
    core: sopnode-f2
    ran: sopnode-f3
    broker: sopnode-f2

  ues:
    - qhat01
    - qhat03

  ue_slices:
    qhat01: slice1
    qhat03: slice2

  reservation:
    enabled: true
    duration_minutes: 120
    image: ubuntu-jammy

  r2lab_reservation:
    enabled: true
    duration_minutes: 120
```

The main configuration surfaces are:

| Surface | Responsibility |
| --- | --- |
| `deployment/group_vars/all/ue_catalog.yaml` | Canonical UE identities and transport settings. |
| `deployment/group_vars/all/network_profile_*.yaml` | PLMN, DNN, slice, QoS, and subscriber-security policy. |
| `deployment.ue_slices` | Explicit UE-to-slice assignment. |
| `deployment.nodes` | Core, RAN, broker, and related placement. |
| `deployment.host_vars` | Host-specific connection and tuning values. |
| `deployment.reservation` | SOP-node reservation policy. |
| `deployment.r2lab_reservation` | Physical R2Lab reservation policy. |
| `deployment.r2lab_ssh` | R2Lab access configuration. |

Local R2Lab credentials and SSH material do **not** belong in committed scenarios. `R2LAB_USERNAME`, `R2LAB_IDENTITY_FILE`, and the local `.r2lab_config` mechanism are available for machine-specific access settings.

---

## Deployment lifecycle

A normal SynthRAN deployment follows a controlled sequence rather than a collection of unrelated scripts.

1. **Resolve** — validate the selected scenario or interactive choices and render the effective deployment configuration.
2. **Reserve** — reconcile the required SOP-node and, where applicable, R2Lab resources.
3. **Prepare** — create the isolated local runtime and prepare the selected hosts.
4. **Deploy** — configure the chosen mobile core, RAN, radio path, networking, and UE environment.
5. **Verify** — verify live deployment state and UE/session behavior rather than treating process startup as success.
6. **Attest** — record the accepted deployment identity and current evidence.
7. **Persist** — retain logs, source revision, resolved configuration, and run evidence beneath the run directory.

SynthRAN also prevents overlapping deployment controllers with a repository lock and keeps private execution state beneath `.synthran/`.

---

## Evidence and reproducibility

Each deployment is associated with a run directory under:

```text
results/<run-id>/
```

The deployment controller records material needed to understand and investigate a run, including the source revision and deployment logs. Accepted deployment identity is also persisted under `.synthran/` for the layer that consumes the testbed later.

The guiding rule is simple:

> **A deployment is not research evidence merely because the processes started.**

A result should be traceable to a specific source revision, resolved configuration, resource selection, live verification state, and resulting run artefacts.

Generated result directories and local authority/credential state should not be committed to Git.

---

## Scientific experiment layer

The scientific side of SynthRAN is currently **under construction**.

[`Experiment/`](Experiment/) contains the evolving research layer, including Ambient-IoT modelling and study material. The long-term public workflow is intended to build experiments on top of an accepted SynthRAN deployment while preserving the same provenance and evidence discipline as the testbed layer.

For now:

- `./deploy.sh` is the supported public repository entry point.
- The root README does not advertise internal `synthran.cli` commands as the experiment interface.
- Experimental modules may change while the deployment-to-experiment contract is being finalized.
- Planned or partially implemented studies are not presented as completed experimental results.

Background material currently lives in [`docs/ambient-iot.md`](docs/ambient-iot.md) and [`docs/experiment-readiness.md`](docs/experiment-readiness.md).

---

## Repository map

```text
SynthRAN/
├── deploy.sh              # supported deployment entry point
├── scenarios/             # versioned infrastructure presets
├── deployment/            # Ansible roles, playbooks, inventory and testbed logic
├── synthran/              # Python support modules used by the platform
├── Experiment/            # scientific studies and experiment work in progress
├── docs/                  # focused technical/research documentation
├── third_party/           # pinned upstream provenance and retained notices
├── THIRD_PARTY_NOTICES.md # third-party attribution and license status
├── CITATION.cff           # software citation metadata
├── CONTRIBUTING.md        # contribution and validation rules
├── SECURITY.md            # vulnerability-reporting guidance
└── LICENSE                # BSD-3-Clause text for SynthRAN-original code
```

A useful boundary for contributors is:

```text
scenarios/ + deploy.sh + deployment/  →  build and attest the testbed
Experiment/                           →  define the science
results/ + .synthran/                 →  local runtime evidence and authority state
```

---

## Project status

SynthRAN is research software under active development. The repository is currently versioned as `0.1.0`.

| Area | Current status |
| --- | --- |
| Interactive and scenario-driven deployment | Active development; public interface is `./deploy.sh`. |
| RFSIM deployment path | Implemented in the deployment framework. |
| R2Lab N300/N320 path | Implemented with explicit physical-resource handling; acceptance remains evidence-specific. |
| Deployment provenance and run evidence | Implemented and persisted per deployment run. |
| Scientific experiment orchestration | Under construction; not yet documented as a stable public interface. |
| Individual research studies | Evolving independently under `Experiment/`; no blanket completion claim is made here. |

This status distinction is intentional: **implemented**, **validated in a particular run**, and **scientifically established** are not treated as synonyms.

---

## Citation

If SynthRAN contributes to published work, cite the software version or commit used for the experiment. Machine-readable citation metadata is provided in [`CITATION.cff`](CITATION.cff).

Until versioned archival releases and a DOI are established, a citation should include at minimum:

- the repository name (`SynthRAN`),
- the exact Git commit or tagged version,
- the repository URL,
- and the access/release date appropriate to the publication.

A DOI will only be added when an actual archived release exists; the repository does not use placeholder citation identifiers.

---

## Contributing

Contributions are welcome when they preserve SynthRAN's separation of concerns, provenance, and testbed-safety rules. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md).

For bugs, include the smallest useful evidence bundle and redact credentials, private keys, tokens, subscriber secrets, and machine-specific access material.

---

## License and third-party code

SynthRAN-original code is distributed under the BSD 3-Clause License; see [`LICENSE`](LICENSE).

This repository also contains or derives from third-party work with separate provenance and licensing conditions. In particular, the Amber-derived model retains its upstream BSD terms, while the retained `sopnode/5g_ansible`-derived deployment material comes from an upstream repository that did not declare a repository-level license at the pinned comparison revision.

The root license does **not** override those third-party conditions or create permissions that the upstream authors did not grant. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) before redistributing derived material.

---

## Acknowledgements

SynthRAN builds on open research infrastructure and software from the wider mobile-networking community, including SLICES/Post5G resources, R2Lab, srsRAN, Open5GS, OAI, free5GC, UERANSIM, the SOPNode 5G Ansible work, and the Amber Ambient-IoT model.

Exact third-party provenance belongs in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and the pinned records under [`third_party/`](third_party/), rather than being inferred from this README.
