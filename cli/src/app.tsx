import React, {useEffect, useRef, useState} from 'react';
import {Box, Spacer, Text, useApp, useInput} from 'ink';

import {
  approveOperation,
  bindProviderExperiment,
  cancelOperation,
  createLocalExperiment,
  executeOperation,
  initializeWorkspace,
  inspectOperation,
  inspectSetup,
  listProviderExperiments,
  planOperation,
  readLocalSnapshot,
  updateWorkspaceDefaults,
  type ControlSnapshot,
  type ExperimentIntent,
  type OperationAction,
  type OperationInspection,
  type OperationSnapshot,
  type PlacementMode,
  type SetupProfile,
  type SetupSnapshot,
} from './backend/control.js';
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

const intentOptions: ExperimentIntent[] = [
  'iot-to-5g',
  'virtual-5g',
  'physical-5g',
  'open-ran',
  'unspecified',
];
const allRadioOptions: RadioMode[] = ['virtual', 'physical', 'automatic'];
const operationActions: OperationAction[] = ['reserve', 'up', 'verify', 'recover', 'down'];

const wrap = (value: number, length: number) => (value + length) % length;
const cycle = <T,>(items: readonly T[], current: T, delta: number): T => {
  const index = Math.max(0, items.indexOf(current));
  return items[wrap(index + delta, items.length)];
};
const clamp = (value: number, minimum: number, maximum: number) =>
  Math.max(minimum, Math.min(maximum, value));

const isIntent = (value: string | null): value is ExperimentIntent =>
  value !== null && intentOptions.includes(value as ExperimentIntent);
const isRadio = (value: string | null): value is RadioMode =>
  value === 'automatic' || value === 'virtual' || value === 'physical';
const isPlacement = (value: string): value is PlacementMode =>
  value === 'automatic' || value === 'manual';

const radioOptionsFor = (intent: ExperimentIntent): RadioMode[] => {
  if (intent === 'virtual-5g') return ['virtual', 'automatic'];
  if (intent === 'physical-5g') return ['physical', 'automatic'];
  return allRadioOptions;
};

