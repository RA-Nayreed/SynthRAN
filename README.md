# SynthRAN

SynthRAN provisions and verifies reusable 5G testbeds. Testbed orchestration lives
in `deploy.sh`, `deployment/`, and the deployment-facing parts of `synthran/`.
Scientific campaigns live under `Experiment/` and are intentionally **not** run
by `deploy.sh`.

For R2Lab, the hardware files listed in
[`SOURCE.json`](third_party/sopnode-5g-ansible/SOURCE.json) remain pinned from the
`sopnode/5g_ansible` implementation where exact upstream parity is useful.
SynthRAN narrows the physical-radio deployment contract to the N300 and N320
networked USRP paths and supplies inventory, the reusable UE catalog, network
profiles, reservations, deployment orchestration, radio/gNB integration, and
live deployment attestation.

## Deploy a testbed

Bare deployment opens the interactive wizard:

```sh
./deploy.sh
```

An explicit testbed preset can be used directly or as interactive defaults:

```sh
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml --no-input
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml --interactive
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml --dry-run
```

`deploy.sh` owns only testbed deployment. It does not configure, prepare, run,
clean up, or finalize an experiment. If a legacy configuration still contains
an `experiment:` block, the launcher strips it before deployment resolution.

The interactive wizard asks for the core, RAN, platform/radio, SOP nodes and UE
set. UE identities are discovered from the platform-independent catalog:

```text
deployment/group_vars/all/ue_catalog.yaml
```

The selected platform filters that catalog to the usable RFSIM or R2Lab UEs.
The wizard then discovers network profiles at runtime from:

```text
deployment/group_vars/all/network_profile_*.yaml
```

A network profile owns PLMN, DNN, slice, QoS, and subscriber-security policy.
Each selected UE is explicitly assigned to one slice exposed by the selected
network profile. UE identity/transport therefore remains independent from
network policy. The supported R2Lab radio choices are `n300` and `n320`.

`--no-reservation` skips POS/R2Lab booking while normal infrastructure setup
still runs. `--dry-run` resolves the testbed configuration and rendered inventory
without provisioning hardware. The launcher creates `.venv` and prepares the
isolated deployment runtime when needed.

## Testbed configuration

A scenario under `scenarios/` contains infrastructure only:

```yaml
deployment:
  core: open5gs
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

Important deployment surfaces include:

- `deployment.network_profile`: selects a bundled network policy.
- `deployment.ues`: selects UE identities from `ue_catalog.yaml`.
- `deployment.ue_slices`: explicitly assigns every selected UE to a slice in the selected network profile.
- `deployment.host_vars.<host>`: connection/hardware settings such as
  `ansible_host`, `ip`, `cpu_low_latency`, and `netplan_config_file`.
- `deployment.reservation`: SOP-node reservation policy.
- `deployment.ansible_vars`: additional upstream deployment options.
- `deployment.r2lab_ssh`: R2Lab host, username, and identity settings.

`R2LAB_USERNAME` and `R2LAB_IDENTITY_FILE` may override R2Lab connection values.
`.r2lab_config` is loaded before inventory generation. The upstream inventory
identity remains `faraday.inria.fr`.

The legacy global `r2lab_experiment_nodes` capability is disabled. Current
Ambient-IoT sensors are logical scientific entities, not arbitrary FIT/PC hosts.
If a future experiment genuinely requires additional R2Lab compute or
measurement nodes, that requirement belongs in that experiment's explicit
resource contract rather than in the generic deployment launcher.

See the [scenario catalog](scenarios/README.md) for editable testbed presets.

## Deployment acceptance

A successful run performs provisioning, UE/session verification, runtime
provenance, and fresh live deployment attestation. Only after that evidence is
accepted is the deployment written as the active deployment identity under
`.synthran/`.

This active, attested testbed is the boundary that a separate experiment launcher
will use. The experiment launcher will be designed independently so scientific
experiments can select an accepted deployment without making `deploy.sh` own
experiment logic again.

## Logs and results

Terminal progress is nested by play, role, task, and host, with skipped noise
suppressed and failures retained. Each deployment run keeps complete
`ansible.log`, `deployment.log`, `controller.pid`, `controller-exit-code`,
`source-revision.txt`, its resolved scenario, deployment fingerprint, and live
deployment evidence under `results/<run-id>/`.

Once the deployment controller starts, it continues if the terminal disconnects.
Ctrl+C cancels the deployment controller and Ansible descendants. Interactive
configuration, reservation, and dependency preparation occur before that
background controller starts.

The Ambient-IoT model's Amber provenance is retained under `third_party/amber/`.
Scientific campaign documentation and results remain under `Experiment/`.
