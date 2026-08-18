#!/usr/bin/env node

import React from 'react';
import {render} from 'ink';

import {App} from './app.js';

// The workbench binds an existing SLICES experiment explicitly in durable state.
// A legacy scripted-workflow override must not retarget or block that workspace.
delete process.env.SYNTHRAN_SLICES_EXPERIMENT;

const instance = render(<App />);
await instance.waitUntilExit();
