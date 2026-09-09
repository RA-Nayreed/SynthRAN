# R2Lab helper compatibility fixtures

`prepare-ue` is an unmodified copy of
[sopnode/oai5g-rru at 9d7f2df8e98527c1a3b05c6352b167e8e9ce7c19](https://github.com/sopnode/oai5g-rru/blob/9d7f2df8e98527c1a3b05c6352b167e8e9ce7c19/quectel-utils/prepare-ue).
Its BSD 3-Clause license is retained in `LICENSE`.

The Ansible integration tests execute this helper while replacing USB control,
sleep, modem configuration, and diagnostic commands with local fixtures. They
verify that omitting `--mode` still selects MBIM and preserves the selected DNN
and NSSAI. This file is never installed on testbed nodes.

A separate strict CLI fixture accepts only `--dnn`, `--dnn2`, `--nssai`, and
`--nssai2`, matching the installed helper's usage output from physical run
`20260909T101521Z`. That fixture rejects unknown options instead of allowing
every SSH invocation to succeed. It models the reported CLI contract; it is
not a copy of the installed helper, whose source was not supplied.
