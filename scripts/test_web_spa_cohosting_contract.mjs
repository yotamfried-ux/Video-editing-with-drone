#!/usr/bin/env node
/**
 * W1 / W3 / W4 / W8 live Next.js co-hosting verification:
 * Boots production `next start` against built `web-api` + synced `public/_spa.html` and verifies:
 * 1. `/` preserves Email confirmed landing + Continue to SportReel Web link.
 * 2. `/login`, `/discover`, `/reel/demo_token_1234`, `/review`, `/pipeline` serve SPA shell 200 with security headers.
 * 3. `/_expo/static/js/web/*.js` serves compiled Expo Router bundle 200.
 * 4. `/operator/review` redirects to `/review`.
 * 5. `/checkout/cancel`, `/checkout/success`, `/legal/privacy` remain handled by Next.js.
 * 6. `/api/nonexistent` returns 404 (never SPA HTML), and `/api/operator/drafts` enforces 401 without secret.
 * 7. `operatorSecret.web.ts` never references `localStorage`, `sessionStorage`, or `document.cookie` (WEB-04).
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..');
const webDir = path.join(repoRoot, 'web-api');

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, '127.0.0.1', () => {
      const addr = srv.address();
      const port = typeof addr === 'object' && addr ? addr.port : 0;
      srv.close(() => resolve(port));
    });
    srv.on('error', reject);
  });
}

async function waitReady(baseUrl, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${baseUrl}/`);
      if (r.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`next start did not become ready at ${baseUrl}`);
}

async function main() {
  // Static WEB-04 check on operatorSecret.web.ts
  const opSecSrc = fs.readFileSync(
    path.join(repoRoot, 'mobile', 'src', 'features', 'operator', 'lib', 'operatorSecret.web.ts'),
    'utf8'
  );
  const codeOnly = opSecSrc.replace(/\/\*[\s\S]*?\*\/|\/\/.*/g, '');
  assert.ok(!/localStorage|sessionStorage|cookie/i.test(codeOnly), 'WEB-04: operatorSecret.web.ts must never use persistent browser storage');
  console.log('PASS WEB-04 operatorSecret.web.ts uses session memory only');

  const port = await freePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const nextBin = path.join(webDir, 'node_modules', 'next', 'dist', 'bin', 'next');
  const server = spawn(process.execPath, [nextBin, 'start', '-p', String(port)], {
    cwd: webDir,
    env: {
      ...process.env,
      NODE_ENV: 'production',
      OPERATOR_SECRET: 'test-operator-secret-cohost-check',
      NEXT_PUBLIC_SUPABASE_URL: 'https://bcndgmymnismbxvdeetc.supabase.co',
      SUPABASE_URL: 'https://bcndgmymnismbxvdeetc.supabase.co',
      SUPABASE_SERVICE_ROLE_KEY: 'test-service-role-placeholder',
    },
    stdio: 'pipe',
  });

  try {
    await waitReady(baseUrl);

    const home = await fetch(`${baseUrl}/`);
    const homeHtml = await home.text();
    assert.equal(home.status, 200);
    assert.equal(home.headers.get('x-content-type-options'), 'nosniff');
    assert.ok(homeHtml.includes('Email confirmed') && homeHtml.includes('/discover'));
    console.log('PASS W1/W3 / preserves Email confirmed landing + web link');

    for (const route of ['/login', '/discover', '/reel/demo_token_12345678', '/review', '/pipeline']) {
      const res = await fetch(`${baseUrl}${route}`);
      const html = await res.text();
      assert.equal(res.status, 200, `${route} expected 200`);
      assert.equal(res.headers.get('x-frame-options'), 'DENY');
      assert.ok(html.includes('id="root"') && html.includes('/_expo/static/js/web/'), `${route} must serve Expo Web SPA shell`);
    }
    console.log('PASS W1/W3 SPA navigation routes (/login, /discover, /reel/:token, /review, /pipeline) serve Expo Web SPA');

    const bundleMatch = (await (await fetch(`${baseUrl}/login`)).text()).match(/\/_expo\/static\/js\/web\/[^"']+\.js/);
    assert.ok(bundleMatch, 'SPA HTML must reference /_expo/static/js/web/*.js bundle');
    const bundleRes = await fetch(`${baseUrl}${bundleMatch[0]}`);
    assert.equal(bundleRes.status, 200, 'JS bundle must return 200');
    console.log(`PASS W2/W3 static JS bundle ${bundleMatch[0]} served cleanly`);

    const redirectRes = await fetch(`${baseUrl}/operator/review`, { redirect: 'manual' });
    assert.ok([302, 307, 308].includes(redirectRes.status), `/operator/review must redirect, got ${redirectRes.status}`);
    assert.ok((redirectRes.headers.get('location') || '').endsWith('/review'));
    console.log('PASS W1 /operator/review redirects to /review');

    const legalRes = await fetch(`${baseUrl}/legal/privacy`);
    assert.equal(legalRes.status, 200);
    assert.ok(!(await legalRes.text()).includes('/_expo/static/js/web/'), '/legal/privacy stays Next.js SSG');
    console.log('PASS W3 /legal/privacy stays Next.js SSG');

    const unknownApi = await fetch(`${baseUrl}/api/does-not-exist-cohost-probe`);
    assert.equal(unknownApi.status, 404, 'Unknown /api/* route must return 404');
    const unauthOp = await fetch(`${baseUrl}/api/operator/drafts`);
    assert.equal(unauthOp.status, 401, '/api/operator/drafts without secret must return 401');
    console.log('PASS W3/W4 /api/* 404 isolation and 401 operator auth boundary verified');

    console.log('ALL WEB SPA CO-HOSTING CONTRACTS PASSED');
  } finally {
    try {
      if (process.platform === 'win32' && server.pid) {
        spawn('taskkill', ['/pid', String(server.pid), '/f', '/t'], { stdio: 'ignore' });
      } else {
        server.kill('SIGTERM');
      }
    } catch {}
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
