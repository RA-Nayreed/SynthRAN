## Purpose

<!-- What problem does this change solve? Keep the scope specific. -->

## Repository boundary

<!-- Check every area this PR changes. -->

- [ ] `deploy.sh` / deployment controller
- [ ] `scenarios/` / infrastructure configuration
- [ ] `deployment/` / Ansible or testbed integration
- [ ] `synthran/` / Python support code
- [ ] `Experiment/` / scientific experiment work
- [ ] Documentation / metadata only
- [ ] Third-party provenance or licensing

## What changed

<!-- Summarize the implementation, not only the intent. -->

## Validation

<!-- List commands/runs actually performed. Do not claim checks that were not run. -->

- [ ] `bash -n deploy.sh` when shell control flow changed
- [ ] `python3 -m compileall -q synthran` when Python changed
- [ ] Relevant scenario `--dry-run` when deployment configuration changed
- [ ] Virtual deployment acceptance when required
- [ ] Authorized physical R2Lab acceptance when required
- [ ] Not applicable; explain why below

Validation evidence / explanation:

```text

```

## Research claim discipline

- [ ] This PR does not describe planned behavior as implemented.
- [ ] This PR does not describe implemented behavior as physically validated unless a live acceptance run was performed.
- [ ] This PR does not turn one successful run into a general scientific claim.
- [ ] Experiment changes preserve enough configuration/provenance to reproduce the study.

## Deployment safety

- [ ] No wildcard/broad cleanup was introduced for shared resources.
- [ ] Resource mutations remain bound to selected/owned authority.
- [ ] No credentials, tokens, private keys, subscriber secrets, or machine-specific access files were committed.
- [ ] Not applicable to this PR.

## Third-party / provenance check

- [ ] No external code was copied or adapted.
- [ ] External code was used and its source revision, copyright, and license status are recorded in this PR and the appropriate provenance files.

## Known limitations / follow-up

<!-- State what remains unverified or intentionally out of scope. -->
