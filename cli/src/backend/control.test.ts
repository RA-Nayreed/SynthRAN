import assert from 'node:assert/strict';
import {mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';

import {
  findWorkspaceStart,
  parseControlOutput,
  parseResourcePreviewOutput,
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

const resourcePreview = {
  inventory: {
    provider: 'slices',
    observed_at_utc: '2026-08-18T12:00:00Z',
    fresh_until_utc: '2026-08-18T12:00:30Z',
    complete: true,
    resources: [
      {resource_id: 'sopnode-f2', availability: 'available', ownership: 'unowned'},
      {resource_id: 'sopnode-f3', availability: 'available', ownership: 'unowned'},
    ],
  },
  decision: {
    selection: {
      assignments: [
        {
          role: 'core',
          ordinal: 1,
          resource_id: 'sopnode-f2',
          provider: 'slices',
          kind: 'compute',
          ownership: 'unowned',
        },
        {
          role: 'ran',
          ordinal: 1,
          resource_id: 'sopnode-f3',
          provider: 'slices',
          kind: 'compute',
          ownership: 'unowned',
        },
        {
          role: 'radio',
          ordinal: 1,
          resource_id: 'virtual:rfsim',
          provider: 'virtual',
          kind: 'virtual',
          ownership: 'unowned',
        },
      ],
      provider_sets: [
        {provider: 'slices', resource_ids: ['sopnode-f2', 'sopnode-f3']},
        {provider: 'virtual', resource_ids: ['virtual:rfsim']},
      ],
    },
    states: [
      {resource_id: 'sopnode-f2', availability: 'available', ownership: 'unowned'},
      {resource_id: 'sopnode-f3', availability: 'available', ownership: 'unowned'},
      {resource_id: 'virtual:rfsim', availability: 'available', ownership: 'unowned'},
    ],
  },
};

const handshake = (overrides: Record<string, unknown> = {}) => ({
  service: 'synthran-control',
  protocol: 3,
  local_writes: true,
  provider_reads: true,
  provider_mutation: false,
  methods: [
    'experiment.create',
    'resources.preview',
    'system.handshake',
    'workspace.snapshot',
  ],
  ...overrides,
});

const snapshotLines = (handshakeOverrides: Record<string, unknown> = {}) => [
  JSON.stringify({v: 3, id: 'handshake', ok: true, result: handshake(handshakeOverrides)}),
  JSON.stringify({v: 3, id: 'snapshot', ok: true, result: snapshot}),
];

const previewLines = (target: Record<string, unknown>) => [
  JSON.stringify({v: 3, id: 'handshake', ok: true, result: handshake()}),
  JSON.stringify({v: 3, id: 'preview', ...target}),
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

test('handshake requires exact read-only provider capabilities', () => {
  assert.throws(
    () => parseControlOutput(snapshotLines({provider_mutation: true}).join('\n')),
    /handshake is incompatible/,
  );
  assert.throws(
    () => parseControlOutput(snapshotLines({provider_reads: false}).join('\n')),
    /handshake is incompatible/,
  );
  assert.throws(
    () => parseControlOutput(snapshotLines({protocol: 2}).join('\n')),
    /handshake is incompatible/,
  );
  assert.throws(
    () =>
      parseControlOutput(
        snapshotLines({
          methods: [
            'experiment.create',
            'resources.preview',
            'system.handshake',
            'workspace.snapshot',
            'resource.reserve',
          ],
        }).join('\n'),
      ),
    /handshake is incompatible/,
  );
});

test('resource preview parser validates inventory and decision structure', () => {
  assert.deepEqual(
    parseResourcePreviewOutput(previewLines({ok: true, result: resourcePreview}).join('\n')),
    resourcePreview,
  );

  const malformed = {
    ...resourcePreview,
    inventory: {...resourcePreview.inventory, complete: false},
  };
  assert.throws(
    () => parseResourcePreviewOutput(previewLines({ok: true, result: malformed}).join('\n')),
    /malformed resource preview/,
  );
});

test('resource preview errors are surfaced only when bounded', () => {
  assert.throws(
    () =>
      parseResourcePreviewOutput(
        previewLines({
          ok: false,
          error: {code: 'resource_unavailable', message: 'current complete r2lab resource inventory is required'},
        }).join('\n'),
      ),
    /complete r2lab resource inventory/,
  );

  assert.throws(
    () =>
      parseResourcePreviewOutput(
        previewLines({
          ok: false,
          error: {code: 'resource_unavailable', message: 'x'.repeat(513)},
        }).join('\n'),
      ),
    /resource preview is unavailable/,
  );
});

test('extra stdout records are rejected instead of ignored', () => {
  const lines = [...snapshotLines(), JSON.stringify({v: 3, id: 'extra', ok: true, result: {}})];
  assert.throws(() => parseControlOutput(lines.join('\n')), /unexpected response set/);
});

test('malformed snapshots fail closed', () => {
  const lines = snapshotLines();
  lines[1] = JSON.stringify({
    v: 3,
    id: 'snapshot',
    ok: true,
    result: {...snapshot, observations: 'not-an-array'},
  });
  assert.throws(() => parseControlOutput(lines.join('\n')), /usable local snapshot/);
});

test('already cancelled reads fail before starting the control service', async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(readLocalSnapshot(controller.signal), /local control request was cancelled/);
});
