# Amber examples inside SynthRAN

These examples exercise the embedded `amber/` package through SynthRAN's
reusable integration layer. They replace upstream's large, duplicated demo
scripts with scenario-driven runs.

```sh
python -m synthran.cli model run --config amber_examples/broadcast.yml --output results/broadcast/model
python -m synthran.cli model run --config amber_examples/broadcast_sic.yml --output results/broadcast-sic/model
python -m synthran.cli model run --config amber_examples/unicast.yml --output results/unicast/model
python -m synthran.cli model run --config amber_examples/adaptive_aloha.yml --output results/adaptive/model
```

The protocol implementations are reusable from `synthran.amber.protocols`.
Each run emits native Amber evidence plus the decoded `events.jsonl` trace.
