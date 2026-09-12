# Ambient-IoT examples

These examples exercise SynthRAN's native Ambient-IoT model through reusable,
scenario-driven runs.

```sh
python -m Experiment.cli model run --config Experiment/ambient_iot/examples/broadcast.yml --output results/broadcast/model
python -m Experiment.cli model run --config Experiment/ambient_iot/examples/broadcast_sic.yml --output results/broadcast-sic/model
python -m Experiment.cli model run --config Experiment/ambient_iot/examples/unicast.yml --output results/unicast/model
python -m Experiment.cli model run --config Experiment/ambient_iot/examples/adaptive_aloha.yml --output results/adaptive/model
```

The protocol implementations are reusable from `Experiment.ambient_iot.protocols`.
Each run emits native Ambient-IoT evidence plus the decoded `events.jsonl` trace.
