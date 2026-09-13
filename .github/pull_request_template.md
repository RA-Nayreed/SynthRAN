## Purpose

<!-- What problem does this change solve? Keep the scope specific. -->

## Repository boundary

<!-- Check every area this PR changes. -->

- [ ] `deploy.sh` / deployment controller
- [ ] `deployment/` / Ansible or testbed integration
- [ ] `experiment.sh` / scientific experiment controller
- [ ] `Experiments/` / study-specific scientific experiment work
- [ ] `synthran/` / reusable Python support code
- [ ] Documentation / metadata only
- [ ] Third-party provenance or licensing

## What changed

<!-- Summarize the implementation, not only the intent. -->

## Validation

<!-- List commands/runs actually performed. Do not claim checks that were not run. -->

- [ ] `bash -n deploy.sh` when deployment shell control flow changed
- [ ] `bash -n experiment.sh` when experiment shell control flow changed
- [ ] `python3 -m compileall -q synthran Experiments` when Python changed
- [ ] Relevant deployment `--dry-run` when infrastructure configuration changed
- [ ] Experiment planner/contract validation when scientific control flow changed
- [ ] Virtual deployment acceptance when required
- [ ] Authorized physical R2Lab acceptance when required
- [ ] Real stochastic campaign execution when a scientific result is claimed
- [ ] Not applicable; explain why below

Validation evidence / explanation:

```text

```

## Research claim discipline

- [ ] This PR does not describe planned behavior as implemented.
- [ ] This PR does not describe implemented behavior as physically validated unless a live acceptance run was performed.
- [ ] This PR does not turn one successful run into a general scientific claim.
- [ ] Experiment changes preserve enough configuration/provenance to reproduce the study.
- [ ] Frozen experiment designs are not silently modified after confirmation begins.

## Deployment and experiment safety

- [ ] No wildcard/broad cleanup was introduced for shared resources.
- [ ] Resource mutations remain bound to selected/owned deployment authority.
- [ ] Scientific experiment code does not reserve, repair, rebuild, power-cycle, or reconfigure accepted testbed infrastructure merely to make a run pass.
- [ ] No credentials, tokens, private keys, subscriber secrets, or machine-specific access files were committed.
- [ ] Not applicable to this PR.

## Third-party / provenance check

- [ ] No external code was copied or adapted.
- [ ] External code was used and its source revision, copyright, and license status are recorded in this PR and the appropriate provenance files.

## Known limitations / follow-up

<!-- State what remains unverified or intentionally out of scope. -->
