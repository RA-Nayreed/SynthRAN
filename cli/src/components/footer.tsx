import React from 'react';
import {Box, Text} from 'ink';

import {theme} from '../theme.js';

export const Footer = () => (
  <Box borderStyle="single" borderColor={theme.hairline} paddingX={1} marginTop={1}>
    <Text color={theme.muted}>↑↓ Navigate   Enter Select   Tab Next   / Actions   ? Help   q Quit</Text>
  </Box>
);
