import React, {useEffect, useRef, useState} from 'react';
import {Box, Spacer, Text, useApp, useInput} from 'ink';

import {
  createLocalExperiment,
  readLocalSnapshot,
} from './backend/control.js';
import {
  allowedRadioModes,
  cycleValue,
  recommendedRadioForIntent,
} from './backend/configuration.js';
import {initialSection, toWorkbenchState} from './backend/workbench.js';
import {ActionPalette, type PaletteAction} from './components/action-palette.js';
import {ConfigurationPanel} from './components/configuration.js';
import {Footer} from './components/footer.js';
import {SectionPanel} from './components/section-panel.js';
import {SectionStrip} from './components/section-strip.js';
import {
  experimentIntents,
  sectionLabels,
  type ExperimentIntent,
  type RadioMode,
  type SectionLabel,
  type WorkbenchMode,
  type WorkbenchState,
} from './model.js';
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
  const [mode, setMode] = useState<WorkbenchMode>('OBSERVE');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteIndex, setPaletteIndex] = useState(0);
  const [configFocus, setConfigFocus] = useState(0);
  const [draftIntent, setDraftIntent] = useState<ExperimentIntent>('virtual-5g');
  const [draftRadio, setDraftRadio] = useState<RadioMode>('virtual');
  const [configBusy, setConfigBusy] = useState(false);
  const [configNotice, setConfigNotice] = useState<string | null>(null);
  const createController = useRef<AbortController | null>(null);

  useEffect(() => {
    const requestController = new AbortController();
    let cancelled = false;
    setState(null);
    setLoadError(null);
    readLocalSnapshot(requestController.signal)
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
      requestController.abort();
    };
  }, [reloadToken]);

  useEffect(
    () => () => {
      createController.current?.abort();
    },
    [],
  );

  const selectSection = (section: SectionLabel) => {
    setActiveSection(section);
    setMode('OBSERVE');
    setConfigNotice(null);
  };

  const moveSection = (delta: number) => {
    const current = sectionLabels.indexOf(activeSection);
    selectSection(sectionLabels[wrap(current + delta, sectionLabels.length)]);
  };

  const submitLocalExperiment = () => {
    if (state === null || state.experimentId !== null || configBusy) return;
    if (mode !== 'OPERATE') {
      setConfigNotice('Switch to OPERATE with m before creating the local experiment.');
      return;
    }

    const controller = new AbortController();
    createController.current?.abort();
    createController.current = controller;
    setConfigBusy(true);
    setConfigNotice('Creating validated local experiment…');

    createLocalExperiment(draftIntent, draftRadio, controller.signal)
      .then(result => {
        if (createController.current !== controller) return;
        setState(toWorkbenchState(result.snapshot));
        setActiveSection('Configure');
        setMode('OBSERVE');
        setConfigNotice(`Created ${result.experiment_id}.`);
      })
      .catch(error => {
        if (createController.current !== controller) return;
        setConfigNotice(
          error instanceof Error ? error.message : 'Local experiment creation failed.',
        );
      })
      .finally(() => {
        if (createController.current !== controller) return;
        createController.current = null;
        setConfigBusy(false);
      });
  };

  useInput((input, key) => {
    if ((key.ctrl && input === 'c') || input.toLowerCase() === 'q') {
      createController.current?.abort();
      exit();
      return;
    }

    if (input.toLowerCase() === 'r' && !configBusy && (state !== null || loadError !== null)) {
      setPaletteOpen(false);
      setMode('OBSERVE');
      setConfigNotice(null);
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
        selectSection(actions[paletteIndex].section);
        setPaletteOpen(false);
      }
      return;
    }

    const creating = activeSection === 'Configure' && state.experimentId === null;
    if (input.toLowerCase() === 'm' && creating && !configBusy) {
      setMode(current => (current === 'OBSERVE' ? 'OPERATE' : 'OBSERVE'));
      setConfigNotice(null);
      return;
    }

    if (input === '/') {
      setPaletteOpen(true);
      setPaletteIndex(0);
      return;
    }

    if (/^[1-6]$/.test(input)) {
      selectSection(sectionLabels[Number(input) - 1]);
      return;
    }

    if (creating && !configBusy) {
      if (key.upArrow) {
        setConfigFocus(index => wrap(index - 1, 3));
        setConfigNotice(null);
        return;
      }
      if (key.downArrow) {
        setConfigFocus(index => wrap(index + 1, 3));
        setConfigNotice(null);
        return;
      }
      if (configFocus === 0 && (key.leftArrow || key.rightArrow)) {
        const nextIntent = cycleValue(
          experimentIntents,
          draftIntent,
          key.rightArrow ? 1 : -1,
        );
        setDraftIntent(nextIntent);
        setDraftRadio(recommendedRadioForIntent(nextIntent));
        setConfigNotice(null);
        return;
      }
      if (configFocus === 1 && (key.leftArrow || key.rightArrow)) {
        setDraftRadio(
          cycleValue(
            allowedRadioModes(draftIntent),
            draftRadio,
            key.rightArrow ? 1 : -1,
          ),
        );
        setConfigNotice(null);
        return;
      }
      if (configFocus === 2 && key.return) {
        submitLocalExperiment();
        return;
      }
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
          <Text inverse>{` ${mode} `}</Text>
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
            <ConfigurationPanel
              state={state}
              mode={mode}
              draftIntent={draftIntent}
              draftRadio={draftRadio}
              focusedIndex={configFocus}
              busy={configBusy}
              notice={configNotice}
            />
          ) : (
            <SectionPanel section={activeSection} state={state} />
          )}
        </Box>
      </Box>

      <Footer />

      <Box paddingX={1} marginTop={1}>
        <Text color={theme.muted}>
          Local configuration only · provider operations unavailable
        </Text>
      </Box>
    </Box>
  );
};
