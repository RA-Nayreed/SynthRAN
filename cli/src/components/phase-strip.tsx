import React from 'react';
import {Box, Text} from 'ink';

import type {Phase} from '../mock.js';
import {theme} from '../theme.js';

interface PhaseStripProps {
  phases: Phase[];
}

const marker = (phase: Phase): string => {
  if (phase.status === 'complete') return '✓';
  if (phase.status === 'active') return '●';
  return '○';
};

export const PhaseStrip = ({phases}: PhaseStripProps) => (
  <Box gap={3} marginTop={1} marginBottom={1}>
    {phases.map(phase => (
      <Text
        key={phase.label}
        color={phase.status === 'complete' ? theme.success : phase.status === 'active' ? theme.bodyStrong : theme.muted}
        bold={phase.status === 'active'}
      >
        {marker(phase)} {phase.label}
      </Text>
    ))}
  </Box>
);
