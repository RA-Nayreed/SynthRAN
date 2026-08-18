import React from 'react';
import {Box, Text} from 'ink';

import type {ControlResourceSnapshot, ResourceView} from '../backend/control.js';
import type {WorkbenchState} from '../model.js';
import {theme} from '../theme.js';

interface ResourcePanelProps {
  state: WorkbenchState;
  inventory: ControlResourceSnapshot | null;
  loading: boolean;
  notice: string | null;
}

const Row = ({label, value}: {label: string; value: string}) => (
  <Box marginBottom={1}>
    <Box width={24}><Text color={theme.muted}>{label}</Text></Box>
    <Text color={theme.bodyStrong}>{value}</Text>
  </Box>
);

const stateLabel = (resource: ResourceView) => {
  const marker = resource.availability === 'available' ? '✓' : resource.availability === 'allocated' ? '●' : '○';
  const ownership = resource.ownership === 'unknown' ? '' : ` · ${resource.ownership}`;
  return `${marker} ${resource.availability}${ownership}`;
};

const providerLabel = (inventory: ControlResourceSnapshot, provider: string) => {
  const item = inventory.providers.find(candidate => candidate.provider === provider);
  if (!item) return 'not observed';
  const freshness = item.fresh ? 'fresh' : 'not fresh';
  const completeness = item.complete ? 'complete' : 'incomplete';
  return `${freshness} · ${completeness}`;
};

const ResourceGroup = ({title, resources}: {title: string; resources: ResourceView[]}) => (
  <Box flexDirection="column" marginBottom={1}>
    <Text bold color={theme.bodyStrong}>{title}</Text>
    {resources.map(resource => (
      <Box key={resource.resource_id}>
        <Box width={24}><Text color={theme.muted}>{resource.resource_id}</Text></Box>
        <Text color={theme.bodyStrong}>{stateLabel(resource)}</Text>
      </Box>
    ))}
  </Box>
);

export const ResourcePanel = ({state, inventory, loading, notice}: ResourcePanelProps) => {
  if (inventory === null) {
    return (
      <Box flexDirection="column" paddingX={1} paddingY={1}>
        <Text bold color={theme.bodyStrong}>Resources</Text>
        <Box height={1} />
        <Row label="Lifecycle" value={state.lifecycle} />
        <Row label="Live inventory" value={loading ? 'Reading provider state…' : 'Not loaded'} />
        <Text color={theme.muted}>
          Press Enter to read conservative provider state. No resource is reserved or selected.
        </Text>
        {notice ? <Box marginTop={1}><Text color={theme.muted}>{notice}</Text></Box> : null}
      </Box>
    );
  }

  const slices = inventory.resources.filter(item => item.provider === 'slices');
  const r2lab = inventory.resources.filter(item => item.provider === 'r2lab');
  const virtual = inventory.resources.filter(item => item.provider === 'virtual');

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color={theme.bodyStrong}>Resources</Text>
      <Text color={theme.muted}>Capability catalog and conservative live observations.</Text>
      <Box height={1} />
      <Row label="SLICES state" value={providerLabel(inventory, 'slices')} />
      <Row label="R2Lab state" value={providerLabel(inventory, 'r2lab')} />
      <Row label="Virtual state" value={providerLabel(inventory, 'virtual')} />
      <Box height={1} />
      <ResourceGroup title="SLICES compute" resources={slices} />
      <ResourceGroup title="R2Lab" resources={r2lab} />
      <ResourceGroup title="Virtual" resources={virtual} />
      <Text color={theme.muted}>
        Incomplete provider state cannot authorize resource selection or reservation.
      </Text>
      {notice ? <Box marginTop={1}><Text color={theme.muted}>{notice}</Text></Box> : null}
    </Box>
  );
};
