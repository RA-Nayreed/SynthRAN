import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {basename, dirname, join, resolve} from 'node:path';

export type ExperimentIntent =
  | 'unspecified'
  | 'virtual-5g'
  | 'physical-5g'
  | 'open-ran'
  | 'iot-to-5g';
export type ExperimentRadioMode = 'automatic' | 'virtual' | 'physical';
export type PlacementMode = 'automatic' | 'manual';
export type OperationAction = 'reserve' | 'up' | 'verify' | 'recover' | 'down';
export type ApprovalMode = 'standard' | 'destructive';

export interface ExperimentCreateInput {
  intent: ExperimentIntent;
  radioMode: ExperimentRadioMode;
  label?: string | null;
}

export interface WorkspaceInitializeInput {
  profileName: string;
  project: string;
  reuseProfile: boolean;
  slicesUsername?: string | null;
  r2labSlice?: string | null;
  r2labIdentity?: string | null;
  reservationMinutes: number;
  placement: PlacementMode;
}

export interface WorkspaceDefaultsInput {
  reservationMinutes: number;
  placement: PlacementMode;
}

export interface SetupProfile {
  name: string;
  slices_username: string | null;
  r2lab_slice: string | null;
  identity_name: string | null;
}

export interface SetupSnapshot {
  workspace_initialized: boolean;
  profiles: SetupProfile[];
  ssh_identities: string[];
  defaults: {
    profile: string;
    project: string;
    slices_username: string;
    r2lab_slice: string;
    reservation_minutes: number;
    placement: PlacementMode;
  };
}

export interface ControlAccessEntry {
  configured: boolean;
  fresh: boolean;
  verified: boolean;
  verified_at_utc: string | null;
  refresh_after_utc: string | null;
  access_until_utc: string | null;
  subject?: string | null;
  slice?: string | null;
  identity_name?: string | null;
}

export interface ControlSnapshot {
  workspace: {
    profile: string;
    project: string;
    reservation_minutes: number;
    placement: string;
  };
  experiment: {
    id: string | null;
    provider_experiment: string | null;
    intent: string | null;
    radio_mode: string | null;
    lifecycle: string;
  };
  access: {
    slices: ControlAccessEntry;
    r2lab: ControlAccessEntry;
  };
  observations: Array<{
    name: string;
    state: string;
    fresh: boolean;
    source: string | null;
    ownership: string | null;
    detail: string;
  }>;
  next_steps: string[];
  blocks: string[];
}

export interface OperationInspection {
  action: OperationAction;
  kind: string;
  risk: string;
  mutates: boolean;
  reason: string;
  approval_required: boolean;
  approval_mode: ApprovalMode | null;
  targets: string[];
  can_plan: boolean;
  plan_block: string | null;
}

export interface OperationPlanView {
  operation_id: string;
  experiment_id: string;
  kind: string;
  risk: string;
  mutates: boolean;
  reason: string;
  approval_required: boolean;
  approval_mode: ApprovalMode | null;
  targets: string[];
  created_at_utc: string;
}

export interface OperationStateView {
  schema: string;
  operation_id: string;
  status: string;
  risk: string;
  mutates: boolean;
  plan_sha256: string;
  updated_at_utc: string;
  claim_held: boolean;
}

export interface OperationApprovalView {
  schema: string;
  operation_id: string;
  plan_sha256: string;
  risk: string;
  mode: ApprovalMode;
  approved_at_utc: string;
}

export interface OperationEventView {
  schema: string;
  event_id: string;
  operation_id: string;
  sequence: number;
  event_type: string;
  occurred_at_utc: string;
  risk: string;
  mutates: boolean;
  plan_sha256: string;
  attributes: Record<string, string>;
}

export interface OperationSnapshot {
  plan: OperationPlanView;
  state: OperationStateView;
  approval: OperationApprovalView | null;
  events: OperationEventView[];
}

interface HandshakeResult {
  service: string;
  protocol: number;
  local_writes: boolean;
  provider_reads: boolean;
  provider_mutation: boolean;
  methods: string[];
}

interface ControlResponse<T> {
  v: number;
  id: string | null;
  ok: boolean;
  result?: T;
  error?: {code: string; message: string};
}

