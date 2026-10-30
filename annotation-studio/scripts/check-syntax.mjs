// Dependency-free "lint": every .mjs/.js file must parse (module syntax).
import { readdirSync, statSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let bad = 0, n = 0;
(function walk(d) {
  for (const f of readdirSync(d)) {
    if (f === 'node_modules' || f.startsWith('.')) continue;
    const p = path.join(d, f);
    if (statSync(p).isDirectory()) walk(p);
    else if (/\.(mjs|js)$/.test(f)) { n++; const r = spawnSync(process.execPath, ['--check', p], { encoding: 'utf8' }); if (r.status) { bad++; console.error(r.stderr); } }
  }
})(root);
console.log(`${n} files checked, ${bad} with syntax errors`);
process.exit(bad ? 1 : 0);
