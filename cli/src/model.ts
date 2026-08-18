export type SectionLabel = 'Setup' | 'Resources' | 'Network' | 'Experiment' | 'Data';
export type RadioMode = 'automatic' | 'virtual' | 'physical';

export interface ObservationView {
  name: string;
  state: string;
  fresh: boolean;
  source: string | null;
  ownership: string | null;
  detail: string;
}

export interface ProfileView {
  name: string;
  slicesUsername: string | null;
  r2labSlice: string | null;
  identityName: string | null;
}

export interface WorkbenchState {
  project: string;
  profile: string;
  profiles: ProfileView[];
  computeNodes: string[];
  experiment: string;
  hasActiveExperiment: boolean;
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
  experimentPlacement: string | null;
  coreNode: string | null;
  ranNode: string | null;
  lifecycle: string;
  observations: ObservationView[];
  nextSteps: string[];
  blocks: string[];
}

export const sectionLabels: SectionLabel[] = [
  'Setup',
  'Resources',
  'Network',
  'Experiment',
  'Data',
];
