#!/usr/bin/env node
/**
 * Syncs `mobile/dist` static Expo Router web bundle into `web-api/public`
 * (`index.html` -> `_spa.html`, `_expo/`, `assets/`, `favicon.ico`) for same-origin Vercel co-hosting (§17 WEB-05).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const mobileDist = path.join(repoRoot, 'mobile', 'dist');
const webPublic = path.join(repoRoot, 'web-api', 'public');

if (!fs.existsSync(path.join(mobileDist, 'index.html'))) {
  throw new Error(`Missing mobile/dist/index.html — run "npx expo export --platform web" in mobile/ first.`);
}

fs.mkdirSync(webPublic, { recursive: true });

for (const sub of ['_expo', 'assets']) {
  const src = path.join(mobileDist, sub);
  const dst = path.join(webPublic, sub);
  if (fs.existsSync(dst)) {
    fs.rmSync(dst, { recursive: true, force: true });
  }
  if (fs.existsSync(src)) {
    fs.cpSync(src, dst, { recursive: true });
  }
}

for (const file of ['favicon.ico', 'metadata.json']) {
  const src = path.join(mobileDist, file);
  if (fs.existsSync(src)) {
    fs.copyFileSync(src, path.join(webPublic, file));
  }
}

fs.copyFileSync(path.join(mobileDist, 'index.html'), path.join(webPublic, '_spa.html'));
console.log('[sync-web-spa] Synced mobile/dist into web-api/public (_spa.html, _expo/, assets/).');
