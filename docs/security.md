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
4. a read-only CI workflow whose source and Gitleaks scans still run when unrelated unit tests fail;
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

## Privileged Boundary and SSH Tunnel Isolation

The controller host runs unprivileged without requiring `sudo`. Privileged TUN network setup (`tunslip6` and `tun0` at `fd00::1/64`) and TCP ingress run exclusively on the root core node (`inventory.core_node`).

To ensure strict network isolation:
1. The reverse SSH tunnel connecting Cooja's serial socket on the controller to the core node explicitly binds to loopback (`-R 127.0.0.1:60001:127.0.0.1:60001`). Remote ports are never exposed to public or non-loopback interfaces.
2. All SSH commands employ strict host-key checking against the run's verified known hosts file (`StrictHostKeyChecking=yes`).
3. Remote core node prerequisites fail closed if `tun0` exists prior to the run, preventing unauthorized adoption or mutation of existing host interfaces.
4. Experiment cleanup removes only the run-created `tun0` interface and the isolated run workspace `/tmp/synthran/<run-id>/`.
