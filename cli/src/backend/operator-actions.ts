import type {OperationAction} from './control.js';
import type {WorkbenchState} from '../model.js';

export interface OperatorActionView {
  action: OperationAction;
  label: string;
  destructive: boolean;
}

const action = (
  name: OperationAction,
  label: string,
  destructive = false,
): OperatorActionView => ({action: name, label, destructive});

export const primaryOperatorAction = (state: WorkbenchState): OperatorActionView | null => {
  if (state.lifecycle === 'RECOVERY_REQUIRED') {
    return action('recover', 'Recover allocation');
  }
  if (state.lifecycle === 'BLOCKED' || state.lifecycle === 'EMPTY') return null;

  // The internal `up` action reconciles exactly one current step. Keeping the
  // operator label concrete lets a fresh provider read safely adapt if state
  // changed after the last local snapshot.
  if (state.lifecycle === 'CONFIGURED') return action('up', 'Reserve resources');
  if (state.lifecycle === 'RESERVED') return action('up', 'Allocate nodes');
  if (state.lifecycle === 'ALLOCATED') return action('up', 'Prepare nodes');
  if (state.lifecycle === 'PREPARED') return action('up', 'Deploy 5G network');
  if (state.lifecycle === 'NETWORK_READY') return action('verify', 'Verify 5G path');
  return null;
};

export const secondaryOperatorAction = (state: WorkbenchState): OperatorActionView | null => {
  if (state.lifecycle === 'ALLOCATED' || state.lifecycle === 'PREPARED') {
    return action('down', 'Release allocation', true);
  }
  if (state.lifecycle === 'NETWORK_READY' || state.lifecycle === 'PATH_PROVEN') {
    return action('down', 'Stop network and release allocation', true);
  }
  return null;
};

export const operationKindLabel = (kind: string, fallback: string): string => {
  const labels: Record<string, string> = {
    reserve: 'Reserve resources',
    allocate: 'Allocate nodes',
    prepare: 'Prepare nodes',
    up: 'Deploy 5G network',
    'verify-path': 'Verify 5G path',
    'recover-allocation': 'Recover allocation',
  };
  return labels[kind] ?? fallback;
};
