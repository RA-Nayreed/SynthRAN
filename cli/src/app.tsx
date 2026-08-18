import React, {useEffect, useRef, useState} from 'react';
import {Box, Spacer, Text, useApp, useInput} from 'ink';

import {
  approveOperation,
  bindProviderExperiment,
  cancelOperation,
  createLocalExperiment,
  executeOperation,
  initializeWorkspace,
  inspectSetup,
  listProviderExperiments,
  planOperation,
  readLocalSnapshot,
  updateWorkspaceDefaults,
  type ControlSnapshot,
  type OperationSnapshot,
  type PlacementMode,
  type SetupProfile,
  type SetupSnapshot,
} from './backend/control.js';
import {
  primaryOperatorAction,
  secondaryOperatorAction,
  type OperatorActionView,
} from './backend/operator-actions.js';
import {initialSection, toWorkbenchState} from './backend/workbench.js';
import {ActionPalette, type PaletteAction} from './components/action-palette.js';
import {ConfigurationPanel} from './components/configuration.js';
import {Footer} from './components/footer.js';
import {OperationPanel} from './components/operation-panel.js';
import {SectionPanel} from './components/section-panel.js';
import {SectionStrip} from './components/section-strip.js';
import {SetupPanel, type SetupDraftView} from './components/setup.js';
import {
  sectionLabels,
  type RadioMode,
  type SectionLabel,
  type WorkbenchState,
} from './model.js';
import {theme} from './theme.js';

const actions: PaletteAction[] = [
  {label: 'Open setup', section: 'Setup'},
  {label: 'Inspect resources', section: 'Resources'},
  {label: 'Inspect 5G network', section: 'Network'},
  {label: 'Open experiment', section: 'Experiment'},
  {label: 'Open data', section: 'Data'},
];

const radioOptions: RadioMode[] = ['virtual', 'physical'];

const wrap = (value: number, length: number) => (value + length) % length;
const cycle = <T,>(items: readonly T[], current: T, delta: number): T => {
  const index = Math.max(0, items.indexOf(current));
  return items[wrap(index + delta, items.length)];
};
const clamp = (value: number, minimum: number, maximum: number) =>
  Math.max(minimum, Math.min(maximum, value));

const draftFromSnapshot = (snapshot: ControlSnapshot) => {
  let radio: RadioMode = 'virtual';
  if (snapshot.experiment.radio_mode === 'physical') radio = 'physical';
  else if (snapshot.experiment.radio_mode === 'virtual') radio = 'virtual';
  else if (snapshot.experiment.intent === 'physical-5g') radio = 'physical';

  return {
    radio,
    reservation: snapshot.workspace.reservation_minutes,
    placement: (
      snapshot.workspace.placement === 'manual' ? 'manual' : 'automatic'
    ) as PlacementMode,
  };
};

const freshProfileName = (setup: SetupSnapshot) => {
  const preferred = setup.defaults.profile || 'default';
  if (!setup.profiles.some(profile => profile.name === preferred)) return preferred;
  if (!setup.profiles.some(profile => profile.name === 'controller')) return 'controller';
  return 'profile';
};

const setupDraftFromSnapshot = (
  setup: SetupSnapshot,
): {draft: SetupDraftView; profileIndex: number} => {
  const profileIndex = setup.profiles.findIndex(profile => profile.name === setup.defaults.profile);
  if (profileIndex >= 0) {
    const profile = setup.profiles[profileIndex];
    return {
      profileIndex,
      draft: {
        reuseProfile: true,
        profileName: profile.name,
        project: setup.defaults.project,
        slicesUsername: profile.slices_username ?? '',
        r2labEnabled: profile.r2lab_slice !== null,
        r2labSlice: profile.r2lab_slice ?? '',
        identityReference: null,
        reservationMinutes: setup.defaults.reservation_minutes,
        placement: setup.defaults.placement,
      },
    };
  }
  return {
    profileIndex: setup.profiles.length,
    draft: {
      reuseProfile: false,
      profileName: freshProfileName(setup),
      project: setup.defaults.project,
      slicesUsername: setup.defaults.slices_username,
      r2labEnabled: false,
      r2labSlice: setup.defaults.r2lab_slice,
      identityReference: setup.ssh_identities[0] ?? null,
      reservationMinutes: setup.defaults.reservation_minutes,
      placement: setup.defaults.placement,
    },
  };
};

