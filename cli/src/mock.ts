export type SectionLabel = 'Access' | 'Configure' | 'Resources' | 'Network' | 'Run' | 'Evidence';

export interface WorkbenchState {
  project: string;
  experiment: string;
  mode: 'OBSERVE' | 'OPERATE';
  completedSections: SectionLabel[];
  intent: string;
  radio: 'virtual' | 'physical';
  slicesProject: string;
  providerExperiment: string | null;
  r2labSlice: string;
  sshIdentity: string;
  reservationMinutes: number;
}

export const sectionLabels: SectionLabel[] = [
  'Access',
  'Configure',
  'Resources',
  'Network',
  'Run',
  'Evidence',
];

export const mockWorkbenchState: WorkbenchState = {
  project: 'example-project',
  experiment: 'sran-20260818-001',
  mode: 'OBSERVE',
  completedSections: ['Access'],
  intent: 'IoT → 5G',
  radio: 'physical',
  slicesProject: 'example-project',
  providerExperiment: null,
  r2labSlice: 'example_slice',
  sshIdentity: 'id_r2lab',
  reservationMinutes: 120,
};
