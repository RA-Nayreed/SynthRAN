import React from 'react';
import {Box, Text} from 'ink';

import type {SectionLabel} from '../model.js';
import {theme} from '../theme.js';

interface SectionStripProps {
  sections: SectionLabel[];
  selected: SectionLabel;
  completed: readonly SectionLabel[];
}

export const SectionStrip = ({sections, selected, completed}: SectionStripProps) => (
  <Box gap={3} marginTop={1} marginBottom={1}>
    {sections.map(section => {
      const isSelected = section === selected;
      const isComplete = completed.includes(section);
      const marker = isSelected ? '●' : isComplete ? '✓' : '○';
      const color = isSelected ? theme.bodyStrong : isComplete ? theme.success : theme.muted;
      return (
        <Text key={section} color={color} bold={isSelected}>
          {marker} {section}
        </Text>
      );
    })}
  </Box>
);
