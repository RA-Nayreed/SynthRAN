import React from 'react';
import {Box, Text} from 'ink';

import type {Section} from '../mock.js';
import {theme} from '../theme.js';

interface SectionStripProps {
  sections: Section[];
}

const marker = (section: Section): string => {
  if (section.status === 'complete') return '✓';
  if (section.status === 'active') return '●';
  return '○';
};

export const SectionStrip = ({sections}: SectionStripProps) => (
  <Box gap={3} marginTop={1} marginBottom={1}>
    {sections.map(section => (
      <Text
        key={section.label}
        color={section.status === 'complete' ? theme.success : section.status === 'active' ? theme.bodyStrong : theme.muted}
        bold={section.status === 'active'}
      >
        {marker(section)} {section.label}
      </Text>
    ))}
  </Box>
);