interface ControlRequest {
  id: string;
  method: string;
  params: Record<string, unknown>;
}

interface RunOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

const CONTROL_VERSION = 5;
const MAX_RESPONSE_BYTES = 1024 * 1024;
const LOCAL_RESPONSE_TIMEOUT_MS = 10_000;
const PROVIDER_RESPONSE_TIMEOUT_MS = 190_000;
const PROVIDER_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]*$/;
const OPERATION_ID_RE = /^op-[0-9]{6,}$/;
const REQUIRED_METHODS = [
  'system.handshake',
  'setup.inspect',
  'workspace.initialize',
  'workspace.snapshot',
  'workspace.update_defaults',
  'experiment.create',
  'provider.experiments',
  'experiment.bind_provider',
  'operation.inspect',
  'operation.plan',
  'operation.read',
  'operation.approve',
  'operation.cancel',
];

const requestLine = ({id, method, params}: ControlRequest) =>
  JSON.stringify({v: CONTROL_VERSION, id, method, params});
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(item => typeof item === 'string');
const isNullableString = (value: unknown): value is string | null =>
  value === null || typeof value === 'string';
const isApprovalMode = (value: unknown): value is ApprovalMode | null =>
  value === null || value === 'standard' || value === 'destructive';
const isOperationAction = (value: unknown): value is OperationAction =>
  value === 'reserve' || value === 'up' || value === 'verify' || value === 'recover' || value === 'down';

export const findWorkspaceStart = (
  start: string,
  override: string | undefined = process.env.SYNTHRAN_WORKSPACE,
): string => {
  if (override) {
    const candidate = resolve(override);
    return basename(candidate) === '.synthran' ? dirname(candidate) : candidate;
  }

  let candidate = resolve(start);
  let gitRoot: string | null = null;
  while (true) {
    if (existsSync(join(candidate, '.synthran', 'workspace.toml'))) return candidate;
    if (gitRoot === null && existsSync(join(candidate, '.git'))) gitRoot = candidate;
    const parent = dirname(candidate);
    if (parent === candidate) return gitRoot ?? resolve(start);
    candidate = parent;
  }
};

const isAccessEntry = (value: unknown): value is ControlAccessEntry => {
  if (!isRecord(value)) return false;
  return (
    typeof value.configured === 'boolean' &&
    typeof value.fresh === 'boolean' &&
    typeof value.verified === 'boolean' &&
    isNullableString(value.verified_at_utc) &&
    isNullableString(value.refresh_after_utc) &&
    isNullableString(value.access_until_utc) &&
    (value.subject === undefined || isNullableString(value.subject)) &&
    (value.slice === undefined || isNullableString(value.slice)) &&
    (value.identity_name === undefined || isNullableString(value.identity_name))
  );
};

const isHandshake = (value: unknown): value is HandshakeResult => {
  if (!isRecord(value)) return false;
  const methods = value.methods;
  if (!isStringArray(methods)) return false;
  return (
    value.service === 'synthran-control' &&
    value.protocol === CONTROL_VERSION &&
    value.local_writes === true &&
    value.provider_reads === true &&
    value.provider_mutation === false &&
    methods.length === REQUIRED_METHODS.length &&
    REQUIRED_METHODS.every(method => methods.includes(method))
  );
};

const isSetupProfile = (value: unknown): value is SetupProfile => {
  if (!isRecord(value)) return false;
  return (
    typeof value.name === 'string' &&
    isNullableString(value.slices_username) &&
    isNullableString(value.r2lab_slice) &&
    isNullableString(value.identity_name)
  );
};

const isSetupSnapshot = (value: unknown): value is SetupSnapshot => {
  if (!isRecord(value) || !isRecord(value.defaults)) return false;
  return (
    typeof value.workspace_initialized === 'boolean' &&
    Array.isArray(value.profiles) &&
    value.profiles.every(isSetupProfile) &&
    isStringArray(value.ssh_identities) &&
    typeof value.defaults.profile === 'string' &&
    typeof value.defaults.project === 'string' &&
    typeof value.defaults.slices_username === 'string' &&
    typeof value.defaults.r2lab_slice === 'string' &&
    Number.isInteger(value.defaults.reservation_minutes) &&
    (value.defaults.placement === 'automatic' || value.defaults.placement === 'manual')
  );
};

