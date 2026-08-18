import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {basename, dirname, join, resolve} from 'node:path';

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

export interface CreateExperimentResult {
  experiment_id: string;
  snapshot: ControlSnapshot;
}

interface HandshakeResult {
  service: string;
  protocol: number;
  provider_mutation: boolean;
  methods: string[];
  local_write_methods: string[];
}

interface ControlError {
  code: string;
  message: string;
}

interface ControlResponse<T> {
  v: number;
  id: string | null;
  ok: boolean;
  result?: T;
  error?: ControlError;
}

const CONTROL_VERSION = 2;
const MAX_RESPONSE_BYTES = 1024 * 1024;
const RESPONSE_TIMEOUT_MS = 10_000;
const EXPECTED_METHODS = ['experiment.create', 'system.handshake', 'workspace.snapshot'] as const;
const EXPECTED_LOCAL_WRITES = ['experiment.create'] as const;

const request = (id: string, method: string, params: Record<string, unknown> = {}) =>
  JSON.stringify({v: CONTROL_VERSION, id, method, params});
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(item => typeof item === 'string');
const isNullableString = (value: unknown): value is string | null =>
  value === null || typeof value === 'string';
const exactStrings = (value: unknown, expected: readonly string[]): value is string[] =>
  isStringArray(value) &&
  value.length === expected.length &&
  expected.every(item => value.includes(item));

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
    value.provider_mutation === false &&
    exactStrings(value.methods, EXPECTED_METHODS) &&
    exactStrings(value.local_write_methods, EXPECTED_LOCAL_WRITES)
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

const isCreateExperimentResult = (value: unknown): value is CreateExperimentResult => {
  if (!isRecord(value)) return false;
  return typeof value.experiment_id === 'string' && isSnapshot(value.snapshot);
};

const isControlError = (value: unknown): value is ControlError => {
  if (!isRecord(value)) return false;
  return (
    typeof value.code === 'string' &&
    value.code.length > 0 &&
    typeof value.message === 'string' &&
    value.message.length > 0 &&
    value.message.length <= 1024
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

const parseControlResult = <T>(
  output: string,
  targetId: string,
  validator: (value: unknown) => value is T,
  invalidMessage: string,
): T => {
  const responses = output
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(parseResponse);

  if (responses.length !== 2) {
    throw new Error('SynthRAN control service returned an unexpected response set');
  }

  const handshake = responses.find(item => item.id === 'handshake');
  const target = responses.find(item => item.id === targetId);
  if (!handshake?.ok || !isHandshake(handshake.result)) {
    throw new Error('SynthRAN control handshake is incompatible');
  }
  if (!target) throw new Error(invalidMessage);
  if (!target.ok) {
    if (isControlError(target.error)) throw new Error(target.error.message);
    throw new Error(invalidMessage);
  }
  if (!validator(target.result)) throw new Error(invalidMessage);
  return target.result;
};

export const parseControlOutput = (output: string): ControlSnapshot =>
  parseControlResult(
    output,
    'snapshot',
    isSnapshot,
    'SynthRAN control service did not provide a usable local snapshot',
  );

export const parseCreateOutput = (output: string): CreateExperimentResult =>
  parseControlResult(
    output,
    'create',
    isCreateExperimentResult,
    'SynthRAN control service did not confirm local experiment creation',
  );

const runLocalRequest = async <T>(
  targetId: string,
  method: string,
  params: Record<string, unknown>,
  parser: (output: string) => T,
  signal?: AbortSignal,
): Promise<T> =>
  new Promise((resolveResult, reject) => {
    if (signal?.aborted) {
      reject(new Error('SynthRAN local control request was cancelled'));
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

    const finishSuccess = (result: T) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      removeAbortListener();
      resolveResult(result);
    };

    const onAbort = () => finishError('SynthRAN local control request was cancelled');
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
    child.stdin.on('error', () =>
      finishError('SynthRAN control service closed its input unexpectedly'),
    );
    child.on('error', () => finishError('SynthRAN control service could not be started'));
    child.on('close', (code: number | null) => {
      if (settled) return;
      if (code !== 0) {
        finishError('SynthRAN control service exited before returning local state');
        return;
      }

      try {
        finishSuccess(parser(output));
      } catch (error) {
        finishError(
          error instanceof Error
            ? error.message
            : 'SynthRAN control service returned malformed data',
        );
      }
    });

    child.stdin.end(
      `${request('handshake', 'system.handshake')}\n${request(targetId, method, params)}\n`,
    );
  });

export const readLocalSnapshot = async (signal?: AbortSignal): Promise<ControlSnapshot> =>
  runLocalRequest('snapshot', 'workspace.snapshot', {}, parseControlOutput, signal);

export const createLocalExperiment = async (
  intent: string,
  radioMode: string,
  signal?: AbortSignal,
): Promise<CreateExperimentResult> =>
  runLocalRequest(
    'create',
    'experiment.create',
    {intent, radio_mode: radioMode},
    parseCreateOutput,
    signal,
  );
