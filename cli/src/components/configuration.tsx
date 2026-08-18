import React from 'react';
import {Box, Text} from 'ink';

import type {RadioMode, WorkbenchState} from '../model.js';
import {theme} from '../theme.js';

interface ConfigurationPanelProps {
  state: WorkbenchState;
  draftRadio: RadioMode;
  draftReservation: number;
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
  return 'Virtual / RFSIM';
};

const providerValue = (
  state: WorkbenchState,
  providerBusy: 'loading' | 'binding' | null,
  providerExperiments: string[] | null,
  providerCandidate: string | null,
) => {
  if (state.providerExperiment) return `${state.providerExperiment} · bound`;
  if (!state.hasActiveExperiment) return 'Create network configuration first';
  if (providerBusy === 'loading') return 'Reading SLICES experiments…';
  if (providerExperiments === null) return 'Enter to load existing experiments';
  if (providerExperiments.length === 0) return 'No experiments available';
  return providerCandidate ?? 'No selection';
};

const bindValue = (
  state: WorkbenchState,
  providerBusy: 'loading' | 'binding' | null,
  providerCandidate: string | null,
) => {
  if (state.providerExperiment) return 'Already bound';
  if (!state.hasActiveExperiment) return 'Unavailable';
  if (providerBusy === 'binding') return 'Verifying and binding…';
  if (!providerCandidate) return 'Select SLICES experiment first';
  return 'Enter';
};

const placementValue = (state: WorkbenchState) =>
  state.placement === 'automatic'
    ? 'Automatic · prefers sopnode-f2 / sopnode-f3'
    : 'Manual';

export const ConfigurationPanel = ({
  state,
  draftRadio,
  draftReservation,
  focusedIndex,
  localBusy,
  providerBusy,
  providerExperiments,
  providerCandidate,
  notice,
}: ConfigurationPanelProps) => {
  const physical = draftRadio === 'physical';

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color={theme.bodyStrong}>Setup</Text>
      <Text color={theme.muted}>Account, SLICES experiment, network stack and resource defaults.</Text>
      <Box height={1} />

      <Text bold color={theme.bodyStrong}>Account</Text>
      <Row label="Profile">{state.profile}</Row>
      <Row label="SLICES user">{state.slicesIdentity ?? 'Not configured'}</Row>
      <Row label="SLICES project">{state.slicesProject}</Row>
      <Row label="SLICES experiment" focused={focusedIndex === 4}>
        {providerValue(state, providerBusy, providerExperiments, providerCandidate)}
      </Row>
      <Row label="Bind selection" focused={focusedIndex === 5}>
        {bindValue(state, providerBusy, providerCandidate)}
      </Row>

      <Box height={1} />
      <Text bold color={theme.bodyStrong}>5G network</Text>
      <Row label="Core">Open5GS</Row>
      <Row label="RAN">srsRAN</Row>
      <Row label="UE">srsUE</Row>
      <Row label="Radio" focused={focusedIndex === 0}>{radioLabel(draftRadio)}</Row>

      <Box height={1} />
      <Text bold color={theme.bodyStrong}>Resources</Text>
      <Row label="Node selection">{placementValue(state)}</Row>
      <Row label="Reservation" focused={focusedIndex === 1}>{draftReservation} minutes</Row>
      <Row label="Save defaults" focused={focusedIndex === 2}>
        {localBusy === 'defaults' ? 'Saving…' : 'Enter'}
      </Row>
      <Row label="New network config" focused={focusedIndex === 3}>
        {localBusy === 'experiment' ? 'Creating…' : 'Enter'}
      </Row>

      {physical ? (
        <>
          <Box height={1} />
          <Text bold color={theme.bodyStrong}>Physical radio</Text>
          <Row label="Testbed">R2Lab</Row>
          <Row label="Slice">{state.r2labSlice}</Row>
          <Row label="SSH identity">{state.sshIdentity}</Row>
          <Text color={theme.muted}>Physical execution remains unavailable until the R2Lab executor is connected.</Text>
        </>
      ) : null}

      <Box height={1} />
      <Row label="Active config">{state.experiment}</Row>
      <Row label="Status">{state.lifecycle}</Row>

      {notice ? (
        <Box marginTop={1}>
          <Text color={notice.toLowerCase().includes('could not') || notice.toLowerCase().includes('failed') ? theme.error : theme.muted}>
            {notice}
          </Text>
        </Box>
      ) : null}
    </Box>
  );
};
