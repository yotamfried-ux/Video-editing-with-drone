#!/usr/bin/env node
// Operator CLI: import pipeline evidence into the Studio (local, explicit; the server API accepts JSON only).
//   gt-import.mjs edl EDL.json [--output REEL.mp4]     copies the rendered reel next to the Studio for Editing Review playback
//   gt-import.mjs predictions PREDICTIONS.json
import { readFileSync, copyFileSync, mkdirSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createContext } from '../server/context.mjs';
import { importEdl, importPipelinePredictions } from '../server/imports.mjs';

const [cmd, file, ...rest] = process.argv.slice(2);
const home = process.env.STUDIO_HOME ?? path.join(os.homedir(), '.sportreel-annotation-studio');
const ctx = createContext(home);
const json = JSON.parse(readFileSync(file, 'utf8'));
if (cmd === 'edl') {
  const i = rest.indexOf('--output');
  if (i >= 0) {
    mkdirSync(ctx.outputsDir, { recursive: true });
    const name = `${json.output_id}${path.extname(rest[i + 1]) || '.mp4'}`;
    copyFileSync(rest[i + 1], path.join(ctx.outputsDir, name));
    json.output_file = name;
  }
  console.log(JSON.stringify(importEdl(ctx.db, json)));
} else if (cmd === 'predictions') console.log(JSON.stringify(importPipelinePredictions(ctx.db, json)));
else { console.error('usage: gt-import.mjs edl EDL.json [--output REEL.mp4] | predictions FILE'); process.exit(2); }
ctx.db.close?.();
