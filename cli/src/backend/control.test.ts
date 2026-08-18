import assert from 'node:assert/strict';
import {mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';

import {
  findWorkspaceStart,
  parseControlOutput,
  parseCreateOutput,
  readLocalSnapshot,
} from './control.js';

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

const handshakeResult = (overrides: Record<string, unknown> = {}) => ({
  service: 'synthran-control',
  protocol: 2,
  provider_mutation: false,
  methods: ['experiment.create', 'system.handshake', 'workspace.snapshot'],
  local_write_methods: ['experiment.create'],
  ...overrides,
});

const snapshotLines = (handshakeOverrides: Record<string, unknown> = {}) => [
  JSON.stringify({
    v: 2,
    id: 'handshake',
    ok: true,
    result: handshakeResult(handshakeOverrides),
  }),
  JSON.stringify({v: 2, id: 'snapshot', ok: true, result: snapshot}),
];

const createLines = (target: Record<string, unknown>) => [
  JSON.stringify({v: 2, id: 'handshake', ok: true, result: handshakeResult()}),
  JSON.stringify({v: 2, id: 'create', ...target}),
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
  assert.deepEqual(parseControlOutput(`${snapshotLines().join('\n')}\n`), snapshot);
});

test('handshake requires exact safe capabilities', () => {
  assert.throws(
    () => parseControlOutput(snapshotLines({provider_mutation: true}).join('\n')),
    /handshake is incompatible/,
  );
  assert.throws(
    () => parseControlOutput(snapshotLines({protocol: 3}).join('\n')),
    /handshake is incompatible/,
  );
  assert.throws(
    () =>
      parseControlOutput(
        snapshotLines({
          methods: [
            'experiment.create',
            'system.handshake',
            'workspace.snapshot',
            'resource.reserve',
          ],
        }).join('\n'),
      ),
    /handshake is incompatible/,
  );
  assert.throws(
    () => parseControlOutput(snapshotLines({local_write_methods: []}).join('\n')),
    /handshake is incompatible/,
  );
});

test('extra stdout records are rejected instead of ignored', () => {
  const lines = [
    ...snapshotLines(),
    JSON.stringify({v: 2, id: 'extra', ok: true, result: {}}),
  ];
  assert.throws(() => parseControlOutput(lines.join('\n')), /unexpected response set/);
});

test('malformed snapshots fail closed', () => {
  const lines = snapshotLines();
  lines[1] = JSON.stringify({
    v: 2,
    id: 'snapshot',
    ok: true,
    result: {...snapshot, observations: 'not-an-array'},
  });
  assert.throws(() => parseControlOutput(lines.join('\n')), /usable local snapshot/);
});

test('create responses return the new experiment snapshot', () => {
  const createdSnapshot = {
    ...snapshot,
    experiment: {
      id: 'sran-20260818-001',
      provider_experiment: null,
      intent: 'iot-to-5g',
      radio_mode: 'virtual',
      lifecycle: 'CONFIGURED',
    },
  };
  const result = parseCreateOutput(
    createLines({
      ok: true,
      result: {experiment_id: 'sran-20260818-001', snapshot: createdSnapshot},
    }).join('\n'),
  );
  assert.equal(result.experiment_id, 'sran-20260818-001');
  assert.deepEqual(result.snapshot, createdSnapshot);
});

test('bounded server validation errors are surfaced for local writes', () => {
  assert.throws(
    () =>
      parseCreateOutput(
        createLines({
          ok: false,
          error: {code: 'workspace_error', message: 'workspace already has an active experiment'},
        }).join('\n'),
      ),
    /already has an active experiment/,
  );
});

test('already cancelled reads fail before starting the control service', async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(readLocalSnapshot(controller.signal), /local control request was cancelled/);
});
