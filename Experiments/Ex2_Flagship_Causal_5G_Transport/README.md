# Experiment 2 — Causal 5G transport

This directory contains the executable Experiment-2 campaign. `experiment-plan.json`
is the frozen machine-readable design authority. The longer research brief remains
background rationale; where an old planning number or pilot description conflicts
with `experiment-plan.json`, the JSON plan and the current runner are authoritative.

## Primary design

The primary physical confirmation uses all 30 frozen `knee-common` source seeds from
the completed Experiment-1 campaign. Every source is crossed with:

- four matched timing arms: native, two independently seeded gap permutations, periodic;
- three formally calibrated competing-load levels: below, near, above.

That is **30 × 4 × 3 = 360 physical transport replays**. The 30 source seeds are the
independent experimental units. The two gap permutations are repeated controls, not
extra independent samples.

This deliberately replaces the older 3 source-arm × 10 seed planning matrix. It keeps
the same 360 replay budget while tripling independent replication for the causal timing
question and avoids mixing changes in upstream event volume with the timing intervention.

## Site split

Preparation is local/model-only and can run on Roihu. It emits compact transport
bundles rather than copying the full Experiment-1 campaign to Duckburg.

```bash
python -m Experiments.Ex2_Flagship_Causal_5G_Transport.prepare_experiment \
  --experiment1-campaign /path/to/ex1/20260913T185453409916Z \
  --transport r2lab \
  --output /path/to/ex2-prepared-r2lab
```

Copy that prepared directory to Duckburg with `rsync`. No tarball is required.

Build the fixed transport scenario on Duckburg:

```bash
python -m Experiments.Ex2_Flagship_Causal_5G_Transport.build_transport_scenario \
  --prepared-root /path/to/ex2-prepared-r2lab \
  --transport r2lab \
  --output /path/to/ex2-transport-config
```

Provision and accept the testbed separately with `deploy.sh`. Experiment code only
attaches read-only to that accepted deployment; it does not reserve, repair, rebuild,
or power-cycle infrastructure.

Then execute confirmation sessions against the accepted deployment:

```bash
python -m Experiments.Ex2_Flagship_Causal_5G_Transport.run_experiment \
  --prepared-root /path/to/ex2-prepared-r2lab \
  --transport r2lab \
  --transport-config /path/to/ex2-transport-config/transport.yml \
  --session 1 \
  --clock-uncertainty-seconds <measured-bound>
```

Repeat with sessions 2 and 3. The active Ex2 campaign is reused automatically. On the
third completed session the runner performs the prespecified paired analysis.

`--session all` is available when one accepted deployment/reservation can safely cover
the entire campaign.

## S3 is opt-in and post-run

Scientific execution does not require S3. There is no experiment-manifest bucket,
alias, or project prefix. To archive a completed result later:

```bash
python -m synthran.archive_cli /path/to/result \
  --alias <mc-alias> \
  --bucket <bucket> \
  --prefix <prefix>
```

The archive helper uses immutable per-file SHA-256 verification and refuses to overwrite
different remote content. This makes Roihu → Duckburg → S3 a normal workflow without
changing the scientific result or rerunning an experiment.
