export type SectionLabel = 'Access' | 'Configure' | 'Resources' | 'Network' | 'Run' | 'Evidence';
export type RadioMode = 'automatic' | 'virtual' | 'physical';

export interface ObservationView {
  name: string;
  state: string;
  fresh: boolean;
  source: string | null;
  ownership: string | null;
  detail: string;
}

export interface WorkbenchState {
  project: string;
  experiment: string;
  completedSections: SectionLabel[];
  intent: string;
  radio: RadioMode;
  slicesProject: string;
  providerExperiment: string | null;
  slicesIdentity: string | null;
  slicesAccessFresh: boolean;
  r2labConfigured: boolean;
  r2labAccessFresh: boolean;
  r2labSlice: string;
  sshIdentity: string;
  reservationMinutes: number;
  placement: string;
  lifecycle: string;
  observations: ObservationView[];
  nextSteps: string[];
  blocks: string[];
}

export const sectionLabels: SectionLabel[] = [
  'Access',
  'Configure',
  'Resources',
  'Network',
  'Run',
  'Evidence',
];
