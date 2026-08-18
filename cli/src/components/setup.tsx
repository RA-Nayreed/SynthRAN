import React from 'react';
import {Box, Text} from 'ink';

import type {PlacementMode, SetupProfile} from '../backend/control.js';
import type {WorkbenchMode} from '../model.js';
import {theme} from '../theme.js';

export interface SetupDraftView {
  reuseProfile: boolean;
  profileName: string;
  project: string;
  slicesUsername: string;
  r2labEnabled: boolean;
  r2labSlice: string;
  identityReference: string | null;
  reservationMinutes: number;
  placement: PlacementMode;
}

interface SetupPanelProps {
  profiles: SetupProfile[];
  selectedProfile: SetupProfile | null;
  draft: SetupDraftView;
  focusedIndex: number;
  mode: WorkbenchMode;
  busy: boolean;
  notice: string | null;
}

const Row = ({label, value, focused = false}: {label: string; value: string; focused?: boolean}) => (
  <Box marginBottom={1}>
    <Box width={24}>
      <Text color={focused ? theme.bodyStrong : theme.muted}>{focused ? '› ' : '  '}{label}</Text>
    </Box>
    <Text color={theme.bodyStrong} inverse={focused}>{focused ? ` ${value} ` : value}</Text>
  </Box>
);

const profileValue = (
  profiles: SetupProfile[],
  selected: SetupProfile | null,
  draft: SetupDraftView,
) => {
  if (draft.reuseProfile && selected) return `${selected.name} · reuse`;
  if (profiles.length === 0) return 'New profile';
  return 'New profile';
};

export const SetupPanel = ({
  profiles,
  selectedProfile,
  draft,
  focusedIndex,
  mode,
  busy,
  notice,
}: SetupPanelProps) => {
  const reused = draft.reuseProfile && selectedProfile !== null;
  const r2labConfigured = reused
    ? selectedProfile.r2lab_slice !== null
    : draft.r2labEnabled;
  const username = reused
    ? selectedProfile.slices_username ?? 'Missing in profile'
    : draft.slicesUsername || 'Type username';
  const slice = reused
    ? selectedProfile.r2lab_slice ?? 'Not configured'
    : draft.r2labEnabled
      ? draft.r2labSlice || 'Type slice'
      : 'Disabled';
  const identity = reused
    ? selectedProfile.identity_name ?? 'Not configured'
    : draft.r2labEnabled
      ? draft.identityReference ?? 'No private identity found'
      : 'Disabled';

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color={theme.bodyStrong}>First-use configuration</Text>
      <Text color={theme.muted}>Provider access is verified read-only before local state is created.</Text>
      <Box height={1} />

      <Row label="Profile source" value={profileValue(profiles, selectedProfile, draft)} focused={focusedIndex === 0} />
      <Row label="Profile name" value={draft.profileName || 'Type profile name'} focused={focusedIndex === 1} />
      <Row label="SLICES project" value={draft.project || 'Type project'} focused={focusedIndex === 2} />
      <Row label="SLICES username" value={username} focused={focusedIndex === 3} />
      <Row label="R2Lab" value={r2labConfigured ? 'Enabled' : 'Disabled'} focused={focusedIndex === 4} />
      <Row label="R2Lab slice" value={slice} focused={focusedIndex === 5} />
      <Row label="SSH identity" value={identity} focused={focusedIndex === 6} />
      <Row label="Reservation" value={`${draft.reservationMinutes} minutes`} focused={focusedIndex === 7} />
      <Row label="Placement" value={draft.placement} focused={focusedIndex === 8} />
      <Row
        label="Initialize"
        value={busy ? 'Verifying access…' : mode === 'OPERATE' ? 'Enter' : 'Switch to OPERATE'}
        focused={focusedIndex === 9}
      />

      <Box height={1} />
      <Row label="Mode" value={mode} />
      <Text color={theme.muted}>Type into text rows · ←/→ changes choices · m toggles mode</Text>

      {notice ? (
        <Box marginTop={1}>
          <Text color={theme.muted}>{notice}</Text>
        </Box>
      ) : null}
    </Box>
  );
};
