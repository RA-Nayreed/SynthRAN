import type {ControlSnapshot} from './control.js';
import type {RadioMode, SectionLabel, WorkbenchState} from '../model.js';

const lifecycleIn = (lifecycle: string, values: readonly string[]) => values.includes(lifecycle);

const radioMode = (value: string | null): RadioMode => {
  if (value === 'virtual' || value === 'physical' || value === 'automatic') return value;
  return 'automatic';
};

const accessReady = (snapshot: ControlSnapshot): boolean => {
  const slicesReady = (
    snapshot.access.slices.configured &&
    snapshot.access.slices.verified &&
    snapshot.access.slices.fresh
  );
  if (!slicesReady) return false;

  const physicalRequired = snapshot.experiment.radio_mode === 'physical';
  if (!physicalRequired) return true;
  return (
    snapshot.access.r2lab.configured &&
    snapshot.access.r2lab.verified &&
    snapshot.access.r2lab.fresh
  );
};

const completedSections = (snapshot: ControlSnapshot): SectionLabel[] => {
  const completed: SectionLabel[] = [];
  if (accessReady(snapshot)) completed.push('Access');
  if (snapshot.experiment.id !== null) completed.push('Configure');
  if (lifecycleIn(snapshot.experiment.lifecycle, [
    'ALLOCATED',
    'PREPARED',
    'NETWORK_READY',
    'PATH_PROVEN',
    'EXPERIMENT_RUNNING',
  ])) completed.push('Resources');
  if (lifecycleIn(snapshot.experiment.lifecycle, ['PATH_PROVEN', 'EXPERIMENT_RUNNING'])) {
    completed.push('Network');
  }
  return completed;
};

export const initialSection = (snapshot: ControlSnapshot): SectionLabel => {
  if (!accessReady(snapshot)) return 'Access';
  if (snapshot.experiment.id === null) return 'Configure';
  if (snapshot.experiment.lifecycle === 'PATH_PROVEN' || snapshot.experiment.lifecycle === 'EXPERIMENT_RUNNING') {
    return 'Run';
  }
  if (['PREPARED', 'NETWORK_READY'].includes(snapshot.experiment.lifecycle)) return 'Network';
  return 'Resources';
};

export const toWorkbenchState = (snapshot: ControlSnapshot): WorkbenchState => ({
  project: snapshot.workspace.project,
  experiment: snapshot.experiment.id ?? 'No active experiment',
  completedSections: completedSections(snapshot),
  intent: snapshot.experiment.intent ?? 'Not configured',
  radio: radioMode(snapshot.experiment.radio_mode),
  slicesProject: snapshot.workspace.project,
  providerExperiment: snapshot.experiment.provider_experiment,
  slicesIdentity: snapshot.access.slices.subject ?? null,
  slicesAccessFresh: snapshot.access.slices.verified && snapshot.access.slices.fresh,
  r2labConfigured: snapshot.access.r2lab.configured,
  r2labAccessFresh: snapshot.access.r2lab.verified && snapshot.access.r2lab.fresh,
  r2labSlice: snapshot.access.r2lab.slice ?? 'Not configured',
  sshIdentity: snapshot.access.r2lab.identity_name ?? 'Not configured',
  reservationMinutes: snapshot.workspace.reservation_minutes,
  placement: snapshot.workspace.placement,
  lifecycle: snapshot.experiment.lifecycle,
  observations: snapshot.observations,
  nextSteps: snapshot.next_steps,
  blocks: snapshot.blocks,
});