const isObservation = (value: unknown): value is ControlSnapshot['observations'][number] => {
  if (!isRecord(value)) return false;
  return (
    typeof value.name === 'string' &&
    typeof value.state === 'string' &&
    typeof value.fresh === 'boolean' &&
    isNullableString(value.source) &&
    isNullableString(value.ownership) &&
    typeof value.detail === 'string'
  );
};

const isSnapshot = (value: unknown): value is ControlSnapshot => {
  if (!isRecord(value)) return false;
  const workspace = value.workspace;
  const experiment = value.experiment;
  const access = value.access;
  if (!isRecord(workspace) || !isRecord(experiment) || !isRecord(access)) return false;
  return (
    typeof workspace.profile === 'string' &&
    typeof workspace.project === 'string' &&
    typeof workspace.reservation_minutes === 'number' &&
    Number.isInteger(workspace.reservation_minutes) &&
    typeof workspace.placement === 'string' &&
    isNullableString(experiment.id) &&
    isNullableString(experiment.provider_experiment) &&
    isNullableString(experiment.intent) &&
    isNullableString(experiment.radio_mode) &&
    typeof experiment.lifecycle === 'string' &&
    isAccessEntry(access.slices) &&
    isAccessEntry(access.r2lab) &&
    Array.isArray(value.observations) &&
    value.observations.every(isObservation) &&
    isStringArray(value.next_steps) &&
    isStringArray(value.blocks)
  );
};

const hasSafeStringMap = (value: unknown): value is Record<string, string> =>
  isRecord(value) && Object.entries(value).every(([key, item]) => key.length > 0 && typeof item === 'string');

const isOperationInspection = (value: unknown): value is OperationInspection => {
  if (!isRecord(value)) return false;
  return (
    isOperationAction(value.action) &&
    typeof value.kind === 'string' &&
    typeof value.risk === 'string' &&
    typeof value.mutates === 'boolean' &&
    typeof value.reason === 'string' &&
    typeof value.approval_required === 'boolean' &&
    isApprovalMode(value.approval_mode) &&
    isStringArray(value.targets) &&
    typeof value.can_plan === 'boolean' &&
    isNullableString(value.plan_block)
  );
};

const isOperationPlan = (value: unknown): value is OperationPlanView => {
  if (!isRecord(value)) return false;
  return (
    typeof value.operation_id === 'string' && OPERATION_ID_RE.test(value.operation_id) &&
    typeof value.experiment_id === 'string' &&
    typeof value.kind === 'string' &&
    typeof value.risk === 'string' &&
    typeof value.mutates === 'boolean' &&
    typeof value.reason === 'string' &&
    typeof value.approval_required === 'boolean' &&
    isApprovalMode(value.approval_mode) &&
    isStringArray(value.targets) &&
    typeof value.created_at_utc === 'string'
  );
};

const isOperationState = (value: unknown): value is OperationStateView => {
  if (!isRecord(value)) return false;
  return (
    typeof value.schema === 'string' &&
    typeof value.operation_id === 'string' && OPERATION_ID_RE.test(value.operation_id) &&
    typeof value.status === 'string' &&
    typeof value.risk === 'string' &&
    typeof value.mutates === 'boolean' &&
    typeof value.plan_sha256 === 'string' &&
    typeof value.updated_at_utc === 'string' &&
    typeof value.claim_held === 'boolean'
  );
};

const isOperationApproval = (value: unknown): value is OperationApprovalView => {
  if (!isRecord(value)) return false;
  return (
    typeof value.schema === 'string' &&
    typeof value.operation_id === 'string' && OPERATION_ID_RE.test(value.operation_id) &&
    typeof value.plan_sha256 === 'string' &&
    typeof value.risk === 'string' &&
    (value.mode === 'standard' || value.mode === 'destructive') &&
    typeof value.approved_at_utc === 'string'
  );
};

