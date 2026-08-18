import assert from 'node:assert/strict';
import {mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';

import {findWorkspaceStart, parseControlOutput, readLocalSnapshot} from './control.js';

const methods = [
  'experiment.bind_provider',
  'experiment.create',
  'operation.approve',
  'operation.cancel',
  'operation.execute',
  'operation.inspect',
  'operation.plan',
  'operation.read',
  'provider.experiments',
  'setup.inspect',
  'system.handshake',
  'workspace.initialize',
  'workspace.snapshot',
  'workspace.update_defaults',
];

const snapshot = {
  workspace: {
    profile: 'default',
    project: 'research-project',
    reservation_minutes: 120,
    placement: 'automatic',
  },
  experiment: {
    id: null,
    provider_experiment: null,
    intent: null,
    radio_mode: null,
    lifecycle: 'EMPTY',
  },
  access: {
    slices: {
      configured: true,
      fresh: true,
      verified: true,
      verified_at_utc: '2026-08-18T00:00:00Z',
      refresh_after_utc: '2026-08-18T12:00:00Z',
      access_until_utc: null,
      subject: 'operator',
    },
    r2lab: {
      configured: false,
      fresh: false,
      verified: false,
      verified_at_utc: null,
      refresh_after_utc: null,
      access_until_utc: null,
    },
  },
  observations: [],
  next_steps: ['configure experiment'],
  blocks: [],
};

const responseLines = (handshakeOverrides: Record<string, unknown> = {}) => [
  JSON.stringify({
    v: 6,
    id: 'handshake',
    ok: true,
    result: {
      service: 'synthran-control',
      protocol: 6,
      local_writes: true,
      provider_reads: true,
      provider_mutation: true,
      methods,
      ...handshakeOverrides,
    },
  }),
  JSON.stringify({v: 6, id: 'snapshot', ok: true, result: snapshot}),
];

test('workspace discovery climbs from nested directories', () => {
  const root = mkdtempSync(join(tmpdir(), 'synthran-workspace-'));
  try {
    mkdirSync(join(root, '.synthran'));
    writeFileSync(join(root, '.synthran', 'workspace.toml'), 'schema = "test"\n');
    const nested = join(root, 'cli', 'dist', 'backend');
    mkdirSync(nested, {recursive: true});
    assert.equal(findWorkspaceStart(nested, undefined), root);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

test('workspace discovery uses the Git root before initialization', () => {
  const root = mkdtempSync(join(tmpdir(), 'synthran-workspace-'));
  try {
    mkdirSync(join(root, '.git'));
    const nested = join(root, 'cli', 'dist', 'backend');
    mkdirSync(nested, {recursive: true});
    assert.equal(findWorkspaceStart(nested, undefined), root);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

test('explicit workspace directory resolves to its repository parent', () => {
  const root = mkdtempSync(join(tmpdir(), 'synthran-workspace-'));
  try {
    const stateDirectory = join(root, '.synthran');
    mkdirSync(stateDirectory);
    assert.equal(findWorkspaceStart('/unrelated', stateDirectory), root);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

test('valid framed responses return the sanitized snapshot', () => {
  assert.deepEqual(parseControlOutput(`${responseLines().join('\n')}\n`), snapshot);
});

test('handshake must prove the exact live operation surface', () => {
  assert.throws(
    () => parseControlOutput(responseLines({provider_mutation: false}).join('\n')),
    /handshake is incompatible/,
  );
  assert.throws(
    () => parseControlOutput(responseLines({provider_reads: false}).join('\n')),
    /handshake is incompatible/,
  );
  assert.throws(
    () => parseControlOutput(responseLines({local_writes: false}).join('\n')),
    /handshake is incompatible/,
  );
  assert.throws(
    () => parseControlOutput(responseLines({protocol: 5}).join('\n')),
    /handshake is incompatible/,
  );
  assert.throws(
    () => parseControlOutput(responseLines({methods: [...methods, 'provider.execute']}).join('\n')),
    /handshake is incompatible/,
  );
});

test('extra stdout records are rejected instead of ignored', () => {
  const lines = [...responseLines(), JSON.stringify({v: 6, id: 'extra', ok: true, result: {}})];
  assert.throws(
    () => parseControlOutput(lines.join('\n')),
    /unexpected response set/,
  );
});

test('malformed snapshots fail closed', () => {
  const lines = responseLines();
  lines[1] = JSON.stringify({
    v: 6,
    id: 'snapshot',
    ok: true,
    result: {...snapshot, observations: 'not-an-array'},
  });
  assert.throws(
    () => parseControlOutput(lines.join('\n')),
    /usable local snapshot/,
  );
});

test('already cancelled reads fail before starting the control service', async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    readLocalSnapshot(controller.signal),
    /control request was cancelled/,
  );
});
