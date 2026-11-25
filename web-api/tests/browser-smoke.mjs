// Real browser smoke simulation for web-api using headless Chromium and Playwright.
// Asserts actual DOM content rendered by Next.js in a headless browser instance.
//
// In Claude Code cloud containers: uses preinstalled Chromium at /opt/pw-browsers/chromium.
// In CI / local environments: uses preinstalled Chrome/Chromium or default Playwright browser.
//
// Run: node web-api/tests/browser-smoke.mjs

import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { existsSync } from 'node:fs';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const WEB_DIR = resolve(__dirname, '..');

// 1. Verify playwright is available in the environment
let playwright;
try {
  playwright = await import('playwright');
} catch {
  console.error('[browser-smoke] FAIL: playwright is not installed in the environment.');
  console.error('Note: Claude Code cloud containers include preinstalled Playwright and Chromium at /opt/pw-browsers/chromium.');
  process.exit(1);
}

// 2. Discover available Chromium executable
function resolveChromiumPath() {
  if (process.env.CHROMIUM_PATH && existsSync(process.env.CHROMIUM_PATH)) {
    return process.env.CHROMIUM_PATH;
  }
  const candidates = [
    '/opt/pw-browsers/chromium', // Claude Code cloud container
    '/usr/bin/google-chrome',    // Linux / GitHub Actions runner
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', // Windows
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return undefined; // Fall back to Playwright's bundled search
}

// 3. Allocate free port
function getFreePort() {
  return new Promise((res, rej) => {
    const srv = createServer();
    srv.listen(0, '127.0.0.1', () => {
      const port = srv.address().port;
      srv.close(() => res(port));
    });
    srv.on('error', rej);
  });
}

// 4. Poll URL until ready
async function waitForServer(url, maxAttempts = 60) {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const res = await fetch(url);
      if (res.ok || res.status === 404 || res.status === 200) {
        return;
      }
    } catch {
      // Server not ready yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Server at ${url} failed to respond within timeout.`);
}

async function main() {
  console.log('='.repeat(65));
  console.log('Web-API Real Browser Smoke Test (Headless Chromium)');
  console.log('='.repeat(65));

  const port = await getFreePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  console.log(`[browser-smoke] Target local port: ${port}`);

  const nextBin = resolve(WEB_DIR, 'node_modules/next/dist/bin/next');
  const hasBuild = existsSync(join(WEB_DIR, '.next'));
  const serverArgs = hasBuild ? [nextBin, 'start', '-p', String(port)] : [nextBin, 'dev', '-p', String(port)];
  console.log(`[browser-smoke] Starting server with: node ${serverArgs.join(' ')}`);

  const server = spawn(process.execPath, serverArgs, {
    cwd: WEB_DIR,
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1', PORT: String(port) },
    stdio: 'pipe',
  });

  server.on('error', (err) => {
    console.error(`[browser-smoke] Failed to start server process: ${err.message}`);
    process.exit(1);
  });

  let browser;
  try {
    console.log('[browser-smoke] Waiting for web-api server to be ready...');
    await waitForServer(`${baseUrl}/`);
    console.log('[browser-smoke] Server ready.');

    const executablePath = resolveChromiumPath();
    console.log(`[browser-smoke] Chromium executable: ${executablePath || 'Playwright default'}`);

    browser = await playwright.chromium.launch({
      headless: true,
      executablePath,
      args: ['--no-sandbox', '--disable-setuid-sandbox'],
    });

    const context = await browser.newContext();
    const page = await context.newPage();

    // Route 1: Home page (email confirmation landing)
    console.log('[browser-smoke] Navigating to / (home page)...');
    await page.goto(`${baseUrl}/`);
    await page.waitForSelector('h1');
    const homeH1 = await page.locator('h1').textContent();
    const homeH2 = await page.locator('h2').textContent();
    const homeBody = await page.textContent('body');
    assert.equal(homeH1?.trim(), 'SportReel', 'Home page h1 must match brand name');
    assert.equal(homeH2?.trim(), 'Email confirmed', 'Home page h2 must display confirmation');
    assert.ok(homeBody.includes('Your email address has been verified successfully.'), 'Home page confirms verification message');
    console.log('  [PASS] /: Rendered SportReel brand, Email confirmed header, and verification message.');

    // Route 2: Checkout cancel page
    console.log('[browser-smoke] Navigating to /checkout/cancel ...');
    await page.goto(`${baseUrl}/checkout/cancel`);
    await page.waitForSelector('h1');
    const cancelH1 = await page.locator('h1').textContent();
    const cancelBody = await page.textContent('body');
    assert.equal(cancelH1?.trim(), 'Payment cancelled', 'Cancel page h1 must match cancellation heading');
    assert.ok(cancelBody.includes('No charge was made.'), 'Cancel page displays cancellation notice');
    console.log('  [PASS] /checkout/cancel: Rendered Payment cancelled header and guidance.');

    // Route 3: Checkout success page (client-side state machine without session)
    console.log('[browser-smoke] Navigating to /checkout/success (without session) ...');
    await page.goto(`${baseUrl}/checkout/success`);
    await page.waitForSelector('text=Missing checkout session.');
    const successBody = await page.textContent('body');
    assert.ok(successBody.includes('Missing checkout session.'), 'Client component rendered error state');
    console.log('  [PASS] /checkout/success: Client component resolved Missing checkout session.');

    // Route 4: Co-hosted Expo Router Web SPA (/login & /discover & /operator/review redirect)
    console.log('[browser-smoke] Navigating to /login (Expo Router Web SPA)...');
    const loginResp = await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' });
    assert.equal(loginResp?.status(), 200, '/login SPA fallback must return 200');
    assert.equal(loginResp?.headers()['x-content-type-options'], 'nosniff', 'Security header X-Content-Type-Options present');
    await page.waitForSelector('#root', { state: 'attached' });
    console.log('  [PASS] /login: Co-hosted SPA shell served with security headers.');

    console.log('[browser-smoke] Navigating to /discover (Expo Router Web SPA)...');
    const discoverResp = await page.goto(`${baseUrl}/discover`, { waitUntil: 'domcontentloaded' });
    assert.equal(discoverResp?.status(), 200, '/discover SPA fallback must return 200');
    await page.waitForSelector('#root', { state: 'attached' });
    console.log('  [PASS] /discover: Co-hosted SPA shell served.');

    console.log('[browser-smoke] Verifying /operator/review redirect -> /review and /api/* 404 isolation...');
    await page.goto(`${baseUrl}/operator/review`, { waitUntil: 'domcontentloaded' });
    assert.ok(page.url().endsWith('/review'), `/operator/review should redirect to /review, got ${page.url()}`);
    const unknownApi = await fetch(`${baseUrl}/api/nonexistent-smoke-probe`);
    assert.equal(unknownApi.status, 404, 'Unknown /api/* path must return 404, never SPA HTML');
    console.log('  [PASS] /operator/review redirect and /api/* 404 boundary verified.');

    console.log('\n[PASS] All Next.js + co-hosted Expo Web SPA routes rendered and verified in headless Chromium.');
  } finally {
    if (browser) {
      await browser.close().catch(() => {});
    }
    if (server && server.pid) {
      try {
        if (process.platform === 'win32') {
          spawn('taskkill', ['/pid', String(server.pid), '/f', '/t'], { stdio: 'ignore' });
        } else {
          server.kill('SIGTERM');
        }
      } catch {}
    }
  }
}

main().catch((err) => {
  console.error(`[browser-smoke] FAIL: ${err.message}`);
  process.exit(1);
});