const isOperationEvent = (value: unknown): value is OperationEventView => {
  if (!isRecord(value)) return false;
  return (
    typeof value.schema === 'string' &&
    typeof value.event_id === 'string' &&
    typeof value.operation_id === 'string' && OPERATION_ID_RE.test(value.operation_id) &&
    Number.isInteger(value.sequence) &&
    typeof value.event_type === 'string' &&
    typeof value.occurred_at_utc === 'string' &&
    typeof value.risk === 'string' &&
    typeof value.mutates === 'boolean' &&
    typeof value.plan_sha256 === 'string' &&
    hasSafeStringMap(value.attributes)
  );
};

const isOperationSnapshot = (value: unknown): value is OperationSnapshot => {
  if (!isRecord(value)) return false;
  return (
    isOperationPlan(value.plan) &&
    isOperationState(value.state) &&
    (value.approval === null || isOperationApproval(value.approval)) &&
    Array.isArray(value.events) && value.events.every(isOperationEvent)
  );
};

const parseResponse = (line: string): ControlResponse<unknown> => {
  const value: unknown = JSON.parse(line);
  if (!isRecord(value)) throw new Error('invalid control response');
  if (
    value.v !== CONTROL_VERSION ||
    !isNullableString(value.id) ||
    typeof value.ok !== 'boolean'
  ) {
    throw new Error('invalid control response');
  }
  return value as unknown as ControlResponse<unknown>;
};

const parseResponses = (output: string, expectedIds: readonly string[]) => {
  const responses = output
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(parseResponse);

  if (responses.length !== expectedIds.length) {
    throw new Error('SynthRAN control service returned an unexpected response set');
  }
  for (const id of expectedIds) {
    if (responses.filter(item => item.id === id).length !== 1) {
      throw new Error('SynthRAN control service returned an unexpected response set');
    }
  }
  return responses;
};

const requireHandshake = (responses: ControlResponse<unknown>[]) => {
  const handshake = responses.find(item => item.id === 'handshake');
  if (!handshake?.ok || !isHandshake(handshake.result)) {
    throw new Error('SynthRAN control handshake is incompatible');
  }
};

const requireSnapshot = (responses: ControlResponse<unknown>[]): ControlSnapshot => {
  const snapshot = responses.find(item => item.id === 'snapshot');
  if (!snapshot?.ok || !isSnapshot(snapshot.result)) {
    throw new Error('SynthRAN control service did not provide a usable local snapshot');
  }
  return snapshot.result;
};

const controlError = (response: ControlResponse<unknown> | undefined, fallback: string) => {
  if (!response || response.ok) return fallback;
  const message = response.error?.message;
  return typeof message === 'string' && message.length <= 512 ? message : fallback;
};

export const parseControlOutput = (output: string): ControlSnapshot => {
  const responses = parseResponses(output, ['handshake', 'snapshot']);
  requireHandshake(responses);
  return requireSnapshot(responses);
};

const runControl = async (
  requests: ControlRequest[],
  options: RunOptions = {},
): Promise<ControlResponse<unknown>[]> =>
  new Promise((resolveResponses, reject) => {
    const {signal, timeoutMs = LOCAL_RESPONSE_TIMEOUT_MS} = options;
    if (signal?.aborted) {
      reject(new Error('SynthRAN control request was cancelled'));
      return;
    }

    const python = process.env.SYNTHRAN_PYTHON || 'python';
    const workspaceStart = findWorkspaceStart(process.cwd());
    const child = spawn(python, ['-m', 'synthran.control'], {
      cwd: workspaceStart,
      env: process.env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    let output = '';
    let settled = false;
    let timer: NodeJS.Timeout | undefined;

    const removeAbortListener = () => {
      signal?.removeEventListener('abort', onAbort);
    };

    const finishError = (message: string) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      removeAbortListener();
      if (child.exitCode === null && !child.killed) child.kill();
      reject(new Error(message));
    };

    const finishSuccess = (responses: ControlResponse<unknown>[]) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      removeAbortListener();
      resolveResponses(responses);
    };

    const onAbort = () => finishError('SynthRAN control request was cancelled');
    signal?.addEventListener('abort', onAbort, {once: true});
    if (signal?.aborted) {
      onAbort();
      return;
    }

    timer = setTimeout(
      () => finishError('SynthRAN control service did not return in time'),
      timeoutMs,
    );

    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk: string) => {
      output += chunk;
      if (Buffer.byteLength(output, 'utf8') > MAX_RESPONSE_BYTES) {
        finishError('SynthRAN control response exceeded the safe size limit');
      }
    });
    child.stderr.resume();
    child.on('error', () => finishError('SynthRAN control service could not be started'));
    child.on('close', (code: number | null) => {
      if (settled) return;
      if (code !== 0) {
        finishError('SynthRAN control service exited before returning a response');
        return;
      }

      try {
        finishSuccess(parseResponses(output, requests.map(item => item.id)));
      } catch (error) {
        finishError(
          error instanceof Error
            ? error.message
            : 'SynthRAN control service returned malformed data',
        );
      }
    });

    child.stdin.end(`${requests.map(requestLine).join('\n')}\n`);
  });

