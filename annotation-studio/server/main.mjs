import path from 'node:path';
import os from 'node:os';
import { createContext } from './context.mjs';
import { createApp } from './app.mjs';
import { R2Archive, r2ConfigFromEnv } from './r2archive.mjs';

const home = process.env.STUDIO_HOME ?? path.join(os.homedir(), '.sportreel-annotation-studio');
// STUDIO_RECONCILE_ROOTS="/data/raw:raw/,/data/processed:processed/"
const roots = (process.env.STUDIO_RECONCILE_ROOTS ?? '').split(',').filter(Boolean).map(x => { const i = x.lastIndexOf(':'); return { dir: x.slice(0, i), prefix: x.slice(i + 1) }; });
// Protected remote archive when configured (dedicated bucket + token); otherwise the local write-once archive.
const archive = process.env.STUDIO_R2_BUCKET ? new R2Archive(r2ConfigFromEnv()) : undefined;
const ctx = createContext(home, { roots, archive });
const port = Number(process.env.STUDIO_PORT ?? 4173);
createApp(ctx).listen(port, '127.0.0.1', () => {
  console.log(`SportReel Annotation Studio\n  state: ${home}\n  open:  http://127.0.0.1:${port}/?t=${ctx.token}`);
});