const draftFromSnapshot = (snapshot: ControlSnapshot) => ({
  intent: isIntent(snapshot.experiment.intent) ? snapshot.experiment.intent : 'iot-to-5g' as ExperimentIntent,
  radio: isRadio(snapshot.experiment.radio_mode) ? snapshot.experiment.radio_mode : 'virtual' as RadioMode,
  reservation: snapshot.workspace.reservation_minutes,
  placement: isPlacement(snapshot.workspace.placement) ? snapshot.workspace.placement : 'automatic' as PlacementMode,
});

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
  const [activeSection, setActiveSection] = useState<SectionLabel>('Access');
  const [state, setState] = useState<WorkbenchState | null>(null);
  const [setup, setSetup] = useState<SetupSnapshot | null>(null);
  const [setupDraft, setSetupDraft] = useState<SetupDraftView | null>(null);
  const [setupProfileIndex, setSetupProfileIndex] = useState(0);
  const [setupIdentityIndex, setSetupIdentityIndex] = useState(0);
  const [setupFocus, setSetupFocus] = useState(0);
  const [mode, setMode] = useState<WorkbenchMode>('OBSERVE');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteIndex, setPaletteIndex] = useState(0);
  const [configFocus, setConfigFocus] = useState(0);
  const [draftIntent, setDraftIntent] = useState<ExperimentIntent>('iot-to-5g');
  const [draftRadio, setDraftRadio] = useState<RadioMode>('virtual');
  const [draftReservation, setDraftReservation] = useState(120);
  const [draftPlacement, setDraftPlacement] = useState<PlacementMode>('automatic');
  const [localBusy, setLocalBusy] = useState<'initializing' | 'defaults' | 'experiment' | null>(null);
  const [providerBusy, setProviderBusy] = useState<'loading' | 'binding' | null>(null);
  const [providerExperiments, setProviderExperiments] = useState<string[] | null>(null);
  const [providerIndex, setProviderIndex] = useState(0);
  const [operationActionIndex, setOperationActionIndex] = useState(1);
  const [operationInspection, setOperationInspection] = useState<OperationInspection | null>(null);
  const [operationSnapshot, setOperationSnapshot] = useState<OperationSnapshot | null>(null);
  const [operationBusy, setOperationBusy] = useState<'review' | 'prepare' | 'approve' | 'execute' | 'cancel' | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const actionRequest = useRef<AbortController | null>(null);

  const operationAction = operationActions[operationActionIndex];
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
    setDraftIntent(draft.intent);
    setDraftRadio(draft.radio);
    setDraftReservation(draft.reservation);
    setDraftPlacement(draft.placement);
    if (chooseSection) setActiveSection(initialSection(snapshot));
  };

  const resetProviderChoices = () => {
    setProviderExperiments(null);
    setProviderIndex(0);
  };

  const resetOperationReview = () => {
    setOperationInspection(null);
    setOperationSnapshot(null);
  };

  useEffect(() => {
    const requestController = new AbortController();
    let cancelled = false;
    setState(null);
    setSetup(null);
    setSetupDraft(null);
    setMode('OBSERVE');
    setLoadError(null);
    setNotice(null);
    resetProviderChoices();
    resetOperationReview();

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
        setActiveSection('Configure');
      })
      .catch(error => {
        if (cancelled) return;
        setState(null);
        setSetup(null);
        setSetupDraft(null);
        setLoadError(error instanceof Error ? error.message : 'SynthRAN configuration could not be loaded');
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
    setMode('OBSERVE');
    setNotice(null);
  };

  const moveSection = (delta: number) => {
    const current = sectionLabels.indexOf(activeSection);
    selectSection(sectionLabels[wrap(current + delta, sectionLabels.length)]);
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

  const runLocalWrite = (
    kind: 'defaults' | 'experiment',
    action: (signal: AbortSignal) => Promise<ControlSnapshot>,
    success: (snapshot: ControlSnapshot) => string,
  ) => {
    if (busy) return;
    if (mode !== 'OPERATE') {
      setNotice('Switch to OPERATE with m before changing local configuration.');
      return;
    }
    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setLocalBusy(kind);
    setNotice(null);
    action(requestController.signal)
      .then(snapshot => {
        if (requestController.signal.aborted) return;
        applySnapshot(snapshot, false);
        setActiveSection('Configure');
        setMode('OBSERVE');
        if (kind === 'experiment') resetProviderChoices();
        setNotice(success(snapshot));
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        setNotice(error instanceof Error ? error.message : 'SynthRAN local configuration could not be changed');
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
    snapshot => `Saved ${snapshot.workspace.reservation_minutes} minute reservation and ${snapshot.workspace.placement} placement defaults.`,
  );

  const saveConfiguration = () => runLocalWrite(
    'experiment',
    signal => createLocalExperiment(
      {intent: draftIntent, radioMode: draftRadio},
      signal,
    ),
    snapshot => snapshot.experiment.id
      ? `Created ${snapshot.experiment.id}. Provider experiment is not bound.`
      : 'Local configuration was created.',
  );

  const initializeFirstUse = () => {
    if (!setup || !setupDraft || busy) return;
    if (mode !== 'OPERATE') {
      setNotice('Switch to OPERATE with m before initializing local configuration.');
      return;
    }
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
        setActiveSection('Configure');
        setMode('OBSERVE');
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
      setNotice('Create a local configuration before loading provider experiments.');
      return;
    }
    if (state.providerExperiment) {
      setNotice(`Provider experiment is already bound to ${state.providerExperiment}.`);
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
            ? `Loaded ${experiments.length} SLICES experiment${experiments.length === 1 ? '' : 's'}.`
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
      setNotice('Create a local configuration before binding a provider experiment.');
      return;
    }
    if (state.providerExperiment) {
      setNotice(`Provider experiment is already bound to ${state.providerExperiment}.`);
      return;
    }
    if (!providerCandidate) {
      setNotice('Load and select a provider experiment first.');
      return;
    }
    if (busy) return;
    if (mode !== 'OPERATE') {
      setNotice('Switch to OPERATE with m before binding the provider experiment.');
      return;
    }
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
        setActiveSection('Configure');
        setMode('OBSERVE');
        setNotice(`Bound ${selected} to ${snapshot.experiment.id ?? 'the active experiment'}.`);
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

  const changeOperationAction = (delta: number) => {
    setOperationActionIndex(index => wrap(index + delta, operationActions.length));
    resetOperationReview();
    setNotice(null);
  };

  const reviewOperation = () => {
    if (busy) return;
    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setOperationBusy('review');
    setOperationSnapshot(null);
    setNotice(null);
    inspectOperation(operationAction, requestController.signal)
      .then(inspection => {
        if (requestController.signal.aborted) return;
        setOperationInspection(inspection);
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        setOperationInspection(null);
        setNotice(error instanceof Error ? error.message : 'Current action could not be reviewed');
      })
      .finally(() => {
        if (actionRequest.current === requestController) {
          actionRequest.current = null;
          setOperationBusy(null);
        }
      });
  };

  const prepareOperation = () => {
    if (busy) return;
    const mutating = operationAction !== 'verify';
    if (mutating && mode !== 'OPERATE') {
      setNotice('Switch to OPERATE with m before preparing a change.');
      return;
    }
    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setOperationBusy('prepare');
    setNotice(null);
    planOperation(operationAction, requestController.signal)
      .then(operation => {
        if (requestController.signal.aborted) return;
        setOperationSnapshot(operation);
        setOperationInspection(null);
        setNotice(`Prepared ${operation.plan.operation_id} for review.`);
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        setNotice(error instanceof Error ? error.message : 'Action could not be prepared');
      })
      .finally(() => {
        if (actionRequest.current === requestController) {
          actionRequest.current = null;
          setOperationBusy(null);
        }
      });
  };

  const approvePreparedOperation = (destructive: boolean) => {
    if (busy || !operationSnapshot) {
      if (!operationSnapshot) setNotice('Prepare an action before recording approval.');
      return;
    }
    if (mode !== 'OPERATE') {
      setNotice('Switch to OPERATE with m before recording approval.');
      return;
    }
    if (!operationSnapshot.plan.approval_required) {
      setNotice('This read-only action does not require approval.');
      return;
    }
    if (operationSnapshot.plan.risk === 'R3' && !destructive) {
      setNotice('Use d to confirm the destructive teardown approval.');
      return;
    }
    if (operationSnapshot.plan.risk !== 'R3' && destructive) {
      setNotice('Destructive approval is reserved for teardown.');
      return;
    }

    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setOperationBusy('approve');
    setNotice(null);
    approveOperation(
      operationSnapshot.plan.operation_id,
      destructive ? 'destructive' : 'standard',
      requestController.signal,
    )
      .then(operation => {
        if (requestController.signal.aborted) return;
        setOperationSnapshot(operation);
        setMode('OBSERVE');
        setNotice(`Approval recorded for ${operation.plan.operation_id}.`);
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        setNotice(error instanceof Error ? error.message : 'Approval could not be recorded');
      })
      .finally(() => {
        if (actionRequest.current === requestController) {
          actionRequest.current = null;
          setOperationBusy(null);
        }
      });
  };

  const executePreparedOperation = () => {
    if (busy || !operationSnapshot) {
      if (!operationSnapshot) setNotice('Prepare an action before executing it.');
      return;
    }
    const readyStatus = operationSnapshot.plan.approval_required ? 'approved' : 'planned';
    if (operationSnapshot.state.status !== readyStatus) {
      setNotice(
        operationSnapshot.plan.approval_required
          ? 'Record the required approval before execution.'
          : 'Prepare a fresh action before execution.',
      );
      return;
    }
    if (operationSnapshot.plan.mutates && mode !== 'OPERATE') {
      setNotice('Switch to OPERATE with m before executing the approved change.');
      return;
    }

    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setOperationBusy('execute');
    setNotice(null);
    executeOperation(operationSnapshot.plan.operation_id, requestController.signal)
      .then(async operation => {
        if (requestController.signal.aborted) return;
        const snapshot = await readLocalSnapshot(requestController.signal);
        if (requestController.signal.aborted) return;
        applySnapshot(snapshot, false);
        setOperationSnapshot(operation);
        setOperationInspection(null);
        setMode('OBSERVE');
        setNotice(`Completed ${operation.plan.operation_id}.`);
      })
      .catch(error => {
        if (requestController.signal.aborted) return;
        setNotice(error instanceof Error ? error.message : 'Live action did not complete');
      })
      .finally(() => {
        if (actionRequest.current === requestController) {
          actionRequest.current = null;
          setOperationBusy(null);
        }
      });
  };

  const cancelPreparedOperation = () => {
    if (busy || !operationSnapshot) {
      if (!operationSnapshot) setNotice('Prepare an action before cancelling it.');
      return;
    }
    if (mode !== 'OPERATE') {
      setNotice('Switch to OPERATE with m before cancelling an action.');
      return;
    }
    const requestController = new AbortController();
    actionRequest.current?.abort();
    actionRequest.current = requestController;
    setOperationBusy('cancel');
    setNotice(null);
    cancelOperation(operationSnapshot.plan.operation_id, requestController.signal)
      .then(operation => {
        if (requestController.signal.aborted) return;
        setOperationSnapshot(operation);
        setMode('OBSERVE');
        setNotice(`Cancelled ${operation.plan.operation_id}.`);
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
        setNotice('A live action is running; interruption is disabled at this boundary.');
        return;
      }
      actionRequest.current?.abort();
      exit();
      return;
    }
    if (!setupTextFocused && input.toLowerCase() === 'q') {
      if (operationBusy === 'execute') {
        setNotice('A live action is running; interruption is disabled at this boundary.');
        return;
      }
      actionRequest.current?.abort();
      exit();
      return;
    }
    if (busy) return;

    if (setup && setupDraft && state === null) {
      if (!setupTextFocused && input.toLowerCase() === 'r') {
        setMode('OBSERVE');
        setReloadToken(value => value + 1);
        return;
      }
      if (!setupTextFocused && input.toLowerCase() === 'm') {
        setMode(current => current === 'OBSERVE' ? 'OPERATE' : 'OBSERVE');
        setNotice(null);
        return;
      }
      if (key.upArrow) {
        setSetupFocus(index => wrap(index - 1, 10));
        return;
      }
      if (key.downArrow || key.tab) {
        setSetupFocus(index => wrap(index + 1, 10));
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
      if (setupFocus === 8 && (key.leftArrow || key.rightArrow || key.return)) {
        setSetupDraft({...setupDraft, placement: setupDraft.placement === 'automatic' ? 'manual' : 'automatic'});
        setNotice(null);
        return;
      }
      if (setupFocus === 9 && key.return) {
        initializeFirstUse();
      }
      return;
    }

    if (input.toLowerCase() === 'r' && (state !== null || loadError !== null)) {
      setPaletteOpen(false);
      setMode('OBSERVE');
      resetOperationReview();
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

    if (
      input.toLowerCase() === 'm' &&
      (activeSection === 'Configure' || activeSection === 'Resources' || activeSection === 'Network')
    ) {
      setMode(current => current === 'OBSERVE' ? 'OPERATE' : 'OBSERVE');
      setNotice(null);
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

    if (activeSection === 'Resources' || activeSection === 'Network') {
      if (key.leftArrow || key.rightArrow) {
        changeOperationAction(key.leftArrow ? -1 : 1);
        return;
      }
      if (key.return) {
        reviewOperation();
        return;
      }
      if (input.toLowerCase() === 'p') {
        prepareOperation();
        return;
      }
      if (input.toLowerCase() === 'a') {
        approvePreparedOperation(false);
        return;
      }
      if (input.toLowerCase() === 'd') {
        approvePreparedOperation(true);
        return;
      }
      if (input.toLowerCase() === 'e') {
        executePreparedOperation();
        return;
      }
      if (input.toLowerCase() === 'x') {
        cancelPreparedOperation();
        return;
      }
    }

    if (activeSection === 'Configure') {
      if (key.upArrow) {
        setConfigFocus(index => wrap(index - 1, 8));
        return;
      }
      if (key.downArrow) {
        setConfigFocus(index => wrap(index + 1, 8));
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
      if (configFocus === 2 && (key.leftArrow || key.rightArrow || key.return)) {
        setDraftReservation(value => clamp(value + (key.leftArrow ? -10 : 10), 10, 1440));
        setNotice(null);
        return;
      }
      if (configFocus === 3 && (key.leftArrow || key.rightArrow || key.return)) {
        setDraftPlacement(value => value === 'automatic' ? 'manual' : 'automatic');
        setNotice(null);
        return;
      }
      if (configFocus === 4 && key.return) {
        saveDefaults();
        return;
      }
      if (configFocus === 5 && key.return) {
        saveConfiguration();
        return;
      }
      if (configFocus === 6) {
        if (providerExperiments === null && key.return) {
          loadProviders();
          return;
        }
        if (key.leftArrow || key.rightArrow) {
          changeProvider(key.leftArrow ? -1 : 1);
          return;
        }
      }
      if (configFocus === 7 && key.return) {
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
          <Text>   </Text>
          <Text inverse>{` ${mode} `}</Text>
        </Box>

        {state ? (
          <SectionStrip sections={sectionLabels} selected={activeSection} completed={state.completedSections} />
        ) : setup ? (
          <SectionStrip sections={sectionLabels} selected="Configure" completed={[]} />
        ) : null}

        <Box borderTop borderStyle="single" borderColor={theme.hairline}>
          {loadError ? (
            <Box flexDirection="column" paddingX={1} paddingY={1}>
              <Text bold color={theme.error}>Configuration unavailable</Text>
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
              mode={mode}
              busy={localBusy === 'initializing'}
              notice={notice}
            />
          ) : state === null ? (
            <Box paddingX={1} paddingY={1}>
              <Text color={theme.muted}>Reading SynthRAN configuration…</Text>
            </Box>
          ) : paletteOpen ? (
            <ActionPalette actions={actions} selectedIndex={paletteIndex} />
          ) : activeSection === 'Configure' ? (
            <ConfigurationPanel
              state={state}
              mode={mode}
              draftIntent={draftIntent}
              draftRadio={draftRadio}
              draftReservation={draftReservation}
              draftPlacement={draftPlacement}
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
              mode={mode}
              action={operationAction}
              inspection={operationInspection}
              operation={operationSnapshot}
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
        <Text color={theme.muted}>OBSERVE by default · OPERATE gates live changes · virtual RFSIM execution enabled</Text>
      </Box>
    </Box>
  );
};
