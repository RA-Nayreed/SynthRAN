import React from 'react';
import {Box, Text} from 'ink';

import type {ObservationView, SectionLabel, WorkbenchState} from '../model.js';
import {theme} from '../theme.js';

interface SectionPanelProps {
  section: SectionLabel;
  state: WorkbenchState;
}

const Row = ({label, value}: {label: string; value: string}) => (
  <Box marginBottom={1}>
    <Box width={24}><Text color={theme.muted}>{label}</Text></Box>
    <Text color={theme.bodyStrong}>{value}</Text>
  </Box>
);

const observation = (state: WorkbenchState, name: string): ObservationView | undefined =>
  state.observations.find(item => item.name === name);

const observedValue = (item: ObservationView | undefined) => {
  if (!item) return '—';
  return `${item.fresh ? '●' : '○'} ${item.state}${item.fresh ? '' : ' · stale'}`;
};

export const SectionPanel = ({section, state}: SectionPanelProps) => {
  if (section === 'Access') {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Access</Text>
        <Box height={1} />
        <Row
          label="SLICES identity"
          value={`${state.slicesAccessFresh ? '✓' : '○'} ${state.slicesIdentity ?? 'Not configured'}`}
        />
        <Row
          label="SLICES project"
          value={`${state.slicesAccessFresh ? '✓' : '○'} ${state.slicesProject}`}
        />
        <Row
          label="R2Lab access"
          value={state.r2labConfigured ? `${state.r2labAccessFresh ? '✓' : '○'} ${state.r2labSlice}` : 'Not configured'}
        />
        <Row label="SSH identity" value={state.sshIdentity} />
      </Box>
    );
  }

  if (section === 'Resources') {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Resources</Text>
        <Box height={1} />
        <Row label="Lifecycle" value={state.lifecycle} />
        <Row label="Reservation" value={observedValue(observation(state, 'reservation'))} />
        <Row label="Allocation" value={observedValue(observation(state, 'allocation'))} />
        <Row label="Preparation" value={observedValue(observation(state, 'preparation'))} />
        <Row label="Next action" value={state.nextSteps[0] ?? '—'} />
        {state.blocks.length > 0 ? <Row label="Blocked" value={state.blocks[0]} /> : null}
      </Box>
    );
  }

  if (section === 'Network') {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Network</Text>
        <Box height={1} />
        <Row label="Core" value={observedValue(observation(state, 'core'))} />
        <Row label="RAN / gNB" value={observedValue(observation(state, 'ran'))} />
        <Row label="UE" value={observedValue(observation(state, 'ue'))} />
        <Row label="PDU" value={observedValue(observation(state, 'pdu'))} />
        <Row label="UPF" value={observedValue(observation(state, 'upf'))} />
        <Row label="Path" value={observedValue(observation(state, 'path'))} />
        <Row label="Lifecycle" value={state.lifecycle} />
      </Box>
    );
  }

  if (section === 'Run') {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Run</Text>
        <Box height={1} />
        <Row label="Lifecycle" value={state.lifecycle} />
        <Row label="Intent" value={state.intent} />
        <Row label="Next action" value={state.nextSteps[0] ?? '—'} />
        <Text color={theme.muted}>Experiment execution is not available through this read-only connection.</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color={theme.bodyStrong}>Evidence</Text>
      <Box height={1} />
      <Row label="Lifecycle" value={state.lifecycle} />
      <Row label="Observations" value={String(state.observations.length)} />
      <Text color={theme.muted}>Evidence collection is not available through this read-only connection.</Text>
    </Box>
  );
};
