import React from 'react';
import {Box, Text} from 'ink';

import type {
  OperationAction,
  OperationInspection,
  OperationSnapshot,
} from '../backend/control.js';
import type {ObservationView, SectionLabel, WorkbenchMode, WorkbenchState} from '../model.js';
import {theme} from '../theme.js';

interface OperationPanelProps {
  section: Extract<SectionLabel, 'Resources' | 'Network'>;
  state: WorkbenchState;
  mode: WorkbenchMode;
  action: OperationAction;
  inspection: OperationInspection | null;
  operation: OperationSnapshot | null;
  busy: boolean;
  notice: string | null;
}

const actionLabels: Record<OperationAction, string> = {
  reserve: 'Reserve',
  up: 'Bring up',
  verify: 'Verify',
  recover: 'Recover',
  down: 'Tear down',
};

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
  return `${item.fresh ? '●' : '○'} ${item.state}${item.fresh ? '' : ' · stale'}`;
};

const riskLabel = (risk: string) => {
  if (risk === 'R3') return 'Destructive change';
  if (risk === 'R2') return 'Controlled change';
  if (risk === 'R1') return 'Live read only';
  return 'Local read only';
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
  if (event.event_type === 'approval.requested') return 'Approval requested';
  if (event.event_type === 'approval.granted') return 'Approval recorded';
  if (event.event_type === 'operation.interrupted') return 'Action cancelled';
  if (event.event_type === 'recovery.required') return 'Recovery required';
  if (event.event_type === 'operation.completed') return 'Action complete';
  if (event.event_type === 'operation.failed') return 'Action failed';
  return event.event_type.replaceAll('.', ' ');
};

const ActionStrip = ({selected}: {selected: OperationAction}) => (
  <Box marginTop={1} marginBottom={1}>
    {(Object.keys(actionLabels) as OperationAction[]).map(action => (
      <Box key={action} marginRight={1}>
        <Text inverse={action === selected} color={action === selected ? undefined : theme.muted}>
          {` ${actionLabels[action]} `}
        </Text>
      </Box>
    ))}
  </Box>
);

export const OperationPanel = ({
  section,
  state,
  mode,
  action,
  inspection,
  operation,
  busy,
  notice,
}: OperationPanelProps) => {
  const isResources = section === 'Resources';
  const currentRisk = operation?.plan.risk ?? inspection?.risk ?? null;
  const currentReason = operation?.plan.reason ?? inspection?.reason ?? null;
  const lastEvents = operation?.events.slice(-5) ?? [];

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color={theme.bodyStrong}>{section}</Text>
      <Text color={theme.muted}>
        {isResources
          ? 'Reservation, allocation and preparation state.'
          : '5G runtime and end-to-end path state.'}
      </Text>
      <Box height={1} />

      {isResources ? (
        <>
          <Row label="Reservation" value={observedValue(observation(state, 'reservation'))} />
          <Row label="Allocation" value={observedValue(observation(state, 'allocation'))} />
          <Row label="Preparation" value={observedValue(observation(state, 'preparation'))} />
        </>
      ) : (
        <>
          <Row label="Core" value={observedValue(observation(state, 'core'))} />
          <Row label="RAN / gNB" value={observedValue(observation(state, 'ran'))} />
          <Row label="UE" value={observedValue(observation(state, 'ue'))} />
          <Row label="PDU" value={observedValue(observation(state, 'pdu'))} />
          <Row label="UPF" value={observedValue(observation(state, 'upf'))} />
          <Row label="Path" value={observedValue(observation(state, 'path'))} />
        </>
      )}
      <Row label="Lifecycle" value={state.lifecycle} />
      {state.blocks.length > 0 ? <Row label="Blocked" value={state.blocks[0]} /> : null}

      <Box borderTop borderStyle="single" borderColor={theme.hairline} marginTop={1} paddingTop={1} flexDirection="column">
        <Text color={theme.muted}>Actions</Text>
        <ActionStrip selected={action} />

        {inspection ? (
          <>
            <Row label="Change" value={riskLabel(inspection.risk)} />
            <Row label="Why" value={inspection.reason} />
            {inspection.plan_block ? <Row label="Needs" value={inspection.plan_block} /> : null}
          </>
        ) : null}

        {operation ? (
          <>
            <Row label="Action ID" value={operation.plan.operation_id} />
            <Row label="Status" value={operation.state.status} />
            <Row label="Approval" value={operation.approval ? 'Recorded' : operation.plan.approval_required ? 'Required' : 'Not required'} />
            {operation.plan.targets.length > 0 ? <Row label="Targets" value={operation.plan.targets.join(', ')} /> : null}
          </>
        ) : null}

        {currentRisk ? <Row label="Safety" value={riskLabel(currentRisk)} /> : null}
        {currentReason && !inspection ? <Row label="Why" value={currentReason} /> : null}

        {lastEvents.length > 0 ? (
          <Box flexDirection="column" marginTop={1}>
            <Text color={theme.muted}>Recent activity</Text>
            {lastEvents.map(event => (
              <Text key={event.event_id} color={theme.bodyStrong}>  {eventText(event)}</Text>
            ))}
          </Box>
        ) : null}

        <Box marginTop={1}>
          <Text color={theme.muted}>
            {busy
              ? 'Working…'
              : '←→ Choose   Enter Review   p Prepare   a Approve   d Approve teardown   x Cancel'}
          </Text>
        </Box>
        <Text color={theme.muted}>
          {mode === 'OPERATE'
            ? 'OPERATE permits local action records. Provider execution remains disabled.'
            : 'OBSERVE reviews current state without provider mutation.'}
        </Text>

        {notice ? (
          <Box marginTop={1}>
            <Text color={notice.toLowerCase().includes('could not') || notice.toLowerCase().includes('required') ? theme.error : theme.bodyStrong}>
              {notice}
            </Text>
          </Box>
        ) : null}
      </Box>
    </Box>
  );
};
