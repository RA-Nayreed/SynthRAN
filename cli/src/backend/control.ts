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

interface HandshakeResult {
  service: string;
  protocol: number;
  read_only: boolean;
  methods: string[];
}

interface ControlResponse<T> {
  v: number;
  id: string | null;
  ok: boolean;
  result?: T;
  error?: {code: string; message: string};
}

const CONTROL_VERSION = 1;
const MAX_RESPONSE_BYTES = 1024 * 1024;
const RESPONSE_TIMEOUT_MS = 10_000;

const request = (id: string, method: string) =>
  JSON.stringify({v: CONTROL_VERSION, id, method, params: {}});
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
    value.read_only === true &&
    isStringArray(value.methods) &&
    value.methods.includes('system.handshake') &&
    value.methods.includes('workspace.snapshot')
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

export const parseControlOutput = (output: string): ControlSnapshot => {
  const responses = output
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(parseResponse);

  if (responses.length !== 2) {
    throw new Error('SynthRAN control service returned an unexpected response set');
  }

  const handshake = responses.find(item => item.id === 'handshake');
  const snapshot = responses.find(item => item.id === 'snapshot');
  if (!handshake?.ok || !isHandshake(handshake.result)) {
    throw new Error('SynthRAN control handshake is incompatible');
  }
  if (!snapshot?.ok || !isSnapshot(snapshot.result)) {
    throw new Error('SynthRAN control service did not provide a usable local snapshot');
  }
  return snapshot.result;
};

export const readLocalSnapshot = async (): Promise<ControlSnapshot> =>
  new Promise((resolveSnapshot, reject) => {
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

    const finishError = (message: string) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      if (!child.killed) child.kill();
      reject(new Error(message));
    };

    const finishSuccess = (snapshot: ControlSnapshot) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      resolveSnapshot(snapshot);
    };

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
        finishSuccess(parseControlOutput(output));
      } catch (error) {
        finishError(
          error instanceof Error
            ? error.message
            : 'SynthRAN control service returned malformed data',
        );
      }
    });

    child.stdin.end(
      `${request('handshake', 'system.handshake')}\n${request('snapshot', 'workspace.snapshot')}\n`,
    );
  });