export const inspectSetup = async (signal?: AbortSignal): Promise<SetupSnapshot> => {
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {id: 'setup', method: 'setup.inspect', params: {}},
    ],
    {signal},
  );
  requireHandshake(responses);
  const setup = responses.find(item => item.id === 'setup');
  if (!setup?.ok || !isSetupSnapshot(setup.result)) {
    throw new Error(controlError(setup, 'SynthRAN first-use configuration could not be inspected'));
  }
  return setup.result;
};

export const initializeWorkspace = async (
  input: WorkspaceInitializeInput,
  signal?: AbortSignal,
): Promise<ControlSnapshot> => {
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {
        id: 'initialize',
        method: 'workspace.initialize',
        params: {
          profile_name: input.profileName,
          project: input.project,
          reuse_profile: input.reuseProfile,
          slices_username: input.slicesUsername ?? null,
          r2lab_slice: input.r2labSlice ?? null,
          r2lab_identity: input.r2labIdentity ?? null,
          reservation_minutes: input.reservationMinutes,
          placement: input.placement,
        },
      },
      {id: 'snapshot', method: 'workspace.snapshot', params: {}},
    ],
    {signal, timeoutMs: PROVIDER_RESPONSE_TIMEOUT_MS},
  );
  requireHandshake(responses);
  const initialized = responses.find(item => item.id === 'initialize');
  if (!initialized?.ok) {
    throw new Error(controlError(initialized, 'SynthRAN workspace could not be initialized'));
  }
  return requireSnapshot(responses);
};

export const readLocalSnapshot = async (signal?: AbortSignal): Promise<ControlSnapshot> => {
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {id: 'snapshot', method: 'workspace.snapshot', params: {}},
    ],
    {signal},
  );
  requireHandshake(responses);
  return requireSnapshot(responses);
};

export const updateWorkspaceDefaults = async (
  input: WorkspaceDefaultsInput,
  signal?: AbortSignal,
): Promise<ControlSnapshot> => {
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {
        id: 'defaults',
        method: 'workspace.update_defaults',
        params: {
          reservation_minutes: input.reservationMinutes,
          placement: input.placement,
        },
      },
      {id: 'snapshot', method: 'workspace.snapshot', params: {}},
    ],
    {signal},
  );
  requireHandshake(responses);
  const defaults = responses.find(item => item.id === 'defaults');
  if (!defaults?.ok) {
    throw new Error(controlError(defaults, 'SynthRAN workspace defaults could not be updated'));
  }
  return requireSnapshot(responses);
};

export const createLocalExperiment = async (
  input: ExperimentCreateInput,
  signal?: AbortSignal,
): Promise<ControlSnapshot> => {
  const params: Record<string, unknown> = {
    intent: input.intent,
    radio_mode: input.radioMode,
  };
  if (input.label !== undefined) params.label = input.label;

  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {id: 'create', method: 'experiment.create', params},
      {id: 'snapshot', method: 'workspace.snapshot', params: {}},
    ],
    {signal},
  );
  requireHandshake(responses);
  const create = responses.find(item => item.id === 'create');
  if (!create?.ok) {
    throw new Error(controlError(create, 'SynthRAN local configuration could not be created'));
  }
  return requireSnapshot(responses);
};

