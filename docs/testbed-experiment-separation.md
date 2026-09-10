## Purpose
Make the R2Lab path use the pinned SOPNode 5g_ansible hardware implementation, remove obsolete SynthRAN wrappers, and give the testbed a generic experiment invocation boundary. Publish and validate each batch separately. Do not merge into main and do not add or retain test files.

## Inspected starting point
- Base: main at a45e46fa9d752c28f8ff8fce8a52b0226cb1cf03.
- PRs #7 and #8 are merged; no open PR exists.
- Latest changes reorganized experiments, removed obsolete experiment/test trees, fixed interactive gateway remapping, and restored Experiment 1 reproduction scripts.
- Authoritative upstream: sopnode/5g_ansible at a0149fc0dde39e2872945a0f3c91e804ece52d4f.
- Git blob comparisons already confirm exact upstream content for R2Lab cleanup, RRU power-on, UE setup/connect, N3xx IP swapping, and srsRAN deploy_gnb/deploy_with_check.
- Exact hardware-role files do not imply an exact end-to-end upstream workflow. SynthRAN still supplies inventory, SSH, reservations, network setup, profiles and experiment orchestration.

## Concrete findings
1. deploy.sh hardcodes an operator-specific SSH key filename, bypasses normal SSH configuration, repeats physical UE lists/mode mappings, and hardcodes Faraday settings in multiple places. Inventory is generated before .r2lab_config is loaded for reservation, so credentials can be applied too late.
2. deploy.sh unconditionally prepares an Ambient-IoT trace and embeds MQTT variables. The detached controller aggregates publisher records and reconciles MQTT results. Those are experiment responsibilities.
3. R2Lab UE connection is inside deployment/playbooks/mqtt.yml rather than the testbed bring-up path.
4. synthran/scenario.py requires model, mqtt and devices even for infrastructure configuration. Campaigns are under experiments/, while model/workload/analysis implementation remains mixed into the testbed package.
5. The progress filter prints full slash-separated role paths and suppresses standalone Ansible [ERROR] diagnostics.
6. Source attribution still points to a deleted parity test. Legacy OAI resume migration and optional R2Lab auxiliary orchestration require reachability review before removal.
7. Experiment 1 embeds settings already represented in its plan. Experiment 2 contains fixed transport and gateway assumptions that should be explicit campaign configuration, not testbed policies.

## Intended architecture
- deployment/ and synthran/ own resource selection, reservations, inventory, core/RAN/UE bring-up and reusable deployment identity.
- Experiment/ owns campaign plans, source generation, model/data, replay, MQTT services and experiment analysis. Preserve all existing campaign documents and historical records.
- A configured experiment entrypoint receives the resolved configuration and run directory. It prepares its own artifacts and execution settings, runs after testbed readiness, and finalizes its own results. A deployment without an experiment must not generate a model or start MQTT.
- Infrastructure profiles/topology are explicit data. Campaign-specific host, gateway, traffic and scientific choices live in campaign configuration.
- Preserve upstream protocol/interface constants within byte-identical upstream roles. Remove SynthRAN-specific hardcoded policy and operator assumptions rather than rewriting functioning upstream modem commands.
- Keep genuine input errors and command failures visible. Remove redundant/custom R2Lab blockers and obsolete migration code, not the ability to detect a failed deployment.

## Commit and push sequence
- [x] Batch 0 — Publish this complete plan before implementation.
- [ ] Batch 1 — R2Lab adapter cleanup. Trace upstream inputs and execution order; load credentials before inventory; respect configured SSH access; consolidate resource/mode data; move UE connection into testbed readiness; remove dead custom auxiliary paths or connect only explicitly supported generic provisioning; update the upstream parity record.
- [ ] Batch 2 — Experiment ownership. Move campaigns and shared scientific/runtime code under Experiment/, update imports/package data/entrypoints, and separate infrastructure parsing from scientific validation. Keep existing experiment data and numerical behavior.
- [ ] Batch 3 — Generic orchestration. Make experiment selection explicit/configured; delegate prepare/run/finalize through a small interface; move MQTT roles/playbooks and result reconciliation under Experiment/; make testbed-only execution work; keep prepared-workload/reuse/resume behavior coherent.
- [ ] Batch 4 — Configuration and efficiency. Remove duplicated campaign constants in favor of their plans, remove obsolete references and unreachable implementation, and avoid unnecessary bootstrap/setup repetition where dependencies are unchanged. Do not add speculative abstractions.
- [ ] Batch 5 — Hierarchical frontend logs. Render play, nested role, task, host and result with indentation; hide skipped noise; show waiting, failure and standalone diagnostics; retain complete raw logs and propagate controller exit codes.
- [ ] Batch 6 — Final validation and documentation. Check the completed boundary, command examples, package contents, upstream parity, configuration overrides, dry runs and failure handling. Update the PR body and report evidence and remaining physical acceptance explicitly.

Each implementation batch will be checked, committed and pushed before beginning the next substantial batch. Update this PR's progress and validation notes after each push.

## Validation
Use temporary checks outside the repository; retain no test files.
- Inspect current and recent diffs and compare relevant files with the pinned upstream source.
- Parse Python/Bash/YAML; install/import the package and check executable entrypoints/package data.
- Exercise representative R2Lab and RFSIM configuration rendering, including alternate hosts, identities, UE sets and testbed-only operation without real reservations.
- Exercise small deterministic model runs and prepared bundle validation/reconciliation after moves.
- Check Ansible syntax and role/playbook references, including nested/dynamic includes where applicable.
- Feed representative multi-host, nested-role, skipped, retry and fatal output through the logging frontend.
- Review git diff/check and tracked-file lists for stale paths, hardcoded operator assumptions, test files and accidental generated artifacts.
- Hardware radio synchronization, registration and actual 5G packet delivery require a real R2Lab run. Local checks will not be reported as physical acceptance.

## Status
Plan published; implementation has not started.
