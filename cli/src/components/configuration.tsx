import React from 'react';
import {Box, Text} from 'ink';

import type {WorkbenchState} from '../mock.js';
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

export const ConfigurationPanel = ({state}: ConfigurationPanelProps) => (
  <Box flexDirection="column" paddingX={1} paddingY={1}>
    <Text bold color={theme.bodyStrong}>Configuration</Text>
    <Box height={1} />

    <Row label="Intent">{state.intent}</Row>

    <Box marginBottom={1}>
      <Box width={24}>
        <Text color={theme.muted}>Radio</Text>
      </Box>
      <Box flexDirection="column">
        <Text color={state.radio === 'virtual' ? theme.bodyStrong : theme.muted}>
          {state.radio === 'virtual' ? '●' : '○'} Virtual / RFSIM
        </Text>
        <Text color={state.radio === 'physical' ? theme.bodyStrong : theme.muted}>
          {state.radio === 'physical' ? '●' : '○'} Physical / R2Lab
        </Text>
      </Box>
    </Box>

    <Row label="SLICES project">{state.slicesProject}</Row>
    <Row label="Provider experiment">
      {state.providerExperiment ?? 'Not bound  [ Select ]'}
    </Row>
    <Row label="R2Lab slice">{state.r2labSlice}</Row>
    <Row label="SSH identity">{state.sshIdentity}  [ Change ]</Row>
    <Row label="Reservation">{state.reservationMinutes} minutes  [ Change ]</Row>

    <Box marginTop={1} justifyContent="flex-end">
      <Text inverse>  Save configuration  </Text>
    </Box>
  </Box>
);
