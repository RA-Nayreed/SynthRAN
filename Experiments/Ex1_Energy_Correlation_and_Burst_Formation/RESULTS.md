# Experiment 1 — retained completed results

This file records the retained results from the completed historical **Energy Correlation and Burst Formation** campaign. Raw run bundles are stored under the repository-local path `results/exp1-energy-correlation/`; the top-level `.gitignore` excludes `/results/`, so those raw directories are not tracked in GitHub.

Reproducibility assets in this directory are:

- `experiment-plan.json` — frozen campaign definition and integrity record;
- `run_experiment.py` — reconstructs the power calibration, population calibration, and 7-arm × 30-seed confirmation campaign while refusing to overwrite immutable bundles;
- `analyze.py` — retained-campaign analysis entry point.

The original execution wrapper used for the historical campaign is not part of the retained repository state. Reproduction therefore uses the frozen experiment record together with the current SynthRAN model contract, while preserving the historical run-directory identities consumed by downstream work, including `knee-common-seed1001`.

## Calibration

Calibration used 8 modeled sensors, 60-second runs, 1-second sensing, lognormal harvested-power CV 1, a 0.1-second source interval, a 5-second correlation time, independent harvesting, and pilot seeds 1–5.

| Mean harvested power | Active fraction | Generated | Transmitted | Decoded | Collisions | Suppressed |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 250 µW | 3.8% | 18.0 | 17.0 | 14.8 | 0.0 | 462.0 |
| 500 µW | 19.5% | 93.4 | 89.2 | 78.2 | 1.4 | 386.6 |
| 1000 µW | 50.3% | 241.6 | 236.0 | 216.4 | 5.2 | 238.4 |
| 2000 µW | 79.2% | 380.0 | 377.6 | 354.0 | 11.0 | 100.0 |
| 4000 µW | 93.5% | 448.6 | 447.6 | 425.4 | 17.6 | 31.4 |

The population calibration selected `N*=32` for confirmation.

## Confirmation

The confirmation campaign used 7 conditions × 30 independent seeds (`1001–1030`) = **210 model runs**. Integrity checks passed for **210/210** runs.

| Condition | Active fraction | Realized power correlation | Decode rate /s | Fano factor | Gap CV | Collision rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Always powered | 100.0% | — | 26.841 | 0.255 | 0.854 | 15.93% |
| Low, independent | 16.5% | -0.001 | 4.720 | 0.759 | 0.925 | 2.54% |
| Low, common | 17.6% | 0.967 | 4.387 | 18.630 | 6.446 | 14.47% |
| Knee, independent | 45.4% | 0.001 | 12.628 | 0.584 | 0.922 | 7.30% |
| Knee, common | 44.5% | 0.961 | 11.294 | 13.391 | 6.508 | 15.33% |
| High, independent | 76.9% | 0.002 | 20.941 | 0.363 | 0.886 | 12.07% |
| High, common | 74.4% | 0.943 | 19.489 | 6.568 | 4.488 | 15.15% |

`low-common-seed1028` is a valid zero-event blackout and is retained. It is one silent run out of 30; conditional event-process metrics for that arm therefore use `n=29` where applicable.

## Supported result

The retained campaign supports the mechanism:

**common energy harvesting → synchronized activation → much burstier decoded traffic → higher collision exposure.**

The reader-side AoI common-minus-independent confidence intervals crossed zero, so this campaign does **not** establish reader-freshness degradation. That downstream transport question is addressed separately by Experiment 2.

## Evidence boundary

These are historical retained aggregates from the completed campaign. They remain valid as evidence about that campaign, but they are not a substitute for recalibration after a material implementation or scientific-design change.

Expected local raw-artifact root:

```text
results/exp1-energy-correlation/
```

Those bundles are source data for Experiment 2. They should not be regenerated or replaced merely to make raw result directories tracked by Git.
