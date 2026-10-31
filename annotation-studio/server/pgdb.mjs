// PostgreSQL adapter exposing the same tiny synchronous surface the Studio uses from node:sqlite:
//   db.prepare(sql).get/all/run(...params), db.exec(sql), and transactions via exec('begin immediate'|'commit'|'rollback').
// SQLite -> PostgreSQL dialect shim: `?` -> `$n`, `insert or ignore` -> `on conflict do nothing`, `begin immediate` -> `begin`.
import { Worker, MessageChannel, receiveMessageOnPort } from 'node:worker_threads';
import { fileURLToPath } from 'node:url';

export function translate(sql) {
  let out = '', n = 0, inStr = false;
  for (let i = 0; i < sql.length; i++) {
    const c = sql[i];
    if (c === "'") { inStr = !inStr; out += c; } else if (c === '?' && !inStr) out += `$${++n}`; else out += c;
  }
  let ignore = false;
  out = out.replace(/\binsert\s+or\s+ignore\s+into\b/i, () => { ignore = true; return 'insert into'; });
  if (ignore) out = out.replace(/;?\s*$/, ' on conflict do nothing');
  if (/^\s*begin\s+immediate\s*;?\s*$/i.test(out)) out = 'begin';
  return out;
}

const dbError = e => Object.assign(new Error(e.message), { code: e.code, detail: e.detail });

export class PgDb {
  constructor(url, { ssl } = {}) {
    this.signal = new SharedArrayBuffer(4);
    this.flag = new Int32Array(this.signal);
    const { port1, port2 } = new MessageChannel();
    this.port = port1;
    this.worker = new Worker(fileURLToPath(new URL('./pg-worker.mjs', import.meta.url)), {
      workerData: { url, signal: this.signal, port: port2, ssl }, transferList: [port2],
    });
    this.worker.unref();
    const boot = this.#await(60000);
    if (!boot.ok) throw dbError(boot.error);
  }

  #await(timeout = 30000) {
    const r = Atomics.wait(this.flag, 0, 0, timeout);
    if (r === 'timed-out') throw new Error('PostgreSQL worker timed out');
    Atomics.store(this.flag, 0, 0);
    return receiveMessageOnPort(this.port).message;
  }

  #query(sql, params = []) {
    this.worker.postMessage({ sql: translate(sql), params: params.map(p => p === undefined ? null : p) });
    const msg = this.#await();
    if (!msg.ok) throw dbError(msg.error);
    return msg;
  }

  exec(sql) { for (const stmt of sql.split(/;\s*(?:\n|$)/).map(s => s.trim()).filter(Boolean)) this.#query(stmt); }
  /** Send a multi-statement script (e.g. migrations with $$ bodies) as one simple query inside a transaction. */
  script(sql) { this.#query(`begin;\n${sql}\n;commit`); }
  prepare(sql) {
    return {
      get: (...p) => this.#query(sql, p).rows[0],
      all: (...p) => this.#query(sql, p).rows,
      run: (...p) => { const r = this.#query(sql, p); return { changes: r.rowCount }; },
    };
  }
  close() {
    try { this.worker.postMessage({ close: true }); this.#await(10000); } catch { /* already gone */ }
    this.worker.terminate();
  }
}
