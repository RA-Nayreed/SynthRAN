import type {ExperimentIntent, PlacementMode} from './control.js';
import type {RadioMode} from '../model.js';

export type ConfigurationControl =
  | 'intent'
  | 'radio'
  | 'experiment-placement'
  | 'core-node'
  | 'ran-node'
  | 'default-placement'
  | 'reservation'
  | 'save-defaults'
  | 'create-experiment'
  | 'provider-experiment'
  | 'bind-provider';

export const experimentIntents: ExperimentIntent[] = [
  'iot-to-5g',
  'virtual-5g',
  'physical-5g',
  'open-ran',
  'unspecified',
];

export const compatibleRadioModes = (intent: ExperimentIntent): RadioMode[] => {
  if (intent === 'virtual-5g') return ['virtual', 'automatic'];
  if (intent === 'physical-5g') return ['physical', 'automatic'];
  return ['virtual', 'physical', 'automatic'];
};

export const recommendedRadioMode = (intent: ExperimentIntent): RadioMode => {
  if (intent === 'physical-5g') return 'physical';
  if (intent === 'virtual-5g') return 'virtual';
  return 'virtual';
};

export const controlsFor = (placement: PlacementMode): ConfigurationControl[] => [
  'intent',
  'radio',
  'experiment-placement',
  ...(placement === 'manual' ? (['core-node', 'ran-node'] as ConfigurationControl[]) : []),
  'default-placement',
  'reservation',
  'save-defaults',
  'create-experiment',
  'provider-experiment',
  'bind-provider',
];

export const cycleValue = <T>(values: readonly T[], current: T, delta: number): T => {
  if (values.length === 0) throw new Error('cannot cycle an empty option set');
  const currentIndex = values.indexOf(current);
  const start = currentIndex >= 0 ? currentIndex : 0;
  return values[(start + delta + values.length) % values.length];
};

export const clampReservation = (
  value: number,
  minimum: number,
  maximum: number,
): number => Math.max(minimum, Math.min(maximum, value));

export const nextReservation = (
  current: number,
  delta: number,
  minimum: number,
  maximum: number,
): number => clampReservation(current + delta, minimum, maximum);

export const nextDistinctNode = (
  nodes: readonly string[],
  current: string,
  other: string,
  delta: number,
): string => {
  if (nodes.length < 2) throw new Error('manual placement requires at least two compute nodes');
  let candidate = current;
  for (let attempt = 0; attempt < nodes.length; attempt += 1) {
    candidate = cycleValue(nodes, candidate, delta);
    if (candidate !== other) return candidate;
  }
  throw new Error('manual placement requires distinct compute nodes');
};
