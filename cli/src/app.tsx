import React, {useEffect, useRef, useState} from 'react';
import {Box, Spacer, Text, useApp, useInput} from 'ink';

import {
  createLocalExperiment,
  readLocalSnapshot,
  type ControlSnapshot,
  type ExperimentIntent,
} from './backend/control.js';
import {initialSection, toWorkbenchState} from './backend/workbench.js';
import {ActionPalette, type PaletteAction} from './components/action-palette.js';
import {ConfigurationPanel} from './components/configuration.js';
import {Footer} from './components/footer.js';
import {SectionPanel} from './components/section-panel.js';
import {SectionStrip} from './components/section-strip.js';
import {sectionLabels, type RadioMode, type SectionLabel, type WorkbenchState} from './model.js';
import {theme} from './theme.js';

const actions: PaletteAction[] = [
  {label: 'Review access', section: 'Access'},
  {label: 'Review configuration', section: 'Configure'},
  {label: 'Inspect resources', section: 'Resources'},
  {label: 'Inspect network', section: 'Network'},
  {label: 'Open run view', section: 'Run'},
  {label: 'Review evidence', section: 'Evidence'},
];

const intentOptions: ExperimentIntent[] = [
  'iot-to-5g',
  'virtual-5g',
  'physical-5g',
  'open-ran',
  'unspecified',
];
const allRadioOptions: RadioMode[] = ['virtual', 'physical', 'automatic'];

const wrap = (value: number, length: number) => (value + length) % length;
const cycle = <T,>(items: readonly T[], current: T, delta: number): T => {
  const index = Math.max(0, items.indexOf(current));
  return items[wrap(index + delta, items.length)];
};

const isIntent = (value: string | null): value is ExperimentIntent =>
  value !== null && intentOptions.includes(value as ExperimentIntent);

const isRadio = (value: string | null): value is RadioMode =>
  value === 'automatic' || value === 'virtual' || value === 'physical';

const radioOptionsFor = (intent: ExperimentIntent): RadioMode[] => {
  if (intent === 'virtual-5g') return ['virtual', 'automatic'];
  if (intent === 'physical-5g') return ['physical', 'automatic'];
  return allRadioOptions;
};

const draftFromSnapshot = (snapshot: ControlSnapshot) => ({
  intent: isIntent(snapshot.experiment.intent) ? snapshot.experiment.intent : 'iot-to-5g' as ExperimentIntent,
  radio: isRadio(snapshot.experiment.radio_mode) ? snapshot.experiment.radio_mode : 'virtual' as RadioMode,
});

export const App = () => {
  const {exit} = useApp();
  const [activeSection, setActiveSection] = useState<SectionLabel>('Access');
  const [state, setState] = useState<WorkbenchState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteIndex, setPaletteIndex] = useState(0);
  const [configFocus, setConfigFocus] = useState(0);
  const [draftIntent, setDraftIntent] = useState<ExperimentIntent>('iot-to-5g');
  const [draftRadio, setDraftRadio] = useState<RadioMode>('virtual');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const saveRequest = useRef<AbortController | null>(null);

  const applySnapshot = (snapshot: ControlSnapshot, chooseSection: boolean) => {
    const next = toWorkbenchState(snapshot);
    const draft = draftFromSnapshot(snapshot);
    setState(next);
    setDraftIntent(draft.intent);
    setDraftRadio(draft.radio);
    if (chooseSection) setActiveSection(initialSection(snapshot));
  };

  useEffect(() => {
    const requestController = new AbortController();
    let cancelled = false;
    setState(null);
    setLoadError(null);
    setNotice(null);
    readLocalSnapshot(requestController.signal)
      .then(snapshot => {
        if (cancelled) return;
        applySnapshot(snapshot, true);
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
      saveRequest.current?.abort();
    },
    [],
  );

  const moveSection = (delta: number) => {
    const current = sectionLabels.indexOf(activeSection);
    setActiveSection(sectionLabels[wrap(current + delta, sectionLabels.length)]);
    setNotice(null);
  };

  const changeIntent = (delta: number) => {
    const nextIntent = cycle(intentOptions, draftIntent, delta);
    const validRadios = radioOptionsFor(nextIntent);
    setDraftIntent(nextIntent);
    if (!validRadios.includes(draftRadio)) setDraftRadio('automatic');
    setNotice(null);
  };

  const changeRadio = (delta: number) => {
    const options = radioOptionsFor(draftIntent);
    setDraftRadio(cycle(options, draftRadio, delta));
    setNotice(null);
  };

  const saveConfiguration = () => {
    if (saving) return;
    const requestController = new AbortController();
    saveRequest.current?.abort();
    saveRequest.current = requestController;
    setSaving(true);
    setNotice(null);

    createLocalExperiment(
      {intent: draftIntent, radioMode: draftRadio},
      requestController.signal,
    )
      .then(snapshot => {
        if (requestController.signal.aborted) return;
        applySnapshot(snapshot, false);
        setActiveSection('Configure');
        setNotice(
          snapshot.experiment.id
            ? `Created ${snapshot.experiment.id}. Provider experiment is not bound.`
            : 'Local configuration was created.',
        );
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        setNotice(
          error instanceof Error
            ? error.message
            : 'SynthRAN local configuration could not be created',
        );
      })
      .finally(() => {
        if (saveRequest.current === requestController) {
          saveRequest.current = null;
          setSaving(false);
        }
      });
  };

  useInput((input, key) => {
    if ((key.ctrl && input === 'c') || input.toLowerCase() === 'q') {
      saveRequest.current?.abort();
      exit();
      return;
    }

    if (saving) return;

    if (input.toLowerCase() === 'r' && (state !== null || loadError !== null)) {
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
        setNotice(null);
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
      setNotice(null);
      return;
    }

    if (activeSection === 'Configure') {
      if (key.upArrow) {
        setConfigFocus(index => wrap(index - 1, 3));
        return;
      }
      if (key.downArrow) {
        setConfigFocus(index => wrap(index + 1, 3));
        return;
      }
      if (configFocus === 0 && (key.leftArrow || key.rightArrow || key.return)) {
        changeIntent(key.leftArrow ? -1 : 1);
        return;
      }
      if (configFocus === 1 && (key.leftArrow || key.rightArrow || key.return)) {
        changeRadio(key.leftArrow ? -1 : 1);
        return;
      }
      if (configFocus === 2 && key.return) {
        saveConfiguration();
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
            <ConfigurationPanel
              state={state}
              draftIntent={draftIntent}
              draftRadio={draftRadio}
              focusedIndex={configFocus}
              saving={saving}
              notice={notice}
            />
          ) : (
            <SectionPanel section={activeSection} state={state} />
          )}
        </Box>
      </Box>

      <Footer />

      <Box paddingX={1} marginTop={1}>
        <Text color={theme.muted}>Local configuration enabled · provider operations disabled</Text>
      </Box>
    </Box>
  );
};