export const listProviderExperiments = async (signal?: AbortSignal): Promise<string[]> => {
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {id: 'providers', method: 'provider.experiments', params: {}},
    ],
    {signal, timeoutMs: PROVIDER_RESPONSE_TIMEOUT_MS},
  );
  requireHandshake(responses);
  const providerResponse = responses.find(item => item.id === 'providers');
  if (!providerResponse?.ok || !isRecord(providerResponse.result)) {
    throw new Error(controlError(providerResponse, 'SLICES experiments could not be loaded'));
  }
  const experiments = providerResponse.result.experiments;
  if (
    !isStringArray(experiments) ||
    experiments.some(name => !PROVIDER_NAME_RE.test(name)) ||
    new Set(experiments).size !== experiments.length
  ) {
    throw new Error('SLICES experiment list was malformed');
  }
  return experiments;
};

export const bindProviderExperiment = async (
  providerExperiment: string,
  signal?: AbortSignal,
): Promise<ControlSnapshot> => {
  if (!PROVIDER_NAME_RE.test(providerExperiment)) {
    throw new Error('SLICES experiment name is invalid');
  }
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {
        id: 'bind',
        method: 'experiment.bind_provider',
        params: {provider_experiment: providerExperiment},
      },
      {id: 'snapshot', method: 'workspace.snapshot', params: {}},
    ],
    {signal, timeoutMs: PROVIDER_RESPONSE_TIMEOUT_MS},
  );
  requireHandshake(responses);
  const bind = responses.find(item => item.id === 'bind');
  if (!bind?.ok) {
    throw new Error(controlError(bind, 'SLICES experiment could not be bound'));
  }
  return requireSnapshot(responses);
};

export const inspectOperation = async (
  action: OperationAction,
  signal?: AbortSignal,
): Promise<OperationInspection> => {
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {id: 'operation', method: 'operation.inspect', params: {action}},
    ],
    {signal},
  );
  requireHandshake(responses);
  const response = responses.find(item => item.id === 'operation');
  if (!response?.ok || !isOperationInspection(response.result)) {
    throw new Error(controlError(response, 'SynthRAN operation could not be inspected'));
  }
  return response.result;
};

const requireOperationSnapshot = (
  responses: ControlResponse<unknown>[],
  id: string,
  fallback: string,
): OperationSnapshot => {
  const response = responses.find(item => item.id === id);
  if (!response?.ok || !isOperationSnapshot(response.result)) {
    throw new Error(controlError(response, fallback));
  }
  return response.result;
};

export const planOperation = async (
  action: OperationAction,
  signal?: AbortSignal,
): Promise<OperationSnapshot> => {
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {id: 'operation', method: 'operation.plan', params: {action}},
    ],
    {signal},
  );
  requireHandshake(responses);
  return requireOperationSnapshot(responses, 'operation', 'SynthRAN operation plan could not be created');
};

export const readOperation = async (
  operationId: string,
  signal?: AbortSignal,
): Promise<OperationSnapshot> => {
  if (!OPERATION_ID_RE.test(operationId)) throw new Error('SynthRAN operation ID is invalid');
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {id: 'operation', method: 'operation.read', params: {operation_id: operationId}},
    ],
    {signal},
  );
  requireHandshake(responses);
  return requireOperationSnapshot(responses, 'operation', 'SynthRAN operation could not be read');
};

export const approveOperation = async (
  operationId: string,
  mode: ApprovalMode,
  signal?: AbortSignal,
): Promise<OperationSnapshot> => {
  if (!OPERATION_ID_RE.test(operationId)) throw new Error('SynthRAN operation ID is invalid');
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {
        id: 'operation',
        method: 'operation.approve',
        params: {operation_id: operationId, mode},
      },
    ],
    {signal},
  );
  requireHandshake(responses);
  return requireOperationSnapshot(responses, 'operation', 'SynthRAN operation approval could not be recorded');
};

export const cancelOperation = async (
  operationId: string,
  signal?: AbortSignal,
): Promise<OperationSnapshot> => {
  if (!OPERATION_ID_RE.test(operationId)) throw new Error('SynthRAN operation ID is invalid');
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {id: 'operation', method: 'operation.cancel', params: {operation_id: operationId}},
    ],
    {signal},
  );
  requireHandshake(responses);
  return requireOperationSnapshot(responses, 'operation', 'SynthRAN operation could not be cancelled');
};
