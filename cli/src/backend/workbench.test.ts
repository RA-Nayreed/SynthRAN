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

test('fresh access with no experiment opens configuration', () => {
  const value = snapshot();
  assert.equal(initialSection(value), 'Configure');
  const state = toWorkbenchState(value);
  assert.deepEqual(state.completedSections, ['Access']);
  assert.equal(state.experiment, 'No active experiment');
});

test('stale SLICES access keeps access incomplete and selected', () => {
  const base = snapshot();
  const value = snapshot({
    access: {
      ...base.access,
      slices: {...base.access.slices, fresh: false},
    },
  });
  assert.equal(initialSection(value), 'Access');
  assert.deepEqual(toWorkbenchState(value).completedSections, []);
});

test('physical radio requires fresh configured R2Lab access', () => {
  const base = snapshot();
  const value = snapshot({
    experiment: {
      id: 'sran-20260818-001',
      provider_experiment: 'provider-exp',
      intent: 'physical-5g',
      radio_mode: 'physical',
      lifecycle: 'CONFIGURED',
    },
    access: base.access,
  });
  assert.equal(initialSection(value), 'Access');
  assert.deepEqual(toWorkbenchState(value).completedSections, ['Configure']);
});

test('path proven state marks only verified earlier work complete', () => {
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
  assert.equal(initialSection(value), 'Run');
  assert.deepEqual(
    toWorkbenchState(value).completedSections,
    ['Access', 'Configure', 'Resources', 'Network'],
  );
});

test('navigation completion never marks run or evidence from lifecycle alone', () => {
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
    ['Access', 'Configure', 'Resources', 'Network'],
  );
});
