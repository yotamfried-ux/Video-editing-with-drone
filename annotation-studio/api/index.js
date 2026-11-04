// Vercel entry: the same Studio request handler as the local server, in hosted mode (see server/context.mjs `serverless`).
// One instance keeps its context (and its PostgreSQL connection) between requests; a cold start builds it once.
import { createContext } from '../server/context.mjs';
import { createApp } from '../server/app.mjs';
import { dbTlsMode } from '../server/db.mjs';

let handler = null, booting = null, bootError = null;

async function boot() {
  if (!process.env.STUDIO_TOKEN) throw Object.assign(new Error('STUDIO_TOKEN is not configured'), { code: 'CONFIG' });
  // STUDIO_DB_URL may list several candidates separated by "|" (e.g. pooler hosts); the first that connects is used.
  const urls = (process.env.STUDIO_DB_URL ?? '').split('|').map(s => s.trim()).filter(Boolean);
  if (!urls.length) throw Object.assign(new Error('STUDIO_DB_URL is not configured'), { code: 'CONFIG' });
  const errors = [];
  for (const dbUrl of urls) {
    try {
      const ctx = createContext('/tmp/sportreel-studio', { dbUrl });
      ctx.dbHost = new URL(dbUrl).host;
      handler = createApp(ctx).listeners('request')[0];
      return;
    } catch (e) { errors.push(`${new URL(dbUrl).host}: ${e.code ?? ''} ${String(e.message).slice(0, 160)}`); }
  }
  throw Object.assign(new Error(errors.join(' ; ')), { code: 'DB_UNAVAILABLE' });
}

export default async function studio(req, res) {
  if (!handler) {
    try { booting ??= boot(); await booting; bootError = null; }
    catch (e) { booting = null; bootError = e; }
  }
  if (!handler) {
    // Health information only (no secrets): which part of the configuration is missing or failing.
    res.writeHead(503, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
    return res.end(JSON.stringify({ code: bootError?.code ?? 'UNAVAILABLE', message: 'הסטודיו לא הצליח להתחבר למסד הנתונים', detail: String(bootError?.message ?? '').replace(/:\/\/[^@]*@/g, '://***@'), db_tls: dbTlsMode() }));
  }
  return handler(req, res);
}
