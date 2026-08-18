import type {ExperimentIntent, RadioMode} from '../model.js';

export const recommendedRadioForIntent = (intent: ExperimentIntent): RadioMode => {
  if (intent === 'virtual-5g') return 'virtual';
  if (intent === 'physical-5g') return 'physical';
  return 'automatic';
};

export const allowedRadioModes = (intent: ExperimentIntent): RadioMode[] => {
  if (intent === 'virtual-5g') return ['automatic', 'virtual'];
  if (intent === 'physical-5g') return ['automatic', 'physical'];
  return ['automatic', 'virtual', 'physical'];
};

export const cycleValue = <T>(values: readonly T[], current: T, delta: number): T => {
  const currentIndex = values.indexOf(current);
  const start = currentIndex >= 0 ? currentIndex : 0;
  return values[(start + delta + values.length) % values.length];
};
