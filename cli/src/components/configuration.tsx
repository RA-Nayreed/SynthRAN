import React from 'react';
import {Box, Text} from 'ink';

import type {WorkbenchState} from '../mock.js';
import {theme} from '../theme.js';

interface ConfigurationPanelProps {
  state: WorkbenchState;
  focusedIndex: number;
  notice: string | null;
}

const Label = ({children, focused = false}: {children: React.ReactNode; focused?: boolean}) => (
  <Box width={24}>
    <Text color={focused ? theme.bodyStrong : theme.muted} bold={focused}>{focused ? '› ' : '  '}{children}</Text>
  </Box>
);

const Row = ({label, children, focused = false}: {label: string; children: React.ReactNode; focused?: boolean}) => (
  <Box marginBottom={1}>
    <Label focused={focused}>{label}</Label>
    <Text color={theme.bodyStrong}>{children}</Text>
  </Box>
);

export const ConfigurationPanel = ({state, focusedIndex, notice}: ConfigurationPanelProps) => (
  <Box flexDirection="column" paddingX={1} paddingY={1}>
    <Text bold color={theme.bodyStrong}>Configuration</Text>
    <Text color={theme.muted}>Mock controls only. Nothing on the provider is changed.</Text>
    <Box height={1} />

    <Row label="Intent">{state.intent}</Row>

    <Box marginBottom={1}>
      <Label focused={focusedIndex === 0}>Radio</Label>
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
    <Row label="Provider experiment" focused={focusedIndex === 1}>
      {state.providerExperiment ?? 'Not bound'}  [ Enter to cycle mock ]
    </Row>
    <Row label="R2Lab slice">{state.r2labSlice}</Row>
    <Row label="SSH identity" focused={focusedIndex === 2}>
      {state.sshIdentity}  [ Enter to cycle mock ]
    </Row>
    <Row label="Reservation" focused={focusedIndex === 3}>
      {state.reservationMinutes} minutes  [ ← / → ]
    </Row>

    <Box marginTop={1} justifyContent="flex-end">
      <Text inverse={focusedIndex === 4} bold={focusedIndex === 4}>  Save mock configuration  </Text>
    </Box>

    {notice ? (
      <Box marginTop={1}>
        <Text color={theme.success}>✓ {notice}</Text>
      </Box>
    ) : null}
  </Box>
);
