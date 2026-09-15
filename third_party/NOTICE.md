# Third-party notices

This directory records provenance and licensing information for upstream work retained or adapted by SynthRAN.

## Amber-derived Ambient-IoT model

Parts of `synthran/model/` originate from the Amber 6G Ambient-IoT simulator by Mirana Manafova and are maintained in modified form inside SynthRAN.

The pinned source revision and import history are recorded in [`amber/SOURCE.json`](amber/SOURCE.json). The upstream BSD 3-Clause license is preserved in [`amber/LICENSE`](amber/LICENSE).

## SOPNode 5G Ansible deployment stack

Substantial portions of `deployment/` derive from [`sopnode/5g_ansible`](https://github.com/sopnode/5g_ansible), developed at Inria Sophia Antipolis (SophiaNode / R2Lab, SLICES-RI), and itself based on `yassir63/5g_ansible`. The comparison reference and SynthRAN modification record are retained in [`sopnode-5g-ansible/SOURCE.json`](sopnode-5g-ansible/SOURCE.json).

The pinned SynthRAN comparison revision predates the upstream repository's explicit repository-level license declaration. The upstream maintainers subsequently clarified that `sopnode/5g_ansible` is licensed under the **Apache License 2.0** and added that license to the upstream repository. SynthRAN therefore records Apache-2.0 as the license for the reused deployment material while preserving the historical pinned revision and modification ledger.

Upstream reference publication:

> Y. Amami, Z. Mabrouk, C. Barakat, T. Turletti, “Toward Real-Time RAN Observability in Open-Source 5G Systems,” 29th Conference on Innovation in Clouds, Internet and Networks (ICIN 2026), Athens, Greece, Mar. 2026. DOI: 10.1109/ICIN69025.2026.11481836.

## Repository license

The root [`LICENSE`](../LICENSE) applies to SynthRAN-original material according to its stated terms. Component-specific upstream copyright, attribution, licensing terms and provenance remain authoritative for retained or derived third-party material.
