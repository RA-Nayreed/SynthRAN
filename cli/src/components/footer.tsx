import React from 'react';
import {Box, Text} from 'ink';

import {theme} from '../theme.js';

export const Footer = () => (
  <Box borderStyle="single" borderColor={theme.hairline} paddingX={1} marginTop={1}>
    <Text color={theme.muted}>Tab Phase   1–6 Jump   ↑↓ Control   ←→ Change   Enter Select   / Actions   m Mode   q Quit</Text>
  </Box>
);
