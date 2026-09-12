# Testbed scenario catalog

These files describe **testbed infrastructure only**: core, RAN, radio/platform,
SOP-node placement, UE selection, network profile, explicit UE-to-slice
assignment, and reservation defaults. They do not currently select or run a
scientific experiment.

They are editable presets, not standing reservations or evidence that every
combination has passed a physical run.

| Scenario | Core / RAN / radio | UE selection |
|---|---|---|
| `rfsim-sidecars-3ue.yml` | Open5GS / srsRAN / RFSIM | Three software UEs |
| `r2lab-reference-oai-srsran.yml` | OAI / srsRAN / N320 | Two QHATs |
| `r2lab-n300-qhats-sdr.yml` | Open5GS / srsRAN / N300 | Three QHATs |
| `r2lab-n320-mixed-ues-dual-sdr.yml` | Free5GC / srsRAN / N320 | QHAT and QFIT modems |

Historical `sdr` filenames are retained for existing commands. They do not
provision auxiliary sensor, edge, or SDR-measurement hosts.

Bare deployment is interactive and does not depend on a reference scenario:

```sh
./deploy.sh
```

An explicit preset can be deployed non-interactively or used as the defaults
for the interactive wizard:

```sh
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml --no-input
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml --interactive
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml --dry-run
```

The interactive wizard first lists UEs dynamically from
`deployment/group_vars/all/ue_catalog.yaml`, filtered by the selected platform.
It then discovers network profiles from
`deployment/group_vars/all/network_profile_*.yaml`. After a profile is selected,
each chosen UE is explicitly assigned to one of that profile's slices.

`--no-reservation` skips POS/R2Lab booking while the normal infrastructure
setup still runs. `--dry-run` resolves the testbed configuration and rendered
inventory without provisioning hardware.

Scientific experiment orchestration is under active construction. Until that
integration is ready, scenarios remain infrastructure-only and `deploy.sh`
stops at an accepted testbed. The intended public workflow is to expose the
experiment layer through the same repository entry point rather than require
normal users to invoke internal `synthran.cli` commands directly.

R2Lab physical deployment currently supports the N300 and N320 networked USRP
paths. Radio power, N3xx handling, gNB deployment, and modem bring-up remain
integrated with the retained upstream-derived hardware logic. See the
[root README](../README.md) for SSH, host tuning, reservation, project-status,
and experiment-boundary guidance.
