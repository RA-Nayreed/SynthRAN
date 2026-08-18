import assert from 'node:assert/strict';
import test from 'node:test';

import type {ControlSnapshot} from './control.js';
import {initialSection, toWorkbenchState} from './workbench.js';

const experiment = (
  overrides: Partial<ControlSnapshot['experiment']> = {},
): ControlSnapshot['experiment'] => ({
  id: null,
  provider_experiment: null,
  intent: null,
  radio_mode: null,
  placement_mode: null,
  core_node: null,
  ran_node: null,
  lifecycle: 'EMPTY',
  ...overrides,
});

const snapshot = (overrides: Partial<ControlSnapshot> = {}): ControlSnapshot => ({
  workspace: {
    profile: 'operator',
    project: 'research-project',
    reservation_minutes: 120,
    placement: 'automatic',
  },
  profiles: [
    {
      name: 'operator',
      slices_username: 'operator',
      r2lab_slice: null,
      identity_name: null,
    },
  ],
  compute_nodes: ['sopnode-f1', 'sopnode-f2', 'sopnode-f3', 'sopnode-w3'],
  experiment: experiment(),
  access: {
    slices: {
      configured: true,
      verified: true,
      fresh: true,
      subject: 'operator',
      verified_at_utc: '2026-08-18T00:00:00Z',
      refresh_after_utc: '2026-08-18T12:00:00Z',
      access_until_utc: null,
    },
    r2lab: {
      configured: false,
      verified: false,
      fresh: false,
      verified_at_utc: null,
      refresh_after_utc: null,
      access_until_utc: null,
    },
  },
  observations: [],
  next_steps: [],
  blocks: [],
  ...overrides,
});

test('fresh access with no experiment opens setup', () => {
  const value = snapshot();
  assert.equal(initialSection(value), 'Setup');
  const state = toWorkbenchState(value);
  assert.deepEqual(state.completedSections, []);
  assert.equal(state.profile, 'operator');
  assert.equal(state.experiment, 'No active experiment');
  assert.equal(state.hasActiveExperiment, false);
  assert.deepEqual(state.computeNodes, ['sopnode-f1', 'sopnode-f2', 'sopnode-f3', 'sopnode-w3']);
});

test('manual placement is projected with exact nodes', () => {
  const value = snapshot({
    experiment: experiment({
      id: 'sran-20260818-001',
      intent: 'iot-to-5g',
      radio_mode: 'virtual',
      placement_mode: 'manual',
      core_node: 'sopnode-f2',
      ran_node: 'sopnode-f3',
      lifecycle: 'CONFIGURED',
    }),
  });
  const state = toWorkbenchState(value);
  assert.equal(state.experimentPlacement, 'manual');
  assert.equal(state.coreNode, 'sopnode-f2');
  assert.equal(state.ranNode, 'sopnode-f3');
});

test('local configuration without provider binding remains in setup', () => {
  const value = snapshot({
    experiment: experiment({
      id: 'sran-20260818-001',
      intent: 'iot-to-5g',
      radio_mode: 'virtual',
      placement_mode: 'automatic',
      lifecycle: 'CONFIGURED',
    }),
  });
  const state = toWorkbenchState(value);
  assert.equal(initialSection(value), 'Setup');
  assert.equal(state.hasActiveExperiment, true);
  assert.equal(state.experiment, 'sran-20260818-001');
  assert.deepEqual(state.completedSections, []);
});

test('bound virtual configuration completes setup and opens resources', () => {
  const value = snapshot({
    experiment: experiment({
      id: 'sran-20260818-001',
      provider_experiment: 'provider-exp',
      intent: 'iot-to-5g',
      radio_mode: 'virtual',
      placement_mode: 'automatic',
      lifecycle: 'CONFIGURED',
    }),
  });
  assert.equal(initialSection(value), 'Resources');
  assert.deepEqual(toWorkbenchState(value).completedSections, ['Setup']);
});

test('stale SLICES access keeps setup incomplete and selected', () => {
  const base = snapshot();
  const value = snapshot({
    experiment: experiment({
      id: 'sran-20260818-001',
      provider_experiment: 'provider-exp',
      intent: 'iot-to-5g',
      radio_mode: 'virtual',
      placement_mode: 'automatic',
      lifecycle: 'CONFIGURED',
    }),
    access: {
      ...base.access,
      slices: {...base.access.slices, fresh: false},
    },
  });
  assert.equal(initialSection(value), 'Setup');
  assert.deepEqual(toWorkbenchState(value).completedSections, []);
});

test('physical radio requires fresh configured R2Lab access', () => {
  const base = snapshot();
  const value = snapshot({
    experiment: experiment({
      id: 'sran-20260818-001',
      provider_experiment: 'provider-exp',
      intent: 'iot-to-5g',
      radio_mode: 'physical',
      placement_mode: 'automatic',
      lifecycle: 'CONFIGURED',
    }),
    access: base.access,
  });
  assert.equal(initialSection(value), 'Setup');
  assert.deepEqual(toWorkbenchState(value).completedSections, []);
});

test('path proven state opens experiment and marks verified earlier work complete', () => {
  const base = snapshot();
  const value = snapshot({
    experiment: experiment({
      id: 'sran-20260818-001',
      provider_experiment: 'provider-exp',
      intent: 'iot-to-5g',
      radio_mode: 'virtual',
      placement_mode: 'automatic',
      lifecycle: 'PATH_PROVEN',
    }),
    access: base.access,
  });
  assert.equal(initialSection(value), 'Experiment');
  assert.deepEqual(
    toWorkbenchState(value).completedSections,
    ['Setup', 'Resources', 'Network'],
  );
});

test('navigation completion never marks experiment or data from lifecycle alone', () => {
  const base = snapshot();
  const value = snapshot({
    experiment: experiment({
      id: 'sran-20260818-001',
      provider_experiment: 'provider-exp',
      intent: 'iot-to-5g',
      radio_mode: 'virtual',
      placement_mode: 'automatic',
      lifecycle: 'EXPERIMENT_RUNNING',
    }),
    access: base.access,
  });
  assert.deepEqual(
    toWorkbenchState(value).completedSections,
    ['Setup', 'Resources', 'Network'],
  );
});
