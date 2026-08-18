import React from 'react';
import {Box, Text} from 'ink';

import {theme} from '../theme.js';

export const Footer = () => (
  <Box borderStyle="single" borderColor={theme.hairline} paddingX={1} marginTop={1}>
    <Text color={theme.muted}>↑↓ Focus   ←→ Change   Enter Select   m Mode   Tab Navigate   / Actions   r Reload   q Quit</Text>
  </Box>
);
