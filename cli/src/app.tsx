import React, {useState} from 'react';
import {Box, Spacer, Text, useApp, useInput} from 'ink';

import {ActionPalette, type PaletteAction} from './components/action-palette.js';
import {ConfigurationPanel} from './components/configuration.js';
import {Footer} from './components/footer.js';
import {SectionPanel} from './components/section-panel.js';
import {SectionStrip} from './components/section-strip.js';
import {mockWorkbenchState, sectionLabels, type SectionLabel} from './mock.js';
import {theme} from './theme.js';

const actions: PaletteAction[] = [
  {label: 'Review access', section: 'Access'},
  {label: 'Configure experiment', section: 'Configure'},
  {label: 'Inspect resources', section: 'Resources'},
  {label: 'Inspect network', section: 'Network'},
  {label: 'Open run controls', section: 'Run'},
  {label: 'Review evidence', section: 'Evidence'},
];

const wrap = (value: number, length: number) => (value + length) % length;

export const App = () => {
  const {exit} = useApp();
  const [activeSection, setActiveSection] = useState<SectionLabel>('Configure');
  const [state, setState] = useState(mockWorkbenchState);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteIndex, setPaletteIndex] = useState(0);
  const [configFocus, setConfigFocus] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);

  const moveSection = (delta: number) => {
    const current = sectionLabels.indexOf(activeSection);
    setActiveSection(sectionLabels[wrap(current + delta, sectionLabels.length)]);
    setNotice(null);
  };

  useInput((input, key) => {
    if ((key.ctrl && input === 'c') || input.toLowerCase() === 'q') {
      exit();
      return;
    }

    if (paletteOpen) {
      if (key.escape) {
        setPaletteOpen(false);
        return;
      }
      if (key.upArrow) {
        setPaletteIndex(index => wrap(index - 1, actions.length));
        return;
      }
      if (key.downArrow) {
        setPaletteIndex(index => wrap(index + 1, actions.length));
        return;
      }
      if (key.return) {
        setActiveSection(actions[paletteIndex].section);
        setPaletteOpen(false);
        setNotice(null);
      }
      return;
    }

    if (input === '/') {
      setPaletteOpen(true);
      setPaletteIndex(0);
      return;
    }

    if (input === 'm') {
      setState(current => ({...current, mode: current.mode === 'OBSERVE' ? 'OPERATE' : 'OBSERVE'}));
      setNotice(null);
      return;
    }

    if (/^[1-6]$/.test(input)) {
      setActiveSection(sectionLabels[Number(input) - 1]);
      setNotice(null);
      return;
    }

    if (key.tab) {
      moveSection(key.shift ? -1 : 1);
      return;
    }

    if (activeSection !== 'Configure') return;

    if (key.upArrow) {
      setConfigFocus(index => wrap(index - 1, 5));
      setNotice(null);
      return;
    }
    if (key.downArrow) {
      setConfigFocus(index => wrap(index + 1, 5));
      setNotice(null);
      return;
    }

    if (configFocus === 0 && (key.leftArrow || key.rightArrow || key.return)) {
      setState(current => ({...current, radio: current.radio === 'physical' ? 'virtual' : 'physical'}));
      setNotice(null);
      return;
    }

    if (configFocus === 1 && key.return) {
      setState(current => ({
        ...current,
        providerExperiment: current.providerExperiment === null ? 'example-provider' : null,
      }));
      setNotice(null);
      return;
    }

    if (configFocus === 2 && key.return) {
      setState(current => ({
        ...current,
        sshIdentity: current.sshIdentity === 'id_r2lab' ? 'id_ed25519' : 'id_r2lab',
      }));
      setNotice(null);
      return;
    }

    if (configFocus === 3 && (key.leftArrow || key.rightArrow)) {
      setState(current => ({
        ...current,
        reservationMinutes: Math.min(360, Math.max(30, current.reservationMinutes + (key.rightArrow ? 30 : -30))),
      }));
      setNotice(null);
      return;
    }

    if (configFocus === 4 && key.return) {
      setNotice('Mock configuration saved in memory');
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

        <SectionStrip sections={sectionLabels} selected={activeSection} completed={state.completedSections} />

        <Box borderTop borderStyle="single" borderColor={theme.hairline}>
          {paletteOpen ? (
            <ActionPalette actions={actions} selectedIndex={paletteIndex} />
          ) : activeSection === 'Configure' ? (
            <ConfigurationPanel state={state} focusedIndex={configFocus} notice={notice} />
          ) : (
            <SectionPanel section={activeSection} state={state} />
          )}
        </Box>
      </Box>

      <Footer />

      <Box paddingX={1} marginTop={1}>
        <Text color={theme.muted}>Prototype · mock state · no provider or backend operations</Text>
      </Box>
    </Box>
  );
};
