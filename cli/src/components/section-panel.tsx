import React from 'react';
import {Box, Text} from 'ink';

import type {SectionLabel, WorkbenchState} from '../mock.js';
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
  if (section === 'Access') {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Access</Text>
        <Box height={1} />
        <Row label="SLICES identity" value="✓ rnayreed (mock)" />
        <Row label="SLICES project" value={`✓ ${state.slicesProject} (mock)`} />
        <Row label="R2Lab slice" value={`✓ ${state.r2labSlice} (mock)`} />
        <Row label="SSH identity" value={`✓ ${state.sshIdentity} (mock)`} />
      </Box>
    );
  }

  if (section === 'Resources') {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Resources</Text>
        <Box height={1} />
        <Row label="Reservation" value="None" />
        <Row label="Allocation" value="None" />
        <Row label="Radio" value={state.radio === 'physical' ? 'R2Lab physical' : 'RFSIM virtual'} />
        <Text color={theme.muted}>Provider discovery and reservation are not connected yet.</Text>
      </Box>
    );
  }

  if (section === 'Network') {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Network</Text>
        <Box height={1} />
        <Row label="Open5GS" value="○ Offline" />
        <Row label="gNB" value="○ Offline" />
        <Row label="UE" value="○ Offline" />
        <Row label="Path" value="○ Not proven" />
      </Box>
    );
  }

  if (section === 'Run') {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Run</Text>
        <Box height={1} />
        <Row label="Condition" value="Baseline" />
        <Row label="Validity" value="Waiting for a proven network path" />
        <Text color={theme.muted}>Experiment execution remains disabled in the mock workbench.</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color={theme.bodyStrong}>Evidence</Text>
      <Box height={1} />
      <Row label="Telemetry" value="—" />
      <Row label="RTT" value="—" />
      <Row label="Dataset" value="—" />
      <Text color={theme.muted}>Evidence appears here after a connected run.</Text>
    </Box>
  );
};
