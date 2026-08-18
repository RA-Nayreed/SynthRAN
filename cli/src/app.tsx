import React from 'react';
import {Box, Spacer, Text, useApp, useInput} from 'ink';

import {ConfigurationPanel} from './components/configuration.js';
import {Footer} from './components/footer.js';
import {PhaseStrip} from './components/phase-strip.js';
import {mockWorkbenchState} from './mock.js';
import {theme} from './theme.js';

export const App = () => {
  const {exit} = useApp();
  const state = mockWorkbenchState;

  useInput(input => {
    if (input.toLowerCase() === 'q') {
      exit();
    }
  });

  return (
    <Box flexDirection="column" width="100%">
      <Box borderStyle="single" borderColor={theme.hairlineStrong} paddingX={2} flexDirection="column">
        <Box>
          <Text bold color={theme.bodyStrong}>SynthRAN</Text>
          <Spacer />
          <Text color={theme.muted}>{state.project}</Text>
          <Text color={theme.hairline}> · </Text>
          <Text color={theme.muted}>{state.experiment}</Text>
          <Text>   </Text>
          <Text inverse>{` ${state.mode} `}</Text>
        </Box>

        <PhaseStrip phases={state.phases} />

        <Box borderTop borderStyle="single" borderColor={theme.hairline}>
          <ConfigurationPanel state={state} />
        </Box>
      </Box>

      <Footer />

      <Box paddingX={1} marginTop={1}>
        <Text color={theme.muted}>Prototype · mock state · no provider or backend operations</Text>
      </Box>
    </Box>
  );
};
