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

export interface ExperimentCreateInput {
  intent: ExperimentIntent;
  radioMode: ExperimentRadioMode;
  label?: string | null;
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

interface HandshakeResult {
  service: string;
  protocol: number;
  local_writes: boolean;
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

const CONTROL_VERSION = 2;
const MAX_RESPONSE_BYTES = 1024 * 1024;
const RESPONSE_TIMEOUT_MS = 10_000;
const REQUIRED_METHODS = ['system.handshake', 'workspace.snapshot', 'experiment.create'];

const requestLine = ({id, method, params}: ControlRequest) =>
  JSON.stringify({v: CONTROL_VERSION, id, method, params});
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(item => typeof item === 'string');
const isNullableString = (value: unknown): value is string | null =>
  value === null || typeof value === 'string';

export const findWorkspaceStart = (
  start: string,
  override: string | undefined = process.env.SYNTHRAN_WORKSPACE,
): string => {
  if (override) {
    const candidate = resolve(override);
    return basename(candidate) === '.synthran' ? dirname(candidate) : candidate;
  }

  let candidate = resolve(start);
  while (true) {
    if (existsSync(join(candidate, '.synthran', 'workspace.toml'))) return candidate;
    const parent = dirname(candidate);
    if (parent === candidate) return resolve(start);
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
  return (
    value.service === 'synthran-control' &&
    value.protocol === CONTROL_VERSION &&
    value.local_writes === true &&
    value.provider_mutation === false &&
    isStringArray(value.methods) &&
    REQUIRED_METHODS.every(method => value.methods.includes(method))
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
  signal?: AbortSignal,
): Promise<ControlResponse<unknown>[]> =>
  new Promise((resolveResponses, reject) => {
    if (signal?.aborted) {
      reject(new Error('SynthRAN local state request was cancelled'));
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

    const onAbort = () => finishError('SynthRAN local state request was cancelled');
    signal?.addEventListener('abort', onAbort, {once: true});
    if (signal?.aborted) {
      onAbort();
      return;
    }

    timer = setTimeout(
      () => finishError('SynthRAN control service did not return local state'),
      RESPONSE_TIMEOUT_MS,
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
        finishError('SynthRAN control service exited before returning local state');
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

export const readLocalSnapshot = async (signal?: AbortSignal): Promise<ControlSnapshot> => {
  const responses = await runControl(
    [
      {id: 'handshake', method: 'system.handshake', params: {}},
      {id: 'snapshot', method: 'workspace.snapshot', params: {}},
    ],
    signal,
  );
  requireHandshake(responses);
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
    signal,
  );
  requireHandshake(responses);
  const create = responses.find(item => item.id === 'create');
  if (!create?.ok) {
    throw new Error(controlError(create, 'SynthRAN local configuration could not be created'));
  }
  return requireSnapshot(responses);
};
