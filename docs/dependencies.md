# Dependency Reuse and Updates

## Reuse model

SynthRAN composes upstream systems; it does not absorb them.

- Git dependencies are complete detached checkouts at immutable commits.
- Container images use immutable digests.
- Direct Conda dependencies use exact versions under `conda.packages`, and the lock declares `linux-64` as the only supported platform.
- Mutable upstream branch names are provenance notes only and are never runtime selectors.
- No Git submodules are used.
- Dependency source belongs under ignored `.deps/` storage.

Complete checkouts matter because `5g_ansible` and Contiki-NG behavior depends on repository-relative roles, examples, templates, build files, and scripts. Copying only visible entry points would make SynthRAN responsible for reconstructing undocumented upstream coupling.

## Synchronization

Activate `synthran` before running these commands.

Preview the two direct checkouts:

```sh
python -m synthran deps sync --dry-run
```

Synchronize them:

```sh
python -m synthran deps sync
```

Inspect locked transitive Git repositories as well:

```sh
python -m synthran deps sync --all
```

Synchronization refuses an origin mismatch or dirty managed checkout. It never merges an upstream branch and never discards local work.

## Golden-path variable mapping

The pinned `5g_ansible` tree accepts its transitive repositories through Ansible variables:

| Locked dependency | Ansible variable |
|---|---|
| `sopnode/open5gs-k8s` | `repo_branch` |
| `turletti/srsran-helm` | `version` |

The golden-path planner and executor pass these exact commits. Execution also installs only `kubernetes.core==6.5.0`, requires the locked yq binary by SHA-256, verifies the exact Python packages used for subscriber bootstrap, and replaces every selected mutable image tag with a Linux AMD64 digest before Kubernetes sees a manifest. It runs from an isolated detached `5g_ansible` worktree and never invokes upstream `deploy.sh`.

The tracked `deploy/ansible/patches/golden-path-boundary.patch` applies only to the locked `5g_ansible` commit and is checked before application. It prevents the selected roles from restarting the cluster, installing or upgrading host packages, downloading mutable tools, deploying the optional WebUI, or expanding the runtime beyond slice one and one srsUE. A patch-context mismatch is terminal.

## Update procedure

Update one dependency at a time:

1. Resolve the intended source reference to an immutable commit or digest.
2. Inspect its license and redistribution implications.
3. Update `dependencies.lock.yml` and `THIRD_PARTY.md` together.
4. Synchronize and verify a clean detached checkout.
5. Run all offline tests and privacy checks.
6. Complete the golden-path compatibility test appropriate to that dependency.
7. Record the rationale and evidence in the local decision journal.

Do not copy `5g_ansible` source into SynthRAN. Its pinned tree has no asserted top-level license, so derivative publication requires clarification.
