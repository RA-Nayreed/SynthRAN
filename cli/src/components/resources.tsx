import React from 'react';
import {Box, Text} from 'ink';

import type {ResourcePreview, ResourceStateView} from '../backend/control.js';
import type {WorkbenchState} from '../model.js';
import {theme} from '../theme.js';

interface ResourcesPanelProps {
  state: WorkbenchState;
  preview: ResourcePreview | null;
  busy: boolean;
  notice: string | null;
}

const Row = ({label, value}: {label: string; value: string}) => (
  <Box marginBottom={1}>
    <Box width={24}><Text color={theme.muted}>{label}</Text></Box>
    <Text color={theme.bodyStrong}>{value}</Text>
  </Box>
);

const resourceValue = (item: ResourceStateView) =>
  `${item.availability} · ${item.ownership}`;

export const ResourcesPanel = ({state, preview, busy, notice}: ResourcesPanelProps) => {
  const assignments = preview?.decision.selection.assignments ?? [];
  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color={theme.bodyStrong}>Resources</Text>
      <Text color={theme.muted}>Read-only placement preview. No reservation or allocation is performed.</Text>
      <Box height={1} />

      <Row label="Lifecycle" value={state.lifecycle} />
      <Row label="Next local action" value={state.nextSteps[0] ?? '—'} />

      <Box height={1} />
      <Text bold color={theme.bodyStrong}>Live SLICES compute</Text>
      {busy ? (
        <Text color={theme.muted}>Reading POS reservation and allocation state…</Text>
      ) : preview === null ? (
        <Text color={theme.muted}>Press Enter to read live SLICES inventory and preview placement.</Text>
      ) : (
        <Box flexDirection="column">
          <Row label="Observed" value={preview.inventory.observed_at_utc} />
          <Row label="Fresh until" value={preview.inventory.fresh_until_utc} />
          {preview.inventory.resources.map(item => (
            <Row key={item.resource_id} label={item.resource_id} value={resourceValue(item)} />
          ))}

          <Box height={1} />
          <Text bold color={theme.bodyStrong}>Selected placement</Text>
          {assignments.map(item => (
            <Row
              key={`${item.role}-${item.ordinal}`}
              label={`${item.role}${item.ordinal > 1 ? ` ${item.ordinal}` : ''}`}
              value={`${item.resource_id} · ${item.provider} · ${item.ownership}`}
            />
          ))}
          <Text color={theme.muted}>Press Enter to refresh the preview.</Text>
        </Box>
      )}

      {notice ? (
        <Box marginTop={1}>
          <Text color={theme.muted}>{notice}</Text>
        </Box>
      ) : null}
    </Box>
  );
};
