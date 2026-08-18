import React, {useEffect, useState} from 'react';
import {Box, Spacer, Text, useApp, useInput} from 'ink';

import {readLocalSnapshot} from './backend/control.js';
import {initialSection, toWorkbenchState} from './backend/workbench.js';
import {ActionPalette, type PaletteAction} from './components/action-palette.js';
import {ConfigurationPanel} from './components/configuration.js';
import {Footer} from './components/footer.js';
import {SectionPanel} from './components/section-panel.js';
import {SectionStrip} from './components/section-strip.js';
import {sectionLabels, type SectionLabel, type WorkbenchState} from './model.js';
import {theme} from './theme.js';

const actions: PaletteAction[] = [
  {label: 'Review access', section: 'Access'},
  {label: 'Review configuration', section: 'Configure'},
  {label: 'Inspect resources', section: 'Resources'},
  {label: 'Inspect network', section: 'Network'},
  {label: 'Open run view', section: 'Run'},
  {label: 'Review evidence', section: 'Evidence'},
];

const wrap = (value: number, length: number) => (value + length) % length;

export const App = () => {
  const {exit} = useApp();
  const [activeSection, setActiveSection] = useState<SectionLabel>('Access');
  const [state, setState] = useState<WorkbenchState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteIndex, setPaletteIndex] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState(null);
    setLoadError(null);
    readLocalSnapshot()
      .then(snapshot => {
        if (cancelled) return;
        setState(toWorkbenchState(snapshot));
        setActiveSection(initialSection(snapshot));
      })
      .catch(error => {
        if (cancelled) return;
        setState(null);
        setLoadError(error instanceof Error ? error.message : 'SynthRAN local state could not be loaded');
      });
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  const moveSection = (delta: number) => {
    const current = sectionLabels.indexOf(activeSection);
    setActiveSection(sectionLabels[wrap(current + delta, sectionLabels.length)]);
  };

  useInput((input, key) => {
    if ((key.ctrl && input === 'c') || input.toLowerCase() === 'q') {
      exit();
      return;
    }

    if (input.toLowerCase() === 'r') {
      setPaletteOpen(false);
      setReloadToken(value => value + 1);
      return;
    }

    if (state === null) return;

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
      }
      return;
    }

    if (input === '/') {
      setPaletteOpen(true);
      setPaletteIndex(0);
      return;
    }

    if (/^[1-6]$/.test(input)) {
      setActiveSection(sectionLabels[Number(input) - 1]);
      return;
    }

    if (key.tab) {
      moveSection(key.shift ? -1 : 1);
    }
  });

  const headerProject = state?.project ?? 'local workspace';
  const headerExperiment = state?.experiment ?? 'reading state';

  return (
    <Box flexDirection="column" width="100%">
      <Box borderStyle="single" borderColor={theme.hairlineStrong} paddingX={2} flexDirection="column">
        <Box>
          <Text bold color={theme.bodyStrong}>SynthRAN</Text>
          <Spacer />
          <Text color={theme.muted}>{headerProject}</Text>
          <Text color={theme.hairline}> · </Text>
          <Text color={theme.muted}>{headerExperiment}</Text>
          <Text>   </Text>
          <Text inverse> OBSERVE </Text>
        </Box>

        {state ? (
          <SectionStrip sections={sectionLabels} selected={activeSection} completed={state.completedSections} />
        ) : null}

        <Box borderTop borderStyle="single" borderColor={theme.hairline}>
          {loadError ? (
            <Box flexDirection="column" paddingX={1} paddingY={1}>
              <Text bold color={theme.error}>Local state unavailable</Text>
              <Text color={theme.muted}>{loadError}</Text>
              <Box height={1} />
              <Text color={theme.bodyStrong}>Press r to retry or q to quit.</Text>
            </Box>
          ) : state === null ? (
            <Box paddingX={1} paddingY={1}>
              <Text color={theme.muted}>Reading local SynthRAN state…</Text>
            </Box>
          ) : paletteOpen ? (
            <ActionPalette actions={actions} selectedIndex={paletteIndex} />
          ) : activeSection === 'Configure' ? (
            <ConfigurationPanel state={state} />
          ) : (
            <SectionPanel section={activeSection} state={state} />
          )}
        </Box>
      </Box>

      <Footer />

      <Box paddingX={1} marginTop={1}>
        <Text color={theme.muted}>Read-only local state · no provider operations</Text>
      </Box>
    </Box>
  );
};
