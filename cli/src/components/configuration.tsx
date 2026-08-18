import React from 'react';
import {Box, Text} from 'ink';

import type {WorkbenchState} from '../model.js';
import {theme} from '../theme.js';

interface ConfigurationPanelProps {
  state: WorkbenchState;
}

const Row = ({label, children}: {label: string; children: React.ReactNode}) => (
  <Box marginBottom={1}>
    <Box width={24}>
      <Text color={theme.muted}>{label}</Text>
    </Box>
    <Text color={theme.bodyStrong}>{children}</Text>
  </Box>
);

const radioLabel = (value: WorkbenchState['radio']) => {
  if (value === 'physical') return 'Physical / R2Lab';
  if (value === 'virtual') return 'Virtual / RFSIM';
  return 'Automatic';
};

export const ConfigurationPanel = ({state}: ConfigurationPanelProps) => (
  <Box flexDirection="column" paddingX={1} paddingY={1}>
    <Text bold color={theme.bodyStrong}>Configuration</Text>
    <Text color={theme.muted}>Read-only local configuration. Provider resources are not changed.</Text>
    <Box height={1} />

    <Row label="Intent">{state.intent}</Row>
    <Row label="Radio">{radioLabel(state.radio)}</Row>
    <Row label="SLICES project">{state.slicesProject}</Row>
    <Row label="Provider experiment">{state.providerExperiment ?? 'Not bound'}</Row>
    <Row label="R2Lab slice">{state.r2labSlice}</Row>
    <Row label="SSH identity">{state.sshIdentity}</Row>
    <Row label="Reservation">{state.reservationMinutes} minutes</Row>
    <Row label="Placement">{state.placement}</Row>
    <Row label="Lifecycle">{state.lifecycle}</Row>
  </Box>
);
