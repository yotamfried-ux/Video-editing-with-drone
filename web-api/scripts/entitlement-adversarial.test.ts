/**
 * Adversarial entitlement tests: Discover -> preview -> checkout -> payment -> entitlement -> full reel.
 *
 * The real route handlers run against an in-process fake of the three services they talk to (Supabase REST,
 * Supabase Storage signing, Supabase Auth) and a fake Stripe API. Nothing is mocked inside the handlers: the
 * requests they make are real HTTP. Webhook signatures are real Stripe signatures.
 *
 * Run: NODE_ENV=test npx -y tsx --test scripts/entitlement-adversarial.test.ts   (from web-api/)
 */
import assert from 'node:assert/strict';
import http from 'node:http';
import { after, before, test } from 'node:test';
import type { AddressInfo } from 'node:net';
import Stripe from 'stripe';
import { NextRequest } from 'next/server';

type Row = Record<string, unknown>;
const db: Record<string, Row[]> = {};
const stripeSessions: Record<string, Row> = {};
const USERS: Record<string, string> = { 'jwt-buyer': 'user-buyer', 'jwt-other': 'user-other' };
const signed: string[] = [];
const t = (name: string): Row[] => (db[name] ??= []);

const REEL = '00000000-0000-4000-8000-0000000000a1';
const REEL_NO_FULL = '00000000-0000-4000-8000-0000000000a2';
const PURCHASE = '00000000-0000-4000-8000-0000000000b1';
const ATHLETE = '00000000-0000-4000-8000-0000000000c1';
const TOKEN = 'reeltoken-0001';
const TOKEN_NO_FULL = 'reeltoken-0002';
const WEBHOOK_SECRET = 'adversarial_test_signing_secret_not_used_in_production';

function reset() {
  for (const key of Object.keys(db)) delete db[key];
  for (const key of Object.keys(stripeSessions)) delete stripeSessions[key];
  signed.length = 0;
  const future = new Date(Date.now() + 86_400_000).toISOString();
  db.reels = [
    { id: REEL, token: TOKEN, status: 'published', expires_at: future, athlete_id: ATHLETE, sport: 'surfing',
      storage_path: '2026-11-14/a1_preview.mp4', full_storage_path: '2026-11-14/a1_full.mp4',
      preview_duration_sec: 10, full_duration_sec: 25 },
    { id: REEL_NO_FULL, token: TOKEN_NO_FULL, status: 'sold', expires_at: future, athlete_id: null,
      storage_path: '2026-11-14/a2_preview.mp4', full_storage_path: null },
  ];
  db.purchases = [
    { id: PURCHASE, reel_id: REEL, token: TOKEN, status: 'checkout_created', user_id: 'user-buyer',
      stripe_checkout_session_id: 'cs_test_1', stripe_payment_intent_id: null, amount_ils: 4900 },
  ];
  db.athletes = [{ id: ATHLETE, label: 'surfer' }];
  db.athlete_follows = [];
  db.analytics_events = [];
  stripeSessions.cs_test_1 = { id: 'cs_test_1', object: 'checkout.session', payment_status: 'unpaid',
    metadata: { purchase_id: PURCHASE, reel_id: REEL } };
}

