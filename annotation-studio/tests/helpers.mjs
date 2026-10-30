import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createContext } from '../server/context.mjs';

export { makeVideo } from '../scripts/synthetic.mjs';

export function tmp(prefix = 'studio-test-') { return mkdtempSync(path.join(os.tmpdir(), prefix)); }
export function newCtx(opts) { const home = tmp(); return createContext(home, { token: 'test-token', ...opts }); }
export const seg = (id, s, e, o = {}) => ({ id, start_frame: s, end_frame: e, athlete_id: null, event_type: 'wave_ride', decision: 'include', reason_code: null, notes: '', framing_mode: null, target: null, ...o });
export const kf = (id, segment_id, frame, bbox, o = {}) => ({ id, segment_id, frame, bbox, visibility: 'visible', origin: 'manual', ...o });
export { writeFileSync };