const safeText = (value: string, profileName: boolean) => {
  const allowed = profileName ? /[a-z0-9._-]/g : /[A-Za-z0-9._:-]/g;
  return (value.match(allowed) ?? []).join('');
};

export const App = () => {
  const {exit} = useApp();
  const [activeSection, setActiveSection] = useState<SectionLabel>('Setup');
  const [state, setState] = useState<WorkbenchState | null>(null);
  const [setup, setSetup] = useState<SetupSnapshot | null>(null);
  const [setupDraft, setSetupDraft] = useState<SetupDraftView | null>(null);
  const [setupProfileIndex, setSetupProfileIndex] = useState(0);
  const [setupIdentityIndex, setSetupIdentityIndex] = useState(0);
  const [setupFocus, setSetupFocus] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteIndex, setPaletteIndex] = useState(0);
  const [configFocus, setConfigFocus] = useState(0);
  const [draftRadio, setDraftRadio] = useState<RadioMode>('virtual');
  const [draftReservation, setDraftReservation] = useState(120);
  const [draftPlacement, setDraftPlacement] = useState<PlacementMode>('automatic');
  const [localBusy, setLocalBusy] = useState<'initializing' | 'defaults' | 'experiment' | null>(null);
  const [providerBusy, setProviderBusy] = useState<'loading' | 'binding' | null>(null);
  const [providerExperiments, setProviderExperiments] = useState<string[] | null>(null);
  const [providerIndex, setProviderIndex] = useState(0);
  const [operationSnapshot, setOperationSnapshot] = useState<OperationSnapshot | null>(null);
  const [operationLabel, setOperationLabel] = useState<string | null>(null);
  const [operationBusy, setOperationBusy] = useState<'prepare' | 'approve' | 'execute' | 'cancel' | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const actionRequest = useRef<AbortController | null>(null);

  const primaryAction = state ? primaryOperatorAction(state) : null;
  const secondaryAction = state ? secondaryOperatorAction(state) : null;
  const providerCandidate =
    providerExperiments && providerExperiments.length > 0
      ? providerExperiments[Math.min(providerIndex, providerExperiments.length - 1)]
      : null;
  const selectedSetupProfile: SetupProfile | null =
    setup && setupDraft?.reuseProfile && setupProfileIndex < setup.profiles.length
      ? setup.profiles[setupProfileIndex]
      : null;

  const applySnapshot = (snapshot: ControlSnapshot, chooseSection: boolean) => {
    const next = toWorkbenchState(snapshot);
    const draft = draftFromSnapshot(snapshot);
    setState(next);
    setSetup(null);
    setSetupDraft(null);
    setDraftRadio(draft.radio);
    setDraftReservation(draft.reservation);
    setDraftPlacement(draft.placement);
    if (chooseSection) setActiveSection(initialSection(snapshot));
  };

  const resetProviderChoices = () => {
    setProviderExperiments(null);
    setProviderIndex(0);
  };

  const resetOperation = () => {
    setOperationSnapshot(null);
    setOperationLabel(null);
  };

  useEffect(() => {
    const requestController = new AbortController();
    let cancelled = false;
    setState(null);
    setSetup(null);
    setSetupDraft(null);
    setLoadError(null);
    setNotice(null);
    resetProviderChoices();
    resetOperation();

    inspectSetup(requestController.signal)
      .then(async setupState => {
        if (cancelled) return;
        if (setupState.workspace_initialized) {
          const snapshot = await readLocalSnapshot(requestController.signal);
          if (cancelled) return;
          applySnapshot(snapshot, true);
          return;
        }
        const initial = setupDraftFromSnapshot(setupState);
        setSetup(setupState);
        setSetupDraft(initial.draft);
        setSetupProfileIndex(initial.profileIndex);
        setSetupIdentityIndex(0);
        setSetupFocus(0);
        setActiveSection('Setup');
      })
      .catch(error => {
        if (cancelled) return;
        setState(null);
        setSetup(null);
        setSetupDraft(null);
        setLoadError(error instanceof Error ? error.message : 'SynthRAN setup could not be loaded');
      });

    return () => {
      cancelled = true;
      requestController.abort();
    };
  }, [reloadToken]);

  useEffect(
    () => () => {
      actionRequest.current?.abort();
    },
    [],
  );

  const busy = localBusy !== null || providerBusy !== null || operationBusy !== null;

  const selectSection = (section: SectionLabel) => {
    setActiveSection(section);
    setNotice(null);
    resetOperation();
  };

  const moveSection = (delta: number) => {
    const current = sectionLabels.indexOf(activeSection);
    selectSection(sectionLabels[wrap(current + delta, sectionLabels.length)]);
  };

  const runLocalWrite = (
    kind: 'defaults' | 'experiment',
    action: (signal: AbortSignal) => Promise<ControlSnapshot>,
    success: (snapshot: ControlSnapshot) => string,
  ) => {
    if (busy) return;
    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setLocalBusy(kind);
    setNotice(null);
    action(requestController.signal)
      .then(snapshot => {
        if (requestController.signal.aborted) return;
        applySnapshot(snapshot, false);
        setActiveSection('Setup');
        if (kind === 'experiment') resetProviderChoices();
        setNotice(success(snapshot));
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        setNotice(error instanceof Error ? error.message : 'SynthRAN setup could not be changed');
      })
      .finally(() => {
        if (actionRequest.current === requestController) {
          actionRequest.current = null;
          setLocalBusy(null);
        }
      });
  };

  const saveDefaults = () => runLocalWrite(
    'defaults',
    signal => updateWorkspaceDefaults(
      {reservationMinutes: draftReservation, placement: draftPlacement},
      signal,
    ),
    snapshot => `Saved ${snapshot.workspace.reservation_minutes} minute reservation default.`,
  );

  const saveConfiguration = () => runLocalWrite(
    'experiment',
    signal => createLocalExperiment(
      {intent: 'iot-to-5g', radioMode: draftRadio},
      signal,
    ),
    snapshot => snapshot.experiment.id
      ? `Created ${snapshot.experiment.id}. Select the existing SLICES experiment to bind.`
      : 'Network configuration was created.',
  );

  const initializeFirstUse = () => {
    if (!setup || !setupDraft || busy) return;
    if (!setupDraft.project) {
      setNotice('SLICES project is required.');
      return;
    }
    if (!setupDraft.reuseProfile && (!setupDraft.profileName || !setupDraft.slicesUsername)) {
      setNotice('Profile name and SLICES username are required for a new profile.');
      return;
    }
    if (!setupDraft.reuseProfile && setupDraft.r2labEnabled && (!setupDraft.r2labSlice || !setupDraft.identityReference)) {
      setNotice('R2Lab slice and SSH identity are both required when R2Lab is enabled.');
      return;
    }

    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setLocalBusy('initializing');
    setNotice(null);
    initializeWorkspace(
      {
        profileName: setupDraft.profileName,
        project: setupDraft.project,
        reuseProfile: setupDraft.reuseProfile,
        slicesUsername: setupDraft.reuseProfile ? null : setupDraft.slicesUsername,
        r2labSlice: setupDraft.reuseProfile || !setupDraft.r2labEnabled ? null : setupDraft.r2labSlice,
        r2labIdentity: setupDraft.reuseProfile || !setupDraft.r2labEnabled ? null : setupDraft.identityReference,
        reservationMinutes: setupDraft.reservationMinutes,
        placement: setupDraft.placement,
      },
      requestController.signal,
    )
      .then(snapshot => {
        if (requestController.signal.aborted) return;
        applySnapshot(snapshot, true);
        setActiveSection('Setup');
        setNotice(`Workspace initialized for ${snapshot.workspace.project}.`);
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        setNotice(error instanceof Error ? error.message : 'SynthRAN workspace could not be initialized');
      })
      .finally(() => {
        if (actionRequest.current === requestController) {
          actionRequest.current = null;
          setLocalBusy(null);
        }
      });
  };

  const changeSetupProfile = (delta: number) => {
    if (!setup || !setupDraft) return;
    const choiceCount = setup.profiles.length + 1;
    const nextIndex = wrap(setupProfileIndex + delta, choiceCount);
    setSetupProfileIndex(nextIndex);
    if (nextIndex < setup.profiles.length) {
      const profile = setup.profiles[nextIndex];
      setSetupDraft(current => current ? {
        ...current,
        reuseProfile: true,
        profileName: profile.name,
        slicesUsername: profile.slices_username ?? '',
        r2labEnabled: profile.r2lab_slice !== null,
        r2labSlice: profile.r2lab_slice ?? '',
      } : current);
    } else {
      setSetupDraft(current => current ? {
        ...current,
        reuseProfile: false,
        profileName: freshProfileName(setup),
        slicesUsername: setup.defaults.slices_username,
        r2labEnabled: false,
        r2labSlice: setup.defaults.r2lab_slice,
        identityReference: setup.ssh_identities[setupIdentityIndex] ?? null,
      } : current);
    }
    setNotice(null);
  };

  const editSetupText = (field: 'profileName' | 'project' | 'slicesUsername' | 'r2labSlice', input: string, backspace: boolean) => {
    setSetupDraft(current => {
      if (!current) return current;
      const previous = current[field];
      const next = backspace
        ? previous.slice(0, -1)
        : previous + safeText(input, field === 'profileName');
      return {...current, [field]: next};
    });
    setNotice(null);
  };

  const changeSetupIdentity = (delta: number) => {
    if (!setup || !setupDraft || setup.ssh_identities.length === 0) return;
    const nextIndex = wrap(setupIdentityIndex + delta, setup.ssh_identities.length);
    setSetupIdentityIndex(nextIndex);
    setSetupDraft({...setupDraft, identityReference: setup.ssh_identities[nextIndex]});
    setNotice(null);
  };

  const loadProviders = () => {
    if (!state?.hasActiveExperiment) {
      setNotice('Create a network configuration before selecting a SLICES experiment.');
      return;
    }
    if (state.providerExperiment) {
      setNotice(`SLICES experiment is already bound to ${state.providerExperiment}.`);
      return;
    }
    if (busy) return;
    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setProviderBusy('loading');
    setNotice(null);
    listProviderExperiments(requestController.signal)
      .then(experiments => {
        if (requestController.signal.aborted) return;
        setProviderExperiments(experiments);
        setProviderIndex(0);
        setNotice(
          experiments.length > 0
            ? `Loaded ${experiments.length} existing SLICES experiment${experiments.length === 1 ? '' : 's'}.`
            : 'No SLICES experiments are available in the verified project.',
        );
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        resetProviderChoices();
        setNotice(error instanceof Error ? error.message : 'SLICES experiments could not be loaded');
      })
      .finally(() => {
        if (actionRequest.current === requestController) {
          actionRequest.current = null;
          setProviderBusy(null);
        }
      });
  };

  const changeProvider = (delta: number) => {
    if (!providerExperiments || providerExperiments.length === 0) return;
    setProviderIndex(index => wrap(index + delta, providerExperiments.length));
    setNotice(null);
  };

  const bindProvider = () => {
    if (!state?.hasActiveExperiment) {
      setNotice('Create a network configuration before binding a SLICES experiment.');
      return;
    }
    if (state.providerExperiment) {
      setNotice(`SLICES experiment is already bound to ${state.providerExperiment}.`);
      return;
    }
    if (!providerCandidate) {
      setNotice('Load and select an existing SLICES experiment first.');
      return;
    }
    if (busy) return;
    const selected = providerCandidate;
    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setProviderBusy('binding');
    setNotice(null);
    bindProviderExperiment(selected, requestController.signal)
      .then(snapshot => {
        if (requestController.signal.aborted) return;
        applySnapshot(snapshot, false);
        setActiveSection('Setup');
        setNotice(`Bound existing SLICES experiment ${selected}.`);
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        setNotice(error instanceof Error ? error.message : 'SLICES experiment could not be bound');
      })
      .finally(() => {
        if (actionRequest.current === requestController) {
          actionRequest.current = null;
          setProviderBusy(null);
        }
      });
  };

  const prepareAction = (candidate: OperatorActionView) => {
    if (busy) return;
    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setOperationBusy('prepare');
    setOperationLabel(candidate.label);
    setNotice(null);
    planOperation(candidate.action, requestController.signal)
      .then(operation => {
        if (requestController.signal.aborted) return;
        setOperationSnapshot(operation);
        setNotice(
          operation.plan.approval_required
            ? `Review the exact action, then press Enter to confirm ${candidate.label.toLowerCase()}.`
            : `Review the exact action, then press Enter to execute ${candidate.label.toLowerCase()}.`,
        );
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        resetOperation();
        setNotice(error instanceof Error ? error.message : 'Action could not be prepared');
      })
      .finally(() => {
        if (actionRequest.current === requestController) {
          actionRequest.current = null;
          setOperationBusy(null);
        }
      });
  };

  const executePreparedOperation = () => {
    if (busy || !operationSnapshot) return;
    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setOperationBusy('execute');
    setNotice(null);
    const label = operationLabel ?? 'action';
    executeOperation(operationSnapshot.plan.operation_id, requestController.signal)
      .then(async operation => {
        if (requestController.signal.aborted) return;
        const snapshot = await readLocalSnapshot(requestController.signal);
        if (requestController.signal.aborted) return;
        applySnapshot(snapshot, false);
        resetOperation();
        setNotice(`Completed ${label}.`);
        if (operation.state.status !== 'completed') {
          setNotice(`${label} finished with state ${operation.state.status}.`);
        }
      })
      .catch(async error => {
        if (requestController.signal.aborted) return;
        try {
          const snapshot = await readLocalSnapshot(requestController.signal);
          if (!requestController.signal.aborted) applySnapshot(snapshot, false);
        } catch {
          // Preserve the original execution error when the follow-up read also fails.
        }
        resetOperation();
        setNotice(error instanceof Error ? error.message : 'Live action did not complete');
      })
      .finally(() => {
        if (actionRequest.current === requestController) {
          actionRequest.current = null;
          setOperationBusy(null);
        }
      });
  };

  const advancePreparedOperation = () => {
    if (busy || !operationSnapshot) return;
    if (operationSnapshot.state.status === 'planned' && operationSnapshot.plan.approval_required) {
      const requestController = new AbortController();
      actionRequest.current?.abort();
      actionRequest.current = requestController;
      setOperationBusy('approve');
      setNotice(null);
      approveOperation(
        operationSnapshot.plan.operation_id,
        operationSnapshot.plan.risk === 'R3' ? 'destructive' : 'standard',
        requestController.signal,
      )
        .then(operation => {
          if (requestController.signal.aborted) return;
          setOperationSnapshot(operation);
          setNotice(`Confirmation recorded. Press Enter to execute ${operationLabel?.toLowerCase() ?? 'the action'}.`);
        })
        .catch(error => {
          if (requestController.signal.aborted) return;
          setNotice(error instanceof Error ? error.message : 'Confirmation could not be recorded');
        })
        .finally(() => {
          if (actionRequest.current === requestController) {
            actionRequest.current = null;
            setOperationBusy(null);
          }
        });
      return;
    }

    if (
      operationSnapshot.state.status === 'approved' ||
      (operationSnapshot.state.status === 'planned' && !operationSnapshot.plan.approval_required)
    ) {
      executePreparedOperation();
      return;
    }

    setNotice(`Action is currently ${operationSnapshot.state.status}. Reload before continuing.`);
  };

  const cancelPreparedOperation = () => {
    if (busy || !operationSnapshot) return;
    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setOperationBusy('cancel');
    setNotice(null);
    cancelOperation(operationSnapshot.plan.operation_id, requestController.signal)
      .then(() => {
        if (requestController.signal.aborted) return;
        resetOperation();
        setNotice('Prepared action cancelled.');
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        setNotice(error instanceof Error ? error.message : 'Action could not be cancelled');
      })
      .finally(() => {
        if (actionRequest.current === requestController) {
          actionRequest.current = null;
          setOperationBusy(null);
        }
      });
  };

  const setupTextFocused = setupDraft !== null && (
    setupFocus === 2 ||
    (!setupDraft.reuseProfile && (setupFocus === 1 || setupFocus === 3 || (setupFocus === 5 && setupDraft.r2labEnabled)))
  );

  useInput((input, key) => {
    if (key.ctrl && input === 'c') {
      if (operationBusy === 'execute') {
        setNotice('A live provider action is running and cannot be interrupted safely here.');
        return;
      }
      actionRequest.current?.abort();
      exit();
      return;
    }
    if (!setupTextFocused && input.toLowerCase() === 'q') {
      if (operationBusy === 'execute') {
        setNotice('A live provider action is running and cannot be interrupted safely here.');
        return;
      }
      actionRequest.current?.abort();
      exit();
      return;
    }
    if (busy) return;

    if (setup && setupDraft && state === null) {
      if (!setupTextFocused && input.toLowerCase() === 'r') {
        setReloadToken(value => value + 1);
        return;
      }
      if (key.upArrow) {
        setSetupFocus(index => wrap(index - 1, 9));
        return;
      }
      if (key.downArrow || key.tab) {
        setSetupFocus(index => wrap(index + 1, 9));
        return;
      }
      if (setupFocus === 0 && (key.leftArrow || key.rightArrow || key.return)) {
        changeSetupProfile(key.leftArrow ? -1 : 1);
        return;
      }
      if (setupFocus === 1 && !setupDraft.reuseProfile && (key.backspace || input)) {
        editSetupText('profileName', input, key.backspace);
        return;
      }
      if (setupFocus === 2 && (key.backspace || input)) {
        editSetupText('project', input, key.backspace);
        return;
      }
      if (setupFocus === 3 && !setupDraft.reuseProfile && (key.backspace || input)) {
        editSetupText('slicesUsername', input, key.backspace);
        return;
      }
      if (setupFocus === 4 && !setupDraft.reuseProfile && (key.leftArrow || key.rightArrow || key.return)) {
        if (!setupDraft.r2labEnabled && setup.ssh_identities.length === 0) {
          setNotice('No private SSH identity was discovered for R2Lab.');
          return;
        }
        setSetupDraft({...setupDraft, r2labEnabled: !setupDraft.r2labEnabled});
        setNotice(null);
        return;
      }
      if (setupFocus === 5 && !setupDraft.reuseProfile && setupDraft.r2labEnabled && (key.backspace || input)) {
        editSetupText('r2labSlice', input, key.backspace);
        return;
      }
      if (setupFocus === 6 && !setupDraft.reuseProfile && setupDraft.r2labEnabled && (key.leftArrow || key.rightArrow || key.return)) {
        changeSetupIdentity(key.leftArrow ? -1 : 1);
        return;
      }
      if (setupFocus === 7 && (key.leftArrow || key.rightArrow || key.return)) {
        const delta = key.leftArrow ? -10 : 10;
        setSetupDraft({...setupDraft, reservationMinutes: clamp(setupDraft.reservationMinutes + delta, 10, 1440)});
        setNotice(null);
        return;
      }
      if (setupFocus === 8 && key.return) {
        initializeFirstUse();
      }
      return;
    }

    if (input.toLowerCase() === 'r' && (state !== null || loadError !== null)) {
      setPaletteOpen(false);
      resetOperation();
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

    if (input === '/') {
      setPaletteOpen(true);
      setPaletteIndex(0);
      return;
    }
    if (/^[1-5]$/.test(input)) {
      selectSection(sectionLabels[Number(input) - 1]);
      return;
    }

    if (activeSection === 'Resources' || activeSection === 'Network') {
      if (input.toLowerCase() === 'x' && operationSnapshot) {
        cancelPreparedOperation();
        return;
      }
      if (input.toLowerCase() === 's' && !operationSnapshot && secondaryAction) {
        prepareAction(secondaryAction);
        return;
      }
      if (key.return) {
        if (operationSnapshot) {
          advancePreparedOperation();
          return;
        }
        if (primaryAction) {
          prepareAction(primaryAction);
          return;
        }
        if (state.lifecycle === 'PATH_PROVEN') {
          selectSection('Experiment');
        }
        return;
      }
    }

    if (activeSection === 'Setup') {
      if (key.upArrow) {
        setConfigFocus(index => wrap(index - 1, 6));
        return;
      }
      if (key.downArrow) {
        setConfigFocus(index => wrap(index + 1, 6));
        return;
      }
      if (configFocus === 0 && (key.leftArrow || key.rightArrow || key.return)) {
        setDraftRadio(value => cycle(radioOptions, value === 'automatic' ? 'virtual' : value, key.leftArrow ? -1 : 1));
        setNotice(null);
        return;
      }
      if (configFocus === 1 && (key.leftArrow || key.rightArrow || key.return)) {
        setDraftReservation(value => clamp(value + (key.leftArrow ? -10 : 10), 10, 1440));
        setNotice(null);
        return;
      }
      if (configFocus === 2 && key.return) {
        saveDefaults();
        return;
      }
      if (configFocus === 3 && key.return) {
        saveConfiguration();
        return;
      }
      if (configFocus === 4) {
        if (providerExperiments === null && key.return) {
          loadProviders();
          return;
        }
        if (key.leftArrow || key.rightArrow) {
          changeProvider(key.leftArrow ? -1 : 1);
          return;
        }
      }
      if (configFocus === 5 && key.return) {
        bindProvider();
        return;
      }
    }

    if (key.tab) moveSection(key.shift ? -1 : 1);
  });

  const headerProject = state?.project ?? (setupDraft?.project || 'local workspace');
  const headerExperiment = state?.experiment ?? (setup ? 'not initialized' : 'reading state');

  return (
    <Box flexDirection="column" width="100%">
      <Box borderStyle="single" borderColor={theme.hairlineStrong} paddingX={2} flexDirection="column">
        <Box>
          <Text bold color={theme.bodyStrong}>SynthRAN</Text>
          <Spacer />
          <Text color={theme.muted}>{headerProject}</Text>
          <Text color={theme.hairline}> · </Text>
          <Text color={theme.muted}>{headerExperiment}</Text>
        </Box>

        {state ? (
          <SectionStrip sections={sectionLabels} selected={activeSection} completed={state.completedSections} />
        ) : setup ? (
          <SectionStrip sections={sectionLabels} selected="Setup" completed={[]} />
        ) : null}

        <Box borderTop borderStyle="single" borderColor={theme.hairline}>
          {loadError ? (
            <Box flexDirection="column" paddingX={1} paddingY={1}>
              <Text bold color={theme.error}>Setup unavailable</Text>
              <Text color={theme.muted}>{loadError}</Text>
              <Box height={1} />
              <Text color={theme.bodyStrong}>Press r to retry or q to quit.</Text>
            </Box>
          ) : setup && setupDraft ? (
            <SetupPanel
              profiles={setup.profiles}
              selectedProfile={selectedSetupProfile}
              draft={setupDraft}
              focusedIndex={setupFocus}
              busy={localBusy === 'initializing'}
              notice={notice}
            />
          ) : state === null ? (
            <Box paddingX={1} paddingY={1}>
              <Text color={theme.muted}>Reading SynthRAN setup…</Text>
            </Box>
          ) : paletteOpen ? (
            <ActionPalette actions={actions} selectedIndex={paletteIndex} />
          ) : activeSection === 'Setup' ? (
            <ConfigurationPanel
              state={state}
              draftRadio={draftRadio}
              draftReservation={draftReservation}
              focusedIndex={configFocus}
              localBusy={localBusy}
              providerBusy={providerBusy}
              providerExperiments={providerExperiments}
              providerCandidate={providerCandidate}
              notice={notice}
            />
          ) : activeSection === 'Resources' || activeSection === 'Network' ? (
            <OperationPanel
              section={activeSection}
              state={state}
              primary={primaryAction}
              secondary={secondaryAction}
              operation={operationSnapshot}
              operationLabel={operationLabel}
              busy={operationBusy !== null}
              notice={notice}
            />
          ) : (
            <SectionPanel section={activeSection} state={state} />
          )}
        </Box>
      </Box>

      <Footer />

      <Box paddingX={1} marginTop={1}>
        <Text color={theme.muted}>Exact action plan · explicit confirmation · live authority rechecked before provider changes</Text>
      </Box>
    </Box>
  );
};
