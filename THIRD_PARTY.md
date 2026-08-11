# Third-Party Dependencies

SynthRAN original code is licensed under Apache-2.0. External projects remain separate dependencies and are not relicensed by this repository.

The immutable identifiers below mirror `dependencies.lock.yml`. The lock file is the machine-readable source of truth.

| Dependency | Purpose | Locked version | Reuse | License status |
|---|---|---|---|---|
| `sopnode/5g_ansible` | SLICES 5G deployment | `a0149fc0dde39e2872945a0f3c91e804ece52d4f` | External detached checkout | No top-level license found in the reviewed tree; do not copy or publish derivative source without clarification |
| `contiki-ng/contiki-ng` | Firmware, RPL/6LoWPAN, Cooja | release 5.1 at `2b87baf3ebdde3c8e37ca791d2bc84bfd76c49a4` | External detached checkout and out-of-tree application | BSD-3-Clause unless a source file states otherwise |
| `sopnode/open5gs-k8s` | Transitive Open5GS Kubernetes deployment | `e53601e5209425867413d45d3d01ed9a1b696de7` | Referenced through the `5g_ansible` adapter | MIT license present in the pinned tree |
| `turletti/srsran-helm` | Transitive srsRAN Helm deployment | `8dfb9890d127734cdcd6eee9df8c5d09b1a8076a` | Referenced through the `5g_ansible` adapter | License not yet asserted; inspect before copying or modifying upstream source |
| `eclipse-mosquitto` | Edge and central MQTT brokers | `2.1.2-alpine@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797` | Container image | EPL-2.0 OR EDL-1.0; retain image notices |
| Miniforge3 | Conda distribution used by CI and recommended locally | `26.3.2-2`, Linux x86-64 installer `sha256:42260ffe3830fb953d5eee1bbb32229ff06aa7c3833c1ed7a9a0420a95685d94` | External environment bootstrap | Installer code is BSD-3-Clause; installed packages retain their own licenses |
| Python | SynthRAN runtime | `3.12.11` | Conda package from `conda-forge` | PSF-2.0 |
| Git | Detached dependency synchronization and repository hooks | `2.51.0` | Conda package from `conda-forge` | GPL-2.0-only |
| Eclipse Paho MQTT Python | Collector MQTT client | `2.1.0` | Conda package from `conda-forge` | EPL-2.0 OR EDL-1.0 |
| Apache PyArrow | Parquet conversion | `21.0.0` | Conda package from `conda-forge` | Apache-2.0 |
| PyPA Setuptools | Python build backend | `83.0.0` | Conda package from `conda-forge` | MIT |
| `actions/checkout` | CI repository checkout | commit `d23441a48e516b6c34aea4fa41551a30e30af803` | GitHub Action | MIT |
| `conda-incubator/setup-miniconda` | CI Conda/Miniforge environment bootstrap | v4 at commit `8ee1f361103df19b6f8c8655fd3967a8ecb162d5` | GitHub Action | MIT |
| `gitleaks/gitleaks-action` | CI secret scanning | commit `e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e` | GitHub Action | MIT |

## Maintenance rules

1. Resolve mutable tags or branches to immutable commits or image digests before use.
2. Change only one dependency at a time.
3. Record the source ref, resolved identifier, date, license review, and compatibility result.
4. Preserve all upstream notices when an upstream artifact is redistributed.
5. Do not copy from a dependency whose redistribution terms are unclear.
6. Regenerate the SBOM when distributable images or packages are introduced.

`environment.yml` and the Conda section of `dependencies.lock.yml` lock direct package versions only. Conda resolves transitive packages and platform builds when the environment is created. Platform-specific artifact lock files must be generated and reviewed before an environment is described as fully reproducible.

This file is provenance documentation, not legal advice. Unasserted license status is a release blocker for copied or redistributed upstream material, not for merely linking to a separately obtained repository.
