export type SectionStatus = 'complete' | 'active' | 'pending';
export type SectionLabel = 'Access' | 'Configure' | 'Resources' | 'Network' | 'Run' | 'Evidence';

export interface Section {
  label: SectionLabel;
  status: SectionStatus;
}

export interface WorkbenchState {
  project: string;
  experiment: string;
  mode: 'OBSERVE' | 'OPERATE';
  sections: Section[];
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

export const sectionsFor = (activeSection: SectionLabel): Section[] => {
  const activeIndex = sectionLabels.indexOf(activeSection);
  return sectionLabels.map((label, index) => ({
    label,
    status: index < activeIndex ? 'complete' : index === activeIndex ? 'active' : 'pending',
  }));
};

export const mockWorkbenchState: WorkbenchState = {
  project: 'post5g-beta',
  experiment: 'sran-20260818-001',
  mode: 'OBSERVE',
  sections: sectionsFor('Configure'),
  intent: 'IoT → 5G',
  radio: 'physical',
  slicesProject: 'post5g-beta',
  providerExperiment: null,
  r2labSlice: 'oulu_rnayreed',
  sshIdentity: 'id_rsa_r2lab_duckburg',
  reservationMinutes: 120,
};
