import assert from 'node:assert/strict';
import test from 'node:test';

import type {ControlSnapshot} from './control.js';
import {initialSection, toWorkbenchState} from './workbench.js';

const snapshot = (overrides: Partial<ControlSnapshot> = {}): ControlSnapshot => ({
  workspace: {
    profile: 'operator',
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
});

test('configured experiment completes setup and opens resources', () => {
  const value = snapshot({
    experiment: {
      id: 'sran-20260818-001',
      provider_experiment: null,
      intent: 'iot-to-5g',
      radio_mode: 'virtual',
      lifecycle: 'CONFIGURED',
    },
  });
  const state = toWorkbenchState(value);
  assert.equal(initialSection(value), 'Resources');
  assert.equal(state.hasActiveExperiment, true);
  assert.equal(state.experiment, 'sran-20260818-001');
  assert.deepEqual(state.completedSections, ['Setup']);
});

test('stale SLICES access keeps setup incomplete and selected', () => {
  const base = snapshot();
  const value = snapshot({
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
    experiment: {
      id: 'sran-20260818-001',
      provider_experiment: 'provider-exp',
      intent: 'iot-to-5g',
      radio_mode: 'physical',
      lifecycle: 'CONFIGURED',
    },
    access: base.access,
  });
  assert.equal(initialSection(value), 'Setup');
  assert.deepEqual(toWorkbenchState(value).completedSections, []);
});

test('path proven state opens experiment and marks verified earlier work complete', () => {
  const base = snapshot();
  const value = snapshot({
    experiment: {
      id: 'sran-20260818-001',
      provider_experiment: 'provider-exp',
      intent: 'iot-to-5g',
      radio_mode: 'virtual',
      lifecycle: 'PATH_PROVEN',
    },
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
    experiment: {
      id: 'sran-20260818-001',
      provider_experiment: 'provider-exp',
      intent: 'iot-to-5g',
      radio_mode: 'virtual',
      lifecycle: 'EXPERIMENT_RUNNING',
    },
    access: base.access,
  });
  assert.deepEqual(
    toWorkbenchState(value).completedSections,
    ['Setup', 'Resources', 'Network'],
  );
});
