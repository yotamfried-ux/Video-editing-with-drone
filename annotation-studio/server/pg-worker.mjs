// Runs `pg` in a worker thread so the (synchronous) Studio server code can use PostgreSQL unchanged:
// the main thread posts a statement, blocks on Atomics.wait, and reads the reply with receiveMessageOnPort.
import { parentPort, workerData } from 'node:worker_threads';

const { default: pg } = await import('pg');
// int8 (count(*), bigint columns) -> Number; Studio byte sizes stay far below 2^53.
pg.types.setTypeParser(20, v => Number(v));
const { url, signal, port, ssl } = workerData;
const flag = new Int32Array(signal);
const client = new pg.Client({ connectionString: url, ssl: ssl || undefined });
client.on('error', () => {}); // a dropped connection surfaces on the next query, never as a crash
let ready;
try { await client.connect(); ready = { ok: true }; } catch (e) { ready = { ok: false, error: { message: e.message, code: e.code } }; }

function reply(msg) { port.postMessage(msg); Atomics.store(flag, 0, 1); Atomics.notify(flag, 0); }
reply({ boot: true, ...ready });

parentPort.on('message', async ({ sql, params, close }) => {
  if (close) { await client.end().catch(() => {}); reply({ ok: true, rows: [], rowCount: 0 }); return; }
  try {
    const r = await client.query(sql, params);
    reply({ ok: true, rows: r.rows ?? [], rowCount: r.rowCount ?? 0 });
  } catch (e) {
    reply({ ok: false, error: { message: e.message, code: e.code, detail: e.detail } });
  }
});
