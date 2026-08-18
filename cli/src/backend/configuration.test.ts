import assert from 'node:assert/strict';
import test from 'node:test';

import {
  compatibleRadioModes,
  controlsFor,
  cycleValue,
  nextDistinctNode,
  nextReservation,
  recommendedRadioMode,
} from './configuration.js';

test('virtual and physical intents exclude incompatible radio modes', () => {
  assert.deepEqual(compatibleRadioModes('virtual-5g'), ['virtual', 'automatic']);
  assert.deepEqual(compatibleRadioModes('physical-5g'), ['physical', 'automatic']);
  assert.deepEqual(compatibleRadioModes('iot-to-5g'), ['virtual', 'physical', 'automatic']);
  assert.equal(recommendedRadioMode('virtual-5g'), 'virtual');
  assert.equal(recommendedRadioMode('physical-5g'), 'physical');
});

test('manual placement exposes exact role pin controls', () => {
  assert.equal(controlsFor('automatic').includes('core-node'), false);
  assert.equal(controlsFor('automatic').includes('ran-node'), false);
  assert.equal(controlsFor('manual').includes('core-node'), true);
  assert.equal(controlsFor('manual').includes('ran-node'), true);
});

test('cycling wraps in both directions', () => {
  const values = ['a', 'b', 'c'] as const;
  assert.equal(cycleValue(values, 'c', 1), 'a');
  assert.equal(cycleValue(values, 'a', -1), 'c');
});

test('reservation changes clamp to provider-neutral workspace bounds', () => {
  assert.equal(nextReservation(120, 30, 10, 1440), 150);
  assert.equal(nextReservation(20, -30, 10, 1440), 10);
  assert.equal(nextReservation(1430, 30, 10, 1440), 1440);
});

test('manual node cycling never selects the other role node', () => {
  const nodes = ['f1', 'f2', 'f3', 'w3'];
  assert.equal(nextDistinctNode(nodes, 'f2', 'f3', 1), 'w3');
  assert.equal(nextDistinctNode(nodes, 'f2', 'f1', -1), 'w3');
});
