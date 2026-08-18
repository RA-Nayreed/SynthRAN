import React from 'react';
import {Box, Text} from 'ink';

import type {ExperimentIntent, PlacementMode} from '../backend/control.js';
import type {RadioMode, WorkbenchMode, WorkbenchState} from '../model.js';
import {theme} from '../theme.js';

interface ConfigurationPanelProps {
  state: WorkbenchState;
  mode: WorkbenchMode;
  draftIntent: ExperimentIntent;
  draftRadio: RadioMode;
  draftReservation: number;
  draftPlacement: PlacementMode;
  focusedIndex: number;
  localBusy: 'initializing' | 'defaults' | 'experiment' | null;
  providerBusy: 'loading' | 'binding' | null;
  providerExperiments: string[] | null;
  providerCandidate: string | null;
  notice: string | null;
}

const Row = ({label, children, focused = false}: {label: string; children: React.ReactNode; focused?: boolean}) => (
  <Box marginBottom={1}>
    <Box width={24}>
      <Text color={focused ? theme.bodyStrong : theme.muted}>{focused ? '› ' : '  '}{label}</Text>
    </Box>
    <Text color={theme.bodyStrong} inverse={focused}>{focused ? ` ${String(children)} ` : children}</Text>
  </Box>
);

const radioLabel = (value: RadioMode) => {
  if (value === 'physical') return 'Physical / R2Lab';
  if (value === 'virtual') return 'Virtual / RFSIM';
  return 'Automatic';
};

const intentLabel = (value: ExperimentIntent) => {
  if (value === 'iot-to-5g') return 'IoT → 5G';
  if (value === 'virtual-5g') return 'Virtual 5G';
  if (value === 'physical-5g') return 'Physical 5G';
  if (value === 'open-ran') return 'Open RAN';
  return 'Unspecified';
};

const providerValue = (
  state: WorkbenchState,
  providerBusy: 'loading' | 'binding' | null,
  providerExperiments: string[] | null,
  providerCandidate: string | null,
) => {
  if (state.providerExperiment) return `${state.providerExperiment} · bound`;
  if (!state.hasActiveExperiment) return 'Create local configuration first';
  if (providerBusy === 'loading') return 'Reading SLICES experiments…';
  if (providerExperiments === null) return 'Enter to load';
  if (providerExperiments.length === 0) return 'No experiments available';
  return providerCandidate ?? 'No selection';
};

const bindValue = (
  state: WorkbenchState,
  mode: WorkbenchMode,
  providerBusy: 'loading' | 'binding' | null,
  providerCandidate: string | null,
) => {
  if (state.providerExperiment) return 'Already bound';
  if (!state.hasActiveExperiment) return 'Unavailable';
  if (providerBusy === 'binding') return 'Verifying and binding…';
  if (!providerCandidate) return 'Select provider experiment first';
  return mode === 'OPERATE' ? 'Enter' : 'Switch to OPERATE';
};

export const ConfigurationPanel = ({
  state,
  mode,
  draftIntent,
  draftRadio,
  draftReservation,
  draftPlacement,
  focusedIndex,
  localBusy,
  providerBusy,
  providerExperiments,
  providerCandidate,
  notice,
}: ConfigurationPanelProps) => (
  <Box flexDirection="column" paddingX={1} paddingY={1}>
    <Text bold color={theme.bodyStrong}>Configuration</Text>
    <Text color={theme.muted}>Provider discovery is read-only. Local writes require OPERATE.</Text>
    <Box height={1} />

    <Row label="Intent" focused={focusedIndex === 0}>{intentLabel(draftIntent)}</Row>
    <Row label="Radio" focused={focusedIndex === 1}>{radioLabel(draftRadio)}</Row>
    <Row label="Reservation" focused={focusedIndex === 2}>{draftReservation} minutes</Row>
    <Row label="Placement" focused={focusedIndex === 3}>{draftPlacement}</Row>
    <Row label="Save workspace defaults" focused={focusedIndex === 4}>
      {localBusy === 'defaults' ? 'Saving…' : mode === 'OPERATE' ? 'Enter' : 'Switch to OPERATE'}
    </Row>
    <Row label="Create configuration" focused={focusedIndex === 5}>
      {localBusy === 'experiment' ? 'Saving…' : mode === 'OPERATE' ? 'Enter' : 'Switch to OPERATE'}
    </Row>
    <Row label="Provider experiment" focused={focusedIndex === 6}>
      {providerValue(state, providerBusy, providerExperiments, providerCandidate)}
    </Row>
    <Row label="Bind provider" focused={focusedIndex === 7}>
      {bindValue(state, mode, providerBusy, providerCandidate)}
    </Row>

    <Box height={1} />
    <Row label="Mode">{mode}</Row>
    <Row label="Active experiment">{state.experiment}</Row>
    <Row label="SLICES project">{state.slicesProject}</Row>
    <Row label="R2Lab slice">{state.r2labSlice}</Row>
    <Row label="SSH identity">{state.sshIdentity}</Row>
    <Row label="Lifecycle">{state.lifecycle}</Row>

    {notice ? (
      <Box marginTop={1}>
        <Text color={theme.muted}>{notice}</Text>
      </Box>
    ) : null}
  </Box>
);
