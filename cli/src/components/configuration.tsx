import React from 'react';
import {Box, Text} from 'ink';

import type {ExperimentIntent} from '../backend/control.js';
import type {RadioMode, WorkbenchState} from '../model.js';
import {theme} from '../theme.js';

interface ConfigurationPanelProps {
  state: WorkbenchState;
  draftIntent: ExperimentIntent;
  draftRadio: RadioMode;
  focusedIndex: number;
  saving: boolean;
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

export const ConfigurationPanel = ({
  state,
  draftIntent,
  draftRadio,
  focusedIndex,
  saving,
  notice,
}: ConfigurationPanelProps) => (
  <Box flexDirection="column" paddingX={1} paddingY={1}>
    <Text bold color={theme.bodyStrong}>Configuration</Text>
    <Text color={theme.muted}>Changes create a new local experiment. Provider resources are not changed.</Text>
    <Box height={1} />

    <Row label="Intent" focused={focusedIndex === 0}>{intentLabel(draftIntent)}</Row>
    <Row label="Radio" focused={focusedIndex === 1}>{radioLabel(draftRadio)}</Row>
    <Row label="Create configuration" focused={focusedIndex === 2}>{saving ? 'Saving…' : 'Enter'}</Row>

    <Box height={1} />
    <Row label="Active experiment">{state.experiment}</Row>
    <Row label="SLICES project">{state.slicesProject}</Row>
    <Row label="Provider experiment">{state.providerExperiment ?? 'Not bound'}</Row>
    <Row label="R2Lab slice">{state.r2labSlice}</Row>
    <Row label="SSH identity">{state.sshIdentity}</Row>
    <Row label="Reservation">{state.reservationMinutes} minutes</Row>
    <Row label="Placement">{state.placement}</Row>
    <Row label="Lifecycle">{state.lifecycle}</Row>

    {notice ? (
      <Box marginTop={1}>
        <Text color={theme.muted}>{notice}</Text>
      </Box>
    ) : null}
  </Box>
);
