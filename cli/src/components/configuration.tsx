import React from 'react';
import {Box, Text} from 'ink';

import type {
  ExperimentIntent,
  RadioMode,
  WorkbenchMode,
  WorkbenchState,
} from '../model.js';
import {theme} from '../theme.js';

interface ConfigurationPanelProps {
  state: WorkbenchState;
  mode: WorkbenchMode;
  draftIntent: ExperimentIntent;
  draftRadio: RadioMode;
  focusedIndex: number;
  busy: boolean;
  notice: string | null;
}

const Row = ({label, children}: {label: string; children: React.ReactNode}) => (
  <Box marginBottom={1}>
    <Box width={24}>
      <Text color={theme.muted}>{label}</Text>
    </Box>
    <Text color={theme.bodyStrong}>{children}</Text>
  </Box>
);

const SelectableRow = ({
  label,
  value,
  focused,
}: {
  label: string;
  value: string;
  focused: boolean;
}) => (
  <Box marginBottom={1}>
    <Box width={24}>
      <Text color={focused ? theme.bodyStrong : theme.muted} bold={focused}>
        {focused ? '› ' : '  '}{label}
      </Text>
    </Box>
    <Text inverse={focused}>{` ${value} `}</Text>
  </Box>
);

const radioLabel = (value: RadioMode) => {
  if (value === 'physical') return 'Physical / R2Lab';
  if (value === 'virtual') return 'Virtual / RFSIM';
  return 'Automatic';
};

export const ConfigurationPanel = ({
  state,
  mode,
  draftIntent,
  draftRadio,
  focusedIndex,
  busy,
  notice,
}: ConfigurationPanelProps) => {
  if (state.experimentId !== null) {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Configuration</Text>
        <Text color={theme.muted}>Active experiment configuration is immutable in this view.</Text>
        <Box height={1} />
        <Row label="Experiment">{state.experimentId}</Row>
        <Row label="Intent">{state.intent}</Row>
        <Row label="Radio">{radioLabel(state.radio)}</Row>
        <Row label="SLICES project">{state.slicesProject}</Row>
        <Row label="Provider experiment">{state.providerExperiment ?? 'Not bound'}</Row>
        <Row label="R2Lab slice">{state.r2labSlice}</Row>
        <Row label="SSH identity">{state.sshIdentity}</Row>
        <Row label="Reservation">{state.reservationMinutes} minutes</Row>
        <Row label="Placement">{state.placement}</Row>
        <Row label="Lifecycle">{state.lifecycle}</Row>
        {notice ? <Text color={theme.success}>✓ {notice}</Text> : null}
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color={theme.bodyStrong}>Create local experiment</Text>
      <Text color={theme.muted}>
        This writes only the local SynthRAN workspace. Provider resources are not changed.
      </Text>
      <Box height={1} />

      <SelectableRow label="Intent" value={draftIntent} focused={focusedIndex === 0} />
      <SelectableRow label="Radio" value={radioLabel(draftRadio)} focused={focusedIndex === 1} />

      <Box marginTop={1} justifyContent="flex-end">
        <Text inverse={focusedIndex === 2} bold={focusedIndex === 2}>
          {busy ? '  Creating…  ' : '  Create local experiment  '}
        </Text>
      </Box>

      <Box marginTop={1}>
        <Text color={theme.muted}>
          {mode === 'OPERATE'
            ? 'OPERATE · Enter on Create writes the validated local configuration.'
            : 'OBSERVE · Press m to enable the local configuration write.'}
        </Text>
      </Box>
      {notice ? (
        <Box marginTop={1}>
          <Text color={theme.bodyStrong}>{notice}</Text>
        </Box>
      ) : null}
    </Box>
  );
};
