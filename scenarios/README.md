# Testbed scenario catalog

These files describe requested infrastructure and select separate configurations
under `Experiment/configs/`. They are editable examples, not standing
reservations or evidence that every combination has passed a physical run.

| Scenario | Core / RAN / radio | UE selection |
|---|---|---|
| `reference.yml` | Open5GS / srsRAN / RFSIM | Two software UEs |
| `rfsim-sidecars-3ue.yml` | Open5GS / srsRAN / RFSIM | Three software UEs |
| `r2lab-reference-oai-srsran.yml` | OAI / srsRAN / N320 | Two QHATs |
| `r2lab-n300-qhats-sdr.yml` | Open5GS / srsRAN / N300 | Three QHATs |
| `r2lab-n320-mixed-ues-dual-sdr.yml` | Free5GC / srsRAN / N320 | QHAT and QFIT modems |
| `r2lab-benetel1-oai.yml` | Open5GS / OAI / Benetel 1 | Two QHATs |
| `r2lab-benetel2-sliced.yml` | Open5GS / srsRAN / Benetel 2 | Physical UEs on separate slices |

Historical `sdr` filenames are retained for existing commands. They do not
provision auxiliary sensor, edge or SDR measurement hosts. A campaign requiring
additional measurements must implement them under `Experiment/`.

```sh
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml --dry-run
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml --interactive
./deploy.sh --config scenarios/r2lab-reference-oai-srsran.yml --testbed-only
```

Interactive prompts edit the loaded defaults; they do not discover live resource
availability. Confirm the requested POS/R2Lab reservation and hardware access
before a real run. `--no-reservation` skips booking, while normal infrastructure
setup still runs. Use `--workload-only` to reuse a healthy matching deployment.

Change testbed hosts, profiles, UEs and connection details under `deployment`.
Change modeled sensor populations, gateway mapping, traffic and scientific
settings in the selected `Experiment/configs/` file. Paths in `experiment` are
relative to the testbed scenario. Node names and radio choices in these examples
are configuration data, not enforced choices.

R2Lab delegates modem and radio bring-up to the pinned upstream roles. Benetel
requires preinstalled Faraday preparation scripts and the appropriate NIC/VLAN
and radio setup; local rendering does not qualify that hardware path. See the
[root README](../README.md) for SSH, host tuning and reservation pool options.
