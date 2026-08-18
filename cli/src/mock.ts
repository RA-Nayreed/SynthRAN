export type PhaseStatus = 'complete' | 'active' | 'pending';

export interface Phase {
  label: string;
  status: PhaseStatus;
}

export interface WorkbenchState {
  project: string;
  experiment: string;
  mode: 'OBSERVE' | 'OPERATE';
  phases: Phase[];
  intent: string;
  radio: 'virtual' | 'physical';
  slicesProject: string;
  providerExperiment: string | null;
  r2labSlice: string;
  sshIdentity: string;
  reservationMinutes: number;
}

export const mockWorkbenchState: WorkbenchState = {
  project: 'post5g-beta',
  experiment: 'sran-20260818-001',
  mode: 'OBSERVE',
  phases: [
    {label: 'Access', status: 'complete'},
    {label: 'Configure', status: 'active'},
    {label: 'Resources', status: 'pending'},
    {label: 'Network', status: 'pending'},
    {label: 'Run', status: 'pending'},
    {label: 'Evidence', status: 'pending'},
  ],
  intent: 'IoT → 5G',
  radio: 'physical',
  slicesProject: 'post5g-beta',
  providerExperiment: null,
  r2labSlice: 'oulu_rnayreed',
  sshIdentity: 'id_rsa_r2lab_duckburg',
  reservationMinutes: 120,
};
