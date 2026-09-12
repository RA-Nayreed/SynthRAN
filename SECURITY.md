# Security policy

SynthRAN can interact with remote hosts, reservations, SSH credentials, mobile
network configuration, physical radios, and research infrastructure. Security
reports should therefore avoid exposing live credentials or access material in
public issues.

## Reporting a vulnerability

Prefer GitHub's private vulnerability-reporting / security-advisory mechanism
for this repository when it is available.

If private reporting is not available, open a minimal public issue that states
that you have a security concern and asks the maintainer to establish a private
contact channel. Do **not** include exploit details, credentials, private keys,
tokens, subscriber secrets, reservation credentials, or sensitive host data in
that public issue.

A useful private report should include:

- the affected component and revision;
- the security impact;
- steps to reproduce with secrets removed or replaced;
- whether physical infrastructure or shared testbed resources are affected;
- any known workaround or containment step.

## Sensitive data

Never commit or publish:

- SSH private keys;
- API tokens, passwords, or session credentials;
- `.r2lab_config` or equivalent machine-specific access material;
- private known-hosts material when it contains sensitive infrastructure data;
- live subscriber credentials unless they are intentionally public test values;
- `.synthran/` authority state from an active environment;
- unredacted logs that expose secrets or private infrastructure identifiers.

## Deployment safety

Security fixes that touch resource ownership, cleanup, reservation handling,
remote command execution, privilege escalation, radio control, or UE activation
must be reviewed as deployment-safety changes as well as software changes.

A successful dry run is not sufficient evidence for a fix whose behavior only
appears on live physical infrastructure. State clearly whether a report or fix
has been validated locally, virtually, or on an authorized physical testbed.

## Supported versions

SynthRAN is currently pre-1.0 research software. Security fixes are applied to
the active development line rather than maintained across a formal matrix of
older supported releases. This policy should be updated once versioned releases
have an explicit support lifetime.
