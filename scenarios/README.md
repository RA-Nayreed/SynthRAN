# Testbed scenario catalog

These files describe **testbed infrastructure only**: core, RAN, radio/platform,
SOP-node placement, 5G profile, UE selection, and reservation defaults. They do
not select or run a scientific experiment.

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

The interactive wizard discovers 5G profiles from
`deployment/group_vars/all/5g_profile_*.yaml` and lists them as numbered
choices. Physical R2Lab UEs are then listed from the selected profile.

`--no-reservation` skips POS/R2Lab booking while the normal infrastructure
setup still runs. `--dry-run` resolves the testbed configuration and rendered
inventory without provisioning hardware.

Scientific experiments are intentionally outside this launcher. A separate
experiment runner will attach to an already accepted SynthRAN deployment and
own experiment selection, preparation, execution, cleanup, and result
finalization.

R2Lab physical deployment currently supports the N300 and N320 networked USRP
paths. Radio power, N3xx handling, gNB deployment, and modem bring-up remain
integrated with the retained upstream-derived hardware logic. See the
[root README](../README.md) for SSH, host tuning, and reservation configuration.
