# Experiment scenario catalog

These scenarios exercise distinct parts of the supported deployment matrix. Node
availability and RF authorization must be checked immediately before running;
the files describe requested resources, not a standing reservation.

| Scenario | 5G system | UE path | Additional R2Lab resources |
|---|---|---|---|
| `rfsim-sidecars-3ue.yml` | Open5GS + srsRAN RF simulator | Three software UE tunnels, each with an injected publisher sidecar | None |
| `r2lab-n300-qhats-sdr.yml` | Open5GS + srsRAN + N300 | Three physical QHAT UEs on `wwan0` | FIT sensor and edge nodes; `pc01` USRP measurement node |
| `r2lab-n320-mixed-ues-dual-sdr.yml` | Free5GC + srsRAN + N320 | QMI QHATs plus MBIM QFITs | Two sensors, one edge node, and both documented miniPC USRPs |
| `r2lab-benetel1-oai.yml` | Open5GS + OAI RAN + Benetel 1 | Two physical QHAT UEs | Sensor, edge, and `pc02` RF measurement |
| `r2lab-benetel2-sliced.yml` | Open5GS + srsRAN + Benetel 2 | Two physical UEs on different `scenario1` slices | Two sensors, edge, and `pc01` RF measurement |

Run a selected scenario non-interactively:

```sh
./deploy.sh --config scenarios/r2lab-n300-qhats-sdr.yml --no-input
```

Set `R2LAB_USERNAME`, or create `.r2lab_config` through the interactive launcher,
before using an R2Lab scenario. Remove `--no-input` when you want the launcher to
select currently available resources. Use `--no-reservation` only when every SOP
and R2Lab resource in the file is already reserved, imaged, and reachable.

Software UE sidecars apply only to RF-simulated UEs. Physical R2Lab QHAT/QFIT
workloads run directly on their hosts and bind MQTT to `wwan0`. Extra sensor,
edge, and RF-measurement nodes receive the frozen Ambient-IoT event trace and collect
host/SDR evidence, but they do not automatically gain a routed 5G user-plane.

`pc01` and `pc02` are used for RF measurement because the deployment roles have
explicit USRP power and validation support for those miniPCs. A FIT node should
only be assigned to `rf_measurement` after confirming that its current R2Lab
hardware entry includes an SDR.
