import React from 'react';
import {Box, Text} from 'ink';

import type {OperationSnapshot} from '../backend/control.js';
import {
  operationKindLabel,
  type OperatorActionView,
} from '../backend/operator-actions.js';
import type {ObservationView, SectionLabel, WorkbenchState} from '../model.js';
import {theme} from '../theme.js';

interface OperationPanelProps {
  section: Extract<SectionLabel, 'Resources' | 'Network'>;
  state: WorkbenchState;
  primary: OperatorActionView | null;
  secondary: OperatorActionView | null;
  operation: OperationSnapshot | null;
  operationLabel: string | null;
  busy: boolean;
  notice: string | null;
}

const Row = ({label, value}: {label: string; value: string}) => (
  <Box marginBottom={1}>
    <Box width={22}><Text color={theme.muted}>{label}</Text></Box>
    <Text color={theme.bodyStrong}>{value}</Text>
  </Box>
);

const observation = (state: WorkbenchState, name: string): ObservationView | undefined =>
  state.observations.find(item => item.name === name);

const observedValue = (item: ObservationView | undefined) => {
  if (!item) return '—';
  return `${item.fresh ? '✓' : '○'} ${item.state}${item.fresh ? '' : ' · stale'}`;
};

const eventText = (event: OperationSnapshot['events'][number]) => {
  if (event.event_type === 'stage.progress') {
    const stage = event.attributes.stage ?? 'work';
    const current = event.attributes.current ?? '?';
    const total = event.attributes.total ?? '?';
    return `${stage} · ${current}/${total}`;
  }
  if (event.event_type === 'stage.started') return `${event.attributes.stage ?? 'work'} started`;
  if (event.event_type === 'stage.completed') return `${event.attributes.stage ?? 'work'} complete`;
  if (event.event_type === 'stage.failed') return `${event.attributes.stage ?? 'work'} failed`;
  if (event.event_type === 'approval.granted') return 'Confirmation recorded';
  if (event.event_type === 'operation.authorized') return 'Execution authorized';
  if (event.event_type === 'operation.interrupted') return 'Action cancelled';
  if (event.event_type === 'recovery.required') return 'Recovery required';
  if (event.event_type === 'operation.completed') return 'Action complete';
  if (event.event_type === 'operation.failed') return 'Action failed';
  return event.event_type.replaceAll('.', ' ');
};

const pendingPrompt = (
  operation: OperationSnapshot | null,
  primary: OperatorActionView | null,
  operationLabel: string | null,
) => {
  if (!operation) return primary ? `Enter  ${primary.label}` : null;
  const label = operationKindLabel(operation.plan.kind, operationLabel ?? primary?.label ?? 'Continue');
  if (operation.state.status === 'planned' && operation.plan.approval_required) {
    return `Enter  Confirm ${label.toLowerCase()}`;
  }
  if (operation.state.status === 'planned' || operation.state.status === 'approved') {
    return `Enter  Execute ${label.toLowerCase()}`;
  }
  return null;
};

export const OperationPanel = ({
  section,
  state,
  primary,
  secondary,
  operation,
  operationLabel,
  busy,
  notice,
}: OperationPanelProps) => {
  const isResources = section === 'Resources';
  const lastEvents = operation?.events.slice(-5) ?? [];
  const prompt = pendingPrompt(operation, primary, operationLabel);
  const radioName = state.radio === 'physical' ? 'R2Lab' : 'RFSIM';
  const activeLabel = operation
    ? operationKindLabel(operation.plan.kind, operationLabel ?? primary?.label ?? 'Action')
    : null;

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color={theme.bodyStrong}>{isResources ? 'Resources' : '5G Network'}</Text>
      <Box height={1} />

      {isResources ? (
        <>
          <Row label="Reservation" value={observedValue(observation(state, 'reservation'))} />
          <Row label="Allocation" value={observedValue(observation(state, 'allocation'))} />
          <Row label="Preparation" value={observedValue(observation(state, 'preparation'))} />
        </>
      ) : (
        <>
          <Row label="Core / Open5GS" value={observedValue(observation(state, 'core'))} />
          <Row label="RAN / srsRAN" value={observedValue(observation(state, 'ran'))} />
          <Row label="UE / srsUE" value={observedValue(observation(state, 'ue'))} />
          <Row label={`Radio / ${radioName}`} value={observedValue(observation(state, 'radio'))} />
          <Row label="PDU session" value={observedValue(observation(state, 'pdu'))} />
          <Row label="UPF" value={observedValue(observation(state, 'upf'))} />
          <Row label="5G path" value={observedValue(observation(state, 'path'))} />
        </>
      )}
      <Row label="Status" value={state.lifecycle} />
      {state.blocks.length > 0 ? <Row label="Blocked" value={state.blocks[0]} /> : null}

      <Box borderTop borderStyle="single" borderColor={theme.hairline} marginTop={1} paddingTop={1} flexDirection="column">
        {operation ? (
          <>
            <Text bold color={theme.bodyStrong}>{activeLabel}</Text>
            <Row label="Action ID" value={operation.plan.operation_id} />
            <Row label="State" value={operation.state.status} />
            {operation.plan.targets.length > 0 ? <Row label="Targets" value={operation.plan.targets.join(', ')} /> : null}
            {operation.plan.approval_required ? (
              <Row label="Confirmation" value={operation.approval ? 'Recorded' : operation.plan.risk === 'R3' ? 'Destructive confirmation required' : 'Required'} />
            ) : null}
          </>
        ) : primary ? (
          <>
            <Text color={theme.muted}>Next</Text>
            <Text bold color={theme.bodyStrong}>  {primary.label}</Text>
          </>
        ) : state.lifecycle === 'PATH_PROVEN' ? (
          <>
            <Text color={theme.muted}>Next</Text>
            <Text bold color={theme.bodyStrong}>  Open Experiment</Text>
          </>
        ) : null}

        {lastEvents.length > 0 ? (
          <Box flexDirection="column" marginTop={1}>
            <Text color={theme.muted}>Recent activity</Text>
            {lastEvents.map(event => (
              <Text key={event.event_id} color={theme.bodyStrong}>  {eventText(event)}</Text>
            ))}
          </Box>
        ) : null}

        <Box marginTop={1} flexDirection="column">
          <Text color={theme.muted}>{busy ? 'Working…' : prompt ?? 'No infrastructure action is required.'}</Text>
          {!busy && secondary && !operation ? (
            <Text color={theme.muted}>s      {secondary.label}</Text>
          ) : null}
          {!busy && operation && ['planned', 'approved'].includes(operation.state.status) ? (
            <Text color={theme.muted}>x      Cancel prepared action</Text>
          ) : null}
        </Box>

        {notice ? (
          <Box marginTop={1}>
            <Text color={notice.toLowerCase().includes('could not') || notice.toLowerCase().includes('required') || notice.toLowerCase().includes('failed') ? theme.error : theme.bodyStrong}>
              {notice}
            </Text>
          </Box>
        ) : null}
      </Box>
    </Box>
  );
};
