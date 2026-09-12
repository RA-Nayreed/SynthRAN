# SynthRAN

SynthRAN provisions and verifies reusable 5G testbeds. Testbed orchestration lives
in `deploy.sh`, `deployment/`, and the deployment-facing parts of `synthran/`.
Scientific campaigns live under `Experiment/` and are intentionally **not** run
by `deploy.sh`.

For R2Lab, the hardware roles listed in
[`SOURCE.json`](third_party/sopnode-5g-ansible/SOURCE.json) are pinned from the
`sopnode/5g_ansible` implementation. They own radio power/configuration, N3xx
IP swapping, gNB deployment, and modem setup/connection. SynthRAN supplies the
inventory, selected 5G profile, reservations, deployment orchestration, and live
deployment attestation.

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

The interactive wizard asks for the core, RAN, platform/radio, SOP nodes,
reservation settings, 5G profile, and UE set. 5G profiles are discovered at
runtime from:

```text
deployment/group_vars/all/5g_profile_*.yaml
```

They are presented as numbered choices. For R2Lab, physical QHAT/QFIT UE choices
are then read from the selected profile rather than from a duplicated hard-coded
list in the launcher.

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
  profile: default
  nodes:
    core: sopnode-f2
    ran: sopnode-f3
    broker: sopnode-f2
  ues:
    - qhat01
  reservation:
    enabled: true
    duration_minutes: 120
    image: ubuntu-jammy
  r2lab_reservation:
    enabled: true
    duration_minutes: 120
```

Important deployment surfaces include:

- `deployment.profile`: selects a bundled 5G profile.
- `deployment.ues`: selected software or physical UEs.
- `deployment.ue_profiles`: optional subscriber overrides.
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
