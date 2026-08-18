import React from 'react';
import {Box, Text} from 'ink';

import type {SectionLabel, WorkbenchState} from '../model.js';
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

export const SectionPanel = ({section, state}: SectionPanelProps) => {
  if (section === 'Experiment') {
    const networkReady = state.lifecycle === 'PATH_PROVEN' || state.lifecycle === 'EXPERIMENT_RUNNING';
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Experiment</Text>
        <Box height={1} />
        <Row label="Scenario" value="IoT → 5G" />
        <Row label="Network" value={networkReady ? '✓ PATH PROVEN' : `○ ${state.lifecycle}`} />
        <Row label="Baseline" value={networkReady ? 'Available through scripted workflow' : 'Requires PATH PROVEN'} />
        <Row label="Congestion" value={networkReady ? 'Available through scripted workflow' : 'Requires PATH PROVEN'} />
        <Text color={theme.muted}>Interactive experiment execution will appear here when that executor is connected.</Text>
      </Box>
    );
  }

  if (section === 'Data') {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Data</Text>
        <Box height={1} />
        <Row label="Network status" value={state.lifecycle} />
        <Row label="Observations" value={String(state.observations.length)} />
        <Row label="Collection" value="Available through scripted workflow" />
        <Text color={theme.muted}>JSONL, Parquet and provenance will appear here when interactive collection is connected.</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color={theme.bodyStrong}>{section}</Text>
      <Box height={1} />
      <Row label="Status" value={state.lifecycle} />
    </Box>
  );
};
