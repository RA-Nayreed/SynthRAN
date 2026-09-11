# SynthRAN

SynthRAN prepares a 5G testbed and runs a configured experiment on it. Testbed
code lives in `deployment/` and `synthran/`. Campaigns, scientific models, MQTT
replay, collection and analysis live in `Experiment/`.

For R2Lab, the hardware roles listed in
[`SOURCE.json`](third_party/sopnode-5g-ansible/SOURCE.json) are byte-identical to
`sopnode/5g_ansible` revision `a0149fc0dde39e2872945a0f3c91e804ece52d4f`.
They own radio power/configuration, N3xx IP swapping, gNB deployment and modem
setup/connection. SynthRAN supplies inventory, selected profiles, reservations
and orchestration. This is a pinned upstream hardware implementation with a
SynthRAN adapter; it does not establish that every deployment combination has
been physically qualified.

## Run

```sh
./deploy.sh
./deploy.sh --config scenarios/reference.yml --dry-run
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml --testbed-only
```

Without an explicit configuration, the launcher prompts for deployment choices.
Use `--interactive` with `--config` to edit its defaults, or `--no-input` to use
the reference configuration without prompts. Host prompts accept names; they do
not discover live availability. POS checks reservation conflicts during a real
run. The source configuration is never overwritten.

A dry run prepares the inventory and selected experiment locally and skips
reservations and remote deployment. `--testbed-only` omits the experiment from
the resolved configuration, so it generates no model, MQTT service or replay.
The launcher creates `.venv` and caches dependency preparation until the runtime
or package requirements change.

A full deployment prepares the selected nodes and rebuilds their 5G stack.
Keeping an existing POS reservation preserves the image on nodes with an active
allocation. Use `--no-reservation` when resources are already reserved, allocated,
imaged and reachable; it does not skip infrastructure setup.

## Configuration and ownership

A testbed scenario selects an experiment through explicit paths, resolved
relative to the scenario file:

```yaml
deployment:
  # Core, RAN, platform, nodes, UEs, profile and reservation settings.
experiment:
  entrypoint: ../Experiment/runner.py
  config: ../Experiment/configs/reference.yml
```

The testbed invokes the Python entrypoint with `prepare`, `run` and `finalize`,
passing `--config` and `--run-dir`. Interactive edits also invoke `configure`
with `--source-config`. Preparation can receive `--prepared-workload` or
`--resume-from`. The entrypoint owns these operations and their artifacts.
Omit `experiment` to use infrastructure alone.

The supplied Ambient-IoT experiment freezes decoded model packets into an
immutable bundle, then replays them over real UE interfaces. Its configuration
contains `model`, `mqtt` and `devices`. Each modeled sensor maps to a selected
UE through `gateway`; several sensors can share one UE, and a competing-traffic
UE can have no modeled sensors. Model-only campaign configurations use logical
`gateways` without inventing a deployment.

Infrastructure choices remain explicit data:

- `deployment.profile` selects a bundled 5G profile; `profile_file` and
  `topology_file` accept alternative files relative to the scenario.
- `deployment.ue_profiles` overrides selected subscriber settings. Additional
  srsRAN RFSIM names such as `uesim04` can derive an IMSI and use the first slice;
  physical UEs must be defined in the selected profile or overrides.
- `deployment.host_vars.<host>` accepts connection and hardware settings, such
  as `ansible_host`, `ip`, `cpu_low_latency` and `netplan_config_file` (an absolute
  controller path). Bundled Netplan files describe the named SOP hosts' actual
  NICs. Supply the appropriate file for different hardware.
- `deployment.reservation.node_pool` lists acceptable alternative POS hosts in
  preference order. Selected nodes are included automatically; absent a pool,
  only the selected nodes are considered. CPU tuning is selected by host
  configuration, with no hostname-specific branch or hyperthreading blocker.
- `deployment.ansible_vars` passes additional upstream feature options. Core,
  RAN, profile and generated execution context come from the scenario.
- `deployment.r2lab_ssh` accepts `host`, `username` and `identity_file`.
  `R2LAB_USERNAME` and `R2LAB_IDENTITY_FILE` can override the latter two.
  `.r2lab_config` is loaded before inventory generation; normal SSH configuration
  and agent identities apply when no key is selected. Upstream's inventory name
  remains `faraday.inria.fr`, while its actual address is configurable.

R2Lab reservation uses `R2LAB_EMAIL`, `R2LAB_PASSWORD` and the selected username.
Benetel bring-up requires the upstream preparation scripts/configuration on
Faraday and appropriate host networking; the example files do not certify those
prerequisites. The retained `deployment/ru_profiles/benetel/` directory contains
upstream installation assets for that separate host preparation.

See the [scenario catalog](scenarios/README.md) for editable combinations.

## Repeat and resume

```sh
./deploy.sh --config scenarios/reference.yml \
  --workload-only --prepared-workload results/permuted/model
./deploy.sh --resume results/<failed-run-id>
```

Workload-only execution checks the saved and live deployment identity before
reusing the stack. Resume uses the failed run's resolved configuration and
original event bundle, checks its attestation evidence and verifies the live
cluster identity. Identity covers the effective core/RAN, nodes, host settings,
profiles, slices, UEs and topology. These checks detect incompatible reuse; they
do not attest physical radio quality or clock synchronization.

UE setup and connection belong to testbed bring-up. Workload-only and resume
leave existing sessions in place. A testbed is marked active after successful
bring-up, before the selected experiment runs, allowing an experiment failure
to be resumed without rebuilding the network.

## Logs and results

Terminal progress is nested by play, role, task and host, with skipped noise
suppressed and failures retained. Each run keeps complete `ansible.log`,
`deployment.log`, `controller.pid`, `controller-exit-code` and
`source-revision.txt` alongside its resolved configuration.

Once the deployment controller starts, it continues if the terminal disconnects.
Ctrl+C cancels the controller and its experiment/Ansible descendants. Earlier
interactive configuration, reservation and dependency steps need a connected
terminal. Following a saved log only observes the run.

For the supplied experiment, `model/` contains the frozen source, and publisher,
receiving-application and `summary.json` records contain transport evidence.
Command success means execution completed; inspect delivery and measurement
validity separately. Software UE publishers run in their UE pod's network
namespace; R2Lab publishers use the upstream-established `wwan0` session.

The Ambient-IoT model's Amber provenance is retained under `third_party/amber/`.
See [experiment readiness](docs/experiment-readiness.md) for scientific semantics,
measurement limits and the physical qualification still required. No test files
are retained in this repository.
