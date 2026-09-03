# Ambient-IoT examples

These examples exercise SynthRAN's native Ambient-IoT model through reusable,
scenario-driven runs.

```sh
python -m synthran.cli model run --config ambient_iot_examples/broadcast.yml --output results/broadcast/model
python -m synthran.cli model run --config ambient_iot_examples/broadcast_sic.yml --output results/broadcast-sic/model
python -m synthran.cli model run --config ambient_iot_examples/unicast.yml --output results/unicast/model
python -m synthran.cli model run --config ambient_iot_examples/adaptive_aloha.yml --output results/adaptive/model
```

The protocol implementations are reusable from `synthran.ambient_iot.protocols`.
Each run emits native Ambient-IoT evidence plus the decoded `events.jsonl` trace.
