import React from 'react';
import {Box, Text} from 'ink';

import type {PlacementMode} from '../backend/control.js';
import type {RadioMode, WorkbenchState} from '../model.js';
import {theme} from '../theme.js';

interface ConfigurationPanelProps {
  state: WorkbenchState;
  draftProfile: string;
  draftRadio: RadioMode;
  draftPlacement: PlacementMode;
  draftCoreNode: string | null;
  draftRanNode: string | null;
  draftReservation: number;
  focusedIndex: number;
  localBusy: 'initializing' | 'profile' | 'defaults' | 'experiment' | null;
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

export const ConfigurationPanel = ({
  state,
  draftProfile,
  draftRadio,
  draftPlacement,
  draftCoreNode,
  draftRanNode,
  draftReservation,
  focusedIndex,
  localBusy,
  providerBusy,
  providerExperiments,
  providerCandidate,
  notice,
}: ConfigurationPanelProps) => {
  const physical = draftRadio === 'physical';
  const selectedProfile = state.profiles.find(profile => profile.name === draftProfile);
  const profileValue = localBusy === 'profile'
    ? 'Verifying and switching…'
    : draftProfile === state.profile
      ? `${draftProfile} · active`
      : `${draftProfile} · Enter to switch`;

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color={theme.bodyStrong}>Setup</Text>
      <Text color={theme.muted}>Account, SLICES experiment, 5G stack and exact resource choices.</Text>
      <Box height={1} />

      <Text bold color={theme.bodyStrong}>Account</Text>
      <Row label="Profile" focused={focusedIndex === 0}>{profileValue}</Row>
      <Row label="SLICES user">{selectedProfile?.slicesUsername ?? state.slicesIdentity ?? 'Not configured'}</Row>
      <Row label="SLICES project">{state.slicesProject}</Row>
      <Row label="SLICES experiment" focused={focusedIndex === 8}>
        {providerValue(state, providerBusy, providerExperiments, providerCandidate)}
      </Row>
      <Row label="Bind selection" focused={focusedIndex === 9}>
        {bindValue(state, providerBusy, providerCandidate)}
      </Row>

      <Box height={1} />
      <Text bold color={theme.bodyStrong}>5G network</Text>
      <Row label="Core">Open5GS</Row>
      <Row label="RAN">srsRAN</Row>
      <Row label="UE">srsUE</Row>
      <Row label="Radio" focused={focusedIndex === 1}>{radioLabel(draftRadio)}</Row>

      <Box height={1} />
      <Text bold color={theme.bodyStrong}>Resources</Text>
      <Row label="Node selection" focused={focusedIndex === 2}>
        {draftPlacement === 'manual' ? 'Manual' : 'Automatic'}
      </Row>
      <Row label="Core node" focused={focusedIndex === 3}>
        {draftPlacement === 'manual' ? (draftCoreNode ?? 'No node') : 'Selected safely at plan time'}
      </Row>
      <Row label="RAN node" focused={focusedIndex === 4}>
        {draftPlacement === 'manual' ? (draftRanNode ?? 'No node') : 'Selected safely at plan time'}
      </Row>
      <Row label="Reservation" focused={focusedIndex === 5}>{draftReservation} minutes</Row>
      <Row label="Save defaults" focused={focusedIndex === 6}>
        {localBusy === 'defaults' ? 'Saving…' : 'Enter'}
      </Row>
      <Row label="New network config" focused={focusedIndex === 7}>
        {localBusy === 'experiment' ? 'Creating…' : 'Enter'}
      </Row>

      {physical ? (
        <>
          <Box height={1} />
          <Text bold color={theme.bodyStrong}>Physical radio</Text>
          <Row label="Testbed">R2Lab</Row>
          <Row label="Slice">{selectedProfile?.r2labSlice ?? state.r2labSlice}</Row>
          <Row label="SSH identity">{selectedProfile?.identityName ?? state.sshIdentity}</Row>
          <Text color={theme.muted}>Physical execution remains unavailable until the R2Lab executor is connected.</Text>
        </>
      ) : null}

      <Box height={1} />
      <Row label="Active config">{state.experiment}</Row>
      <Row label="Status">{state.lifecycle}</Row>

      {notice ? (
        <Box marginTop={1}>
          <Text color={notice.toLowerCase().includes('could not') || notice.toLowerCase().includes('failed') || notice.toLowerCase().includes('cannot') ? theme.error : theme.muted}>
            {notice}
          </Text>
        </Box>
      ) : null}
    </Box>
  );
};