function matches(row: Row, params: URLSearchParams): boolean {
  for (const [key, raw] of params) {
    if (['select', 'limit', 'order', 'on_conflict', 'columns'].includes(key)) continue;
    const value = row[key];
    if (raw.startsWith('eq.')) { if (String(value) !== raw.slice(3)) return false; }
    else if (raw.startsWith('in.(')) { if (!raw.slice(4, -1).split(',').map((v) => v.replace(/"/g, '')).includes(String(value))) return false; }
    else if (raw === 'not.is.null') { if (value === null || value === undefined) return false; }
    else throw new Error(`fake PostgREST: unsupported filter ${key}=${raw}`);
  }
  return true;
}

function project(row: Row, select: string | null): Row {
  if (!select || select === '*') return row;
  return Object.fromEntries(select.split(',').map((c) => c.trim()).filter(Boolean).map((c) => [c, row[c] ?? null]));
}

async function body(req: http.IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString('utf8');
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', 'http://fake');
  const send = (status: number, payload: unknown) => {
    res.writeHead(status, { 'content-type': 'application/json' });
    res.end(payload === undefined ? '' : JSON.stringify(payload));
  };
  try {
    if (url.pathname.startsWith('/v1/checkout/sessions/')) {
      const session = stripeSessions[url.pathname.split('/').pop()!];
      return session ? send(200, session) : send(404, { error: { type: 'invalid_request_error', message: 'No such session' } });
    }
    if (url.pathname === '/auth/v1/user') {
      const userId = USERS[(req.headers.authorization ?? '').replace(/^Bearer /i, '')];
      return userId ? send(200, { id: userId, aud: 'authenticated', email: `${userId}@example.com` })
        : send(401, { code: 401, msg: 'invalid JWT' });
    }
    if (url.pathname.startsWith('/storage/v1/object/sign/')) {
      const path = decodeURIComponent(url.pathname.replace('/storage/v1/object/sign/reels/', ''));
      signed.push(path);
      return send(200, { signedURL: `/object/sign/reels/${path}?token=signed-${signed.length}` });
    }
    if (url.pathname.startsWith('/rest/v1/rpc/')) return send(200, [{ allowed: true }]);
    if (url.pathname.startsWith('/rest/v1/')) {
      const table = url.pathname.replace('/rest/v1/', '');
      const rows = (db[table] ??= []);
      const select = url.searchParams.get('select');
      const wantsObject = String(req.headers.accept ?? '').includes('vnd.pgrst.object');
      const representation = String(req.headers.prefer ?? '').includes('return=representation');
      const reply = (hit: Row[]) => {
        const out = hit.map((r) => project(r, select));
        if (!wantsObject) return send(200, out);
        if (out.length === 1) return send(200, out[0]);
        return send(406, { code: 'PGRST116', message: 'JSON object requested, multiple (or no) rows returned', details: `${out.length} rows` });
      };
      if (req.method === 'GET') {
        const limit = Number(url.searchParams.get('limit') ?? Infinity);
        return reply(rows.filter((r) => matches(r, url.searchParams)).slice(0, limit));
      }
      const payload = JSON.parse((await body(req)) || 'null');
      if (req.method === 'POST') {
        const incoming: Row[] = Array.isArray(payload) ? payload : [payload];
        const conflict = url.searchParams.get('on_conflict');
        const added: Row[] = [];
        for (const row of incoming) {
          if (conflict && rows.some((r) => conflict.split(',').every((c) => r[c] === row[c]))) continue;
          const stored = { id: `gen-${table}-${rows.length + 1}`, ...row };
          rows.push(stored);
          added.push(stored);
        }
        return representation ? reply(added) : send(201, undefined);
      }
      if (req.method === 'PATCH') {
        const hit = rows.filter((r) => matches(r, url.searchParams));
        for (const row of hit) Object.assign(row, payload);
        return representation ? reply(hit) : send(204, undefined);
      }
      if (req.method === 'DELETE') {
        db[table] = rows.filter((r) => !matches(r, url.searchParams));
        return send(204, undefined);
      }
    }
    send(404, { message: `fake: no handler for ${req.method} ${url.pathname}` });
  } catch (err) {
    send(500, { message: String(err) });
  }
});

let stream: typeof import('../src/app/api/stream/[token]/route');
let ownership: typeof import('../src/app/api/reels/[token]/ownership/route');
let follow: typeof import('../src/app/api/reels/[token]/follow/route');
let session: typeof import('../src/app/api/checkout/session/route');
let webhook: typeof import('../src/app/api/payments/webhook/route');

before(async () => {
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as AddressInfo).port;
  Object.assign(process.env, {
    SUPABASE_URL: `http://127.0.0.1:${port}`,
    SUPABASE_SERVICE_KEY: 'fake-service-key',
    STRIPE_SECRET_KEY: 'sk_' + 'test_placeholder',
    STRIPE_WEBHOOK_SECRET: WEBHOOK_SECRET,
    STRIPE_TEST_API_HOST: '127.0.0.1',
    STRIPE_TEST_API_PORT: String(port),
  });
  delete process.env.PAYMENT_PROVIDER;
  stream = await import('../src/app/api/stream/[token]/route');
  ownership = await import('../src/app/api/reels/[token]/ownership/route');
  follow = await import('../src/app/api/reels/[token]/follow/route');
  session = await import('../src/app/api/checkout/session/route');
  webhook = await import('../src/app/api/payments/webhook/route');
});
after(() => new Promise<void>((resolve) => server.close(() => resolve())));

const params = (token: string) => ({ params: Promise.resolve({ token }) });
const get = (path: string, jwt?: string) =>
  new NextRequest(`http://app.test${path}`, { headers: jwt ? { authorization: `Bearer ${jwt}` } : {} });
const post = (path: string, jwt?: string) =>
  new NextRequest(`http://app.test${path}`, { method: 'POST', headers: jwt ? { authorization: `Bearer ${jwt}` } : {} });

function stripeEvent(event: object, secret = WEBHOOK_SECRET) {
  const payload = JSON.stringify(event);
  const header = new Stripe('sk_' + 'test_placeholder').webhooks.generateTestHeaderString({ payload, secret });
  return new NextRequest('http://app.test/api/payments/webhook', {
    method: 'POST', body: payload, headers: { 'stripe-signature': header },
  });
}
const paidEvent = (sessionId = 'cs_test_1', purchaseId = PURCHASE) => ({
  id: 'evt_1', object: 'event', type: 'checkout.session.completed',
  data: { object: { id: sessionId, object: 'checkout.session', payment_status: 'paid', payment_intent: 'pi_1',
    metadata: { purchase_id: purchaseId, reel_id: REEL } } },
});
const refundEvent = (full = true) => ({
  id: 'evt_2', object: 'event', type: 'charge.refunded',
  data: { object: { id: 'ch_1', object: 'charge', payment_intent: 'pi_1', refunded: full } },
});
const purchase = () => t('purchases').find((p) => p.id === PURCHASE)!;
const reel = () => t('reels').find((r) => r.id === REEL)!;
const fullWasSigned = () => signed.some((p) => p.includes('_full'));

async function pay() {
  stripeSessions.cs_test_1.payment_status = 'paid';
  const res = await webhook.POST(stripeEvent(paidEvent()));
  assert.equal(res.status, 200);
}

test('anonymous Discover gets the preview only, before and after the reel is sold', async () => {
  reset();
  for (const status of ['published', 'sold']) {
    reel().status = status;
    const res = await stream.GET(get(`/api/stream/${TOKEN}`), params(TOKEN));
    const json = await res.json();
    assert.equal(res.status, 200);
    assert.match(json.streamUrl, /a1_preview\.mp4/);
    assert.equal(json.isPreview, true);
    assert.deepEqual([json.previewSeconds, json.fullSeconds], [10, 25]);
    assert.ok(!JSON.stringify(json).includes('_full'), 'the stream response never names the full reel');
  }
  assert.equal(fullWasSigned(), false, 'the stream route never signs the full reel');
});

test('ownership: no token, an invalid token and a stranger get nothing', async () => {
  reset();
  await pay();
  assert.equal((await ownership.GET(get(`/api/reels/${TOKEN}/ownership`), params(TOKEN))).status, 401);
  assert.equal((await ownership.GET(get(`/api/reels/${TOKEN}/ownership`, 'jwt-forged'), params(TOKEN))).status, 401);
  signed.length = 0;
  const stranger = await (await ownership.GET(get(`/api/reels/${TOKEN}/ownership`, 'jwt-other'), params(TOKEN))).json();
  assert.deepEqual(stranger, { purchased: false, download_url: null, can_follow: false, following: false });
  assert.equal(fullWasSigned(), false, 'a signed-in user who did not buy never gets the full reel signed');
});

test('ownership: an unpaid buyer gets nothing; the paid buyer gets the full reel, not the preview', async () => {
  reset();
  const unpaid = await (await ownership.GET(get(`/api/reels/${TOKEN}/ownership`, 'jwt-buyer'), params(TOKEN))).json();
  assert.equal(unpaid.purchased, false);
  assert.equal(unpaid.download_url, null);
  assert.equal(fullWasSigned(), false);
  await pay();
  const paid = await (await ownership.GET(get(`/api/reels/${TOKEN}/ownership`, 'jwt-buyer'), params(TOKEN))).json();
  assert.equal(paid.purchased, true);
  assert.match(paid.download_url, /a1_full\.mp4\?token=/);
  assert.ok(!paid.download_url.includes('_preview'));
});

test('checkout result: a paid provider session without our webhook grants nothing', async () => {
  reset();
  stripeSessions.cs_test_1.payment_status = 'paid'; // Stripe says paid; our webhook has not recorded it
  const res = await session.GET(get('/api/checkout/session?session_id=cs_test_1&provider=stripe'));
  const json = await res.json();
  assert.equal(json.paid, false);
  assert.equal(json.download_url, undefined);
  assert.equal(fullWasSigned(), false);
});

test('checkout result: unknown, foreign and non-Stripe session ids are not found', async () => {
  reset();
  for (const id of ['cs_test_unknown', 'abc', '../../etc', 'x'.repeat(300)]) {
    const res = await session.GET(get(`/api/checkout/session?session_id=${encodeURIComponent(id)}`));
    assert.equal(res.status, 404, id);
  }
  // A real Stripe session whose metadata points at a purchase that used another session id.
  stripeSessions.cs_test_evil = { id: 'cs_test_evil', object: 'checkout.session', payment_status: 'paid',
    metadata: { purchase_id: PURCHASE, reel_id: REEL } };
  await pay();
  const res = await session.GET(get('/api/checkout/session?session_id=cs_test_evil'));
  assert.equal(res.status, 404, 'another session cannot claim this purchase');
});

test('checkout result: after the verified webhook the download is the full reel with a 15 minute link', async () => {
  reset();
  await pay();
  const json = await (await session.GET(get('/api/checkout/session?session_id=cs_test_1&provider=stripe'))).json();
  assert.equal(json.delivery_ready, true);
  assert.match(json.download_url, /a1_full\.mp4\?token=/);
  assert.equal(json.expires_in, 900);
});

test('checkout result: a sold reel with no stored full file is "not ready", never the preview', async () => {
  reset();
  t('purchases').push({ id: 'p2', reel_id: REEL_NO_FULL, status: 'paid', stripe_checkout_session_id: 'cs_test_2' });
  stripeSessions.cs_test_2 = { id: 'cs_test_2', object: 'checkout.session', payment_status: 'paid',
    metadata: { purchase_id: 'p2', reel_id: REEL_NO_FULL } };
  const json = await (await session.GET(get('/api/checkout/session?session_id=cs_test_2'))).json();
  assert.equal(json.delivery_ready, false);
  assert.equal(json.download_url, undefined);
  assert.equal(signed.length, 0, 'nothing is signed, in particular not the preview');
});

test('webhook: unsigned, wrongly signed and mismatched events change nothing', async () => {
  reset();
  const unsigned = new NextRequest('http://app.test/api/payments/webhook', { method: 'POST', body: JSON.stringify(paidEvent()) });
  assert.equal((await webhook.POST(unsigned)).status, 400);
  assert.equal((await webhook.POST(stripeEvent(paidEvent(), 'attacker_secret'))).status, 400);
  // Correctly signed, but for a session id that is not the one stored on the purchase.
  assert.equal((await (await webhook.POST(stripeEvent(paidEvent('cs_test_other')))).json()).duplicate, true);
  assert.equal(purchase().status, 'checkout_created');
  assert.equal(reel().status, 'published');
  assert.equal(t('analytics_events').length, 0);
});

test('webhook: one fulfilment for one payment, however many times and however concurrently it arrives', async () => {
  reset();
  const results = await Promise.all(Array.from({ length: 12 }, () => webhook.POST(stripeEvent(paidEvent()))));
  const bodies = await Promise.all(results.map((r) => r.json()));
  assert.equal(bodies.filter((b) => !b.duplicate).length, 1);
  assert.equal(bodies.filter((b) => b.duplicate).length, 11);
  assert.equal(purchase().status, 'paid');
  assert.equal(reel().status, 'sold');
  assert.equal(t('analytics_events').length, 1, 'the purchase is recorded once');
});

test('refund: a full refund takes the reel back and puts it on sale again; a partial refund does not', async () => {
  reset();
  await pay();
  assert.equal((await (await webhook.POST(stripeEvent(refundEvent(false)))).json()).received, true);
  assert.equal(purchase().status, 'paid', 'a partial refund is a price adjustment');
  assert.equal((await webhook.POST(stripeEvent(refundEvent()))).status, 200);
  assert.equal(purchase().status, 'refunded');
  assert.equal(reel().status, 'published');
  signed.length = 0;
  const owned = await (await ownership.GET(get(`/api/reels/${TOKEN}/ownership`, 'jwt-buyer'), params(TOKEN))).json();
  assert.equal(owned.purchased, false);
  assert.equal(owned.download_url, null);
  const result = await (await session.GET(get('/api/checkout/session?session_id=cs_test_1'))).json();
  assert.equal(result.paid, false);
  assert.equal(fullWasSigned(), false, 'no download path signs the full reel after a refund');
  assert.equal((await (await webhook.POST(stripeEvent(refundEvent()))).json()).duplicate, true, 'a replayed refund is a no-op');
});

test('follow: only the buyer, only after paying, and only once', async () => {
  reset();
  assert.equal((await follow.POST(post(`/api/reels/${TOKEN}/follow`), params(TOKEN))).status, 401);
  assert.equal((await follow.POST(post(`/api/reels/${TOKEN}/follow`, 'jwt-buyer'), params(TOKEN))).status, 403, 'not paid yet');
  await pay();
  assert.equal((await follow.POST(post(`/api/reels/${TOKEN}/follow`, 'jwt-other'), params(TOKEN))).status, 403, 'not the buyer');
  assert.equal((await follow.POST(post(`/api/reels/${TOKEN}/follow`, 'jwt-buyer'), params(TOKEN))).status, 200);
  assert.equal((await follow.POST(post(`/api/reels/${TOKEN}/follow`, 'jwt-buyer'), params(TOKEN))).status, 200);
  assert.equal(t('athlete_follows').length, 1);
  assert.equal(t('athlete_follows')[0].user_id, 'user-buyer');
  const owned = await (await ownership.GET(get(`/api/reels/${TOKEN}/ownership`, 'jwt-buyer'), params(TOKEN))).json();
  assert.equal(owned.following, true);
});
