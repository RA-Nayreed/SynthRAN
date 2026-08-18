import assert from 'node:assert/strict';
import test from 'node:test';

import type {WorkbenchState} from '../model.js';
import {
  operationKindLabel,
  primaryOperatorAction,
  secondaryOperatorAction,
} from './operator-actions.js';

const state = (lifecycle: string): WorkbenchState => ({
  project: 'post5g-beta',
  profile: 'default',
  profiles: [
    {
      name: 'default',
      slicesUsername: 'rnayreed',
      r2labSlice: null,
      identityName: null,
    },
  ],
  computeNodes: ['sopnode-f1', 'sopnode-f2', 'sopnode-f3', 'sopnode-w3'],
  experiment: 'sran-20260818-001',
  hasActiveExperiment: true,
  completedSections: [],
  intent: 'iot-to-5g',
  radio: 'virtual',
  slicesProject: 'post5g-beta',
  providerExperiment: 'provider-exp',
  slicesIdentity: 'rnayreed',
  slicesAccessFresh: true,
  r2labConfigured: false,
  r2labAccessFresh: false,
  r2labSlice: 'Not configured',
  sshIdentity: 'Not configured',
  reservationMinutes: 120,
  placement: 'automatic',
  experimentPlacement: 'automatic',
  coreNode: null,
  ranNode: null,
  lifecycle,
  observations: [],
  nextSteps: [],
  blocks: [],
});

test('primary actions follow the actual reconciliation boundary', () => {
  assert.deepEqual(primaryOperatorAction(state('CONFIGURED')), {
    action: 'up', label: 'Reserve resources', destructive: false,
  });
  assert.equal(primaryOperatorAction(state('RESERVED'))?.label, 'Allocate nodes');
  assert.equal(primaryOperatorAction(state('ALLOCATED'))?.label, 'Prepare nodes');
  assert.equal(primaryOperatorAction(state('PREPARED'))?.label, 'Deploy 5G network');
  assert.equal(primaryOperatorAction(state('NETWORK_READY'))?.label, 'Verify 5G path');
  assert.equal(primaryOperatorAction(state('PATH_PROVEN')), null);
});

test('recovery appears only when recovery is required', () => {
  assert.equal(primaryOperatorAction(state('RECOVERY_REQUIRED'))?.action, 'recover');
  assert.equal(primaryOperatorAction(state('BLOCKED')), null);
});

test('stop and release actions are contextual', () => {
  assert.equal(secondaryOperatorAction(state('RESERVED')), null);
  assert.equal(secondaryOperatorAction(state('ALLOCATED'))?.label, 'Release allocation');
  assert.equal(
    secondaryOperatorAction(state('PATH_PROVEN'))?.label,
    'Stop network and release allocation',
  );
});

test('operation kinds render concrete operator language', () => {
  assert.equal(operationKindLabel('allocate', 'fallback'), 'Allocate nodes');
  assert.equal(operationKindLabel('up', 'fallback'), 'Deploy 5G network');
  assert.equal(operationKindLabel('verify-path', 'fallback'), 'Verify 5G path');
  assert.equal(operationKindLabel('down', 'Release allocation'), 'Release allocation');
  assert.equal(operationKindLabel('unknown', 'fallback'), 'fallback');
});
