# Third-party notices

## Amber (`amber/`)

The `amber/` package is the upstream [Amber](https://github.com/RA-Nayreed/Amber)
6G Ambient-IoT discrete-event simulator by Mirana Manafova, vendored in full
and kept as close to upstream as possible. It is redistributed under the BSD
3-Clause License; the unmodified upstream license text is preserved below and
also duplicated at `third_party/amber/LICENSE`. Exact provenance (source
commit and the one local compatibility patch applied) is recorded in
`third_party/amber/SOURCE.json`.

SynthRAN's own Amber integration/orchestration code lives under
`synthran/amber/` and is SynthRAN-original, not derived from Amber.

## `synthran.model` compatibility imports

The 6G ambient-IoT simulation primitives previously copied into
`synthran.model` (`backscatter.py`, `bsengine.py`, `capacitor.py`,
`controller.py`, `packet_analysis.py`, `propagation.py`, `radiodevices.py`)
also derive from Amber and remain redistributed under the same license below.
These copies are being consolidated onto the single `amber/` copy above; see
`docs/amber-integration.md` for the integration architecture. Modules under
`synthran.model` are deprecated import shims and contain no independent Amber
implementation.

Copyright and license conditions are preserved below.

Copyright (c) 2025, Mirana Manafova

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS “AS IS”
AND ANY EXPRESS OR IMPLIED WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE.

## SOPNode 5G Ansible deployment stack (`deployment/`)

Substantial portions of `deployment/`, particularly the Ansible roles for
Kubernetes host preparation and OAI, Open5GS, free5GC, srsRAN, UERANSIM,
R2Lab, radio-unit, networking, and performance configuration, are derived from
[sopnode/5g_ansible](https://github.com/sopnode/5g_ansible). That repository is
itself a fork of
[yassir63/5g_ansible](https://github.com/yassir63/5g_ansible).

The comparison reference and modification provenance are recorded in
`third_party/sopnode-5g-ansible/SOURCE.json`. Principal upstream contributors
visible in the referenced history include Thierry Turletti, Ziyad Mabrouk, and
Samuel DeLaughter.

SynthRAN reorganized the selected upstream files beneath `deployment/`, removed
unneeded upstream components, and substantially adapted the retained roles for
scenario-driven multi-core/multi-RAN deployment. SynthRAN also added its own
network playbooks, POS and R2Lab reservation/provisioning, MQTT broker and UE
publisher roles, physical-UE handling, immutable Amber trace replay, evidence
collection, logging, and result reconciliation.

**License status:** neither `sopnode/5g_ansible` nor its parent repository
declared a repository-level license at the comparison reference. This notice
provides provenance and attribution only; it does not create or imply a license
grant. Redistribution and modification permission for the derived deployment
files must be confirmed with the upstream copyright holders.
