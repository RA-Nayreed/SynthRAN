import assert from 'node:assert/strict';
import test from 'node:test';

import {
  allowedRadioModes,
  cycleValue,
  recommendedRadioForIntent,
} from './configuration.js';

test('recommended radio follows intent safety', () => {
  assert.equal(recommendedRadioForIntent('virtual-5g'), 'virtual');
  assert.equal(recommendedRadioForIntent('physical-5g'), 'physical');
  assert.equal(recommendedRadioForIntent('open-ran'), 'automatic');
  assert.equal(recommendedRadioForIntent('iot-to-5g'), 'automatic');
});

test('virtual and physical intents exclude incompatible radio modes', () => {
  assert.deepEqual(allowedRadioModes('virtual-5g'), ['automatic', 'virtual']);
  assert.deepEqual(allowedRadioModes('physical-5g'), ['automatic', 'physical']);
  assert.deepEqual(allowedRadioModes('iot-to-5g'), ['automatic', 'virtual', 'physical']);
});

test('selector cycling wraps in both directions', () => {
  const values = ['a', 'b', 'c'] as const;
  assert.equal(cycleValue(values, 'c', 1), 'a');
  assert.equal(cycleValue(values, 'a', -1), 'c');
});
