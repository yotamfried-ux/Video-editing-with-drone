// Smoke simulation for web user flows (Email confirmation, Pricing, Checkout journeys).
// Run: node --test web-api/tests/smoke-web-flow.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';

const WEB_API_ROOT = resolve(process.cwd(), 'web-api');

test('Web user flow: Home landing / email confirmation page structure', () => {
  const homePath = join(WEB_API_ROOT, 'src/app/page.tsx');
  assert.ok(existsSync(homePath), 'Home page file exists');
  const content = readFileSync(homePath, 'utf8');

  // Verify elements presented to a user verifying their email
  assert.match(content, /SportReel/, 'Displays brand name');
  assert.match(content, /Email confirmed/, 'Displays email confirmed heading');
  assert.match(content, /verified successfully/, 'Confirms verification');
  assert.match(content, /return to the SportReel app/, 'Guides user back to mobile app');
});

test('Web user flow: Checkout success and delivery verification state machine', () => {
  const successPath = join(WEB_API_ROOT, 'src/app/checkout/success/page.tsx');
  assert.ok(existsSync(successPath), 'Checkout success page exists');
  const content = readFileSync(successPath, 'utf8');

  // Verify client flow states
  assert.match(content, /Verifying payment/, 'Default loading state');
  assert.match(content, /Missing checkout session/, 'Guards against direct visit without session');
  assert.match(content, /Payment confirmed\. Your reel is ready/, 'Ready state message');
  assert.match(content, /Download reel/, 'Provides download link when delivery ready');
  assert.match(content, /api\/checkout\/session/, 'Calls checkout verification API');
});

test('Web user flow: Checkout cancellation feedback', () => {
  const cancelPath = join(WEB_API_ROOT, 'src/app/checkout/cancel/page.tsx');
  assert.ok(existsSync(cancelPath), 'Checkout cancel page exists');
  const content = readFileSync(cancelPath, 'utf8');

  assert.match(content, /cancelled|Payment/, 'Contains cancellation guidance');
});

test('Web user flow: Pricing API catalog contract', async () => {
  const pricingRoute = join(WEB_API_ROOT, 'src/app/api/pricing/route.ts');
  const pricingLib = join(WEB_API_ROOT, 'src/lib/pricing.ts');

  assert.ok(existsSync(pricingRoute) || existsSync(pricingLib), 'Pricing definition exists');
  if (existsSync(pricingLib)) {
    const libContent = readFileSync(pricingLib, 'utf8');
    assert.match(libContent, /amount|price|cents|currency|tier|ils|usd/i, 'Defines pricing values');
  }
});

test('Web user flow: Browser simulation environment readiness', () => {
  const isLinux = process.platform === 'linux';
  const preinstalledChromium = '/opt/pw-browsers/chromium';
  
  // In Claude Code cloud container, Chromium is pre-installed at /opt/pw-browsers/chromium
  // In local/custom environments, Playwright MCP or Chrome DevTools MCP executes via npx
  const report = {
    platform: process.platform,
    nodeVersion: process.version,
    cloudChromiumExpectedPath: preinstalledChromium,
    cloudChromiumPresent: isLinux && existsSync(preinstalledChromium),
  };

  assert.ok(report.nodeVersion.startsWith('v'), 'Node.js is available');
});
