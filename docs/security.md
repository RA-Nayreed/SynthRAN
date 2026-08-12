# Security, Privacy and Artifact Handling

## Repository boundary

Never commit:

- generated inventories or subscriber profiles;
- IMSIs, authentication keys, OPC values, or subscriber credentials;
- SLICES credentials, reservation tokens, kubeconfigs, or private keys;
- `.env` files containing secrets;
- unsanitized packet captures or testbed logs;
- dependency worktrees, run directories, or firmware build output.

Ignore rules reduce accidental staging but are not a security boundary by themselves.

## Layered publication protection

SynthRAN uses complementary controls:

1. tracked ignore rules for known local and generated paths;
2. a local pre-push hook that scans every outgoing commit;
3. GitHub push protection for supported provider credentials;
4. a read-only CI workflow that scans the worktree and full Git history with Gitleaks;
5. explicit sanitization for generated public text.

Scanners report a rule and location, not the detected value. Source findings block publication rather than silently rewriting code.

## Manual scanning

With `synthran` activated:

```sh
python -m synthran privacy scan --worktree
python -m synthran privacy scan --history
```

## Generated text redaction

Write a separate sanitized derivative:

```sh
python -m synthran privacy redact \
  input.txt sanitized.txt --dry-run
python -m synthran privacy redact \
  input.txt sanitized.txt
```

The redactor replaces local user homes, usernames, network-share prefixes, and private IP addresses with stable placeholders. It never rewrites the input in place.

Do not use text redaction for packet captures, kubeconfigs, private keys, databases, or binary credential stores. Keep raw artifacts local and create purpose-built sanitized evidence.

## Experiment artifacts

Run manifests retain dependency and overlay hashes, image digests, inventory hashes, node roles, selected non-secret route facts, timestamps, and validation results. Sensitive raw evidence remains untracked by default. Cleanup may target only resources proven to carry the requested run ID.
