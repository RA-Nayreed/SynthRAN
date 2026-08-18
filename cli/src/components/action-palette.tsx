import React from 'react';
import {Box, Text} from 'ink';

import type {SectionLabel} from '../model.js';
import {theme} from '../theme.js';

export interface PaletteAction {
  label: string;
  section: SectionLabel;
}

interface ActionPaletteProps {
  actions: PaletteAction[];
  selectedIndex: number;
}

export const ActionPalette = ({actions, selectedIndex}: ActionPaletteProps) => (
  <Box flexDirection="column" paddingX={1} paddingY={1}>
    <Text bold color={theme.bodyStrong}>Actions</Text>
    <Text color={theme.muted}>Jump to a workbench surface</Text>
    <Box height={1} />
    {actions.map((action, index) => (
      <Text
        key={action.label}
        inverse={index === selectedIndex}
        color={index === selectedIndex ? undefined : theme.bodyStrong}
      >
        {index === selectedIndex ? '›' : ' '} {action.label}
      </Text>
    ))}
    <Box height={1} />
    <Text color={theme.muted}>↑↓ Select   Enter Open   Esc Close</Text>
  </Box>
);
