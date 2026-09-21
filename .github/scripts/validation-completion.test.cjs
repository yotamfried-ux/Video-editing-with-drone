const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {validate, relay} = require('./validation-completion.cjs');
const config = require('../validation-completion.json');
const now = Date.parse('2026-09-21T11:00:00Z');
const sha = 'a'.repeat(40);
const run = () => ({id: 123, run_attempt: 1, workflow_id: 456,
  repository: {full_name: config.repository}, head_repository: {full_name: config.repository},
  name: 'UPL-01 Android App Upload E2E', path: config.workflows['UPL-01 Android App Upload E2E'],
  head_branch: 'validation/upl01-android-e2e', head_sha: sha, event: 'push',
  status: 'completed', conclusion: 'success', updated_at: new Date(now).toISOString(),
  html_url: `https://github.com/${config.repository}/actions/runs/123`});

test('success and failure retain exact provenance, never acceptance PASS', () => {
  for (const conclusion of ['success', 'failure', 'cancelled', 'timed_out']) {
    const r = {...run(), conclusion};
    const e = validate(r, r, sha, now);
    assert.equal(e.conclusion, conclusion);
    assert.equal(e.acceptance_status, 'UNVERIFIED');
    assert.equal(e.event_key, `${config.repository}:123:1`);
    for (const key of ['repository', 'workflow', 'run_id', 'run_attempt', 'branch', 'ref', 'head_sha', 'conclusion', 'run_url']) assert.ok(e[key]);
  }
});

for (const [name, mutate] of [
  ['fork', r => r.head_repository.full_name = 'attacker/fork'],
  ['observer recursion', r => r.name = 'Validation Completion Relay'],
  ['workflow spoof', r => r.path = '.github/workflows/evil.yml'],
  ['untrusted PR code', r => r.event = 'pull_request'],
  ['wrong branch', r => r.head_branch = 'feature/other'],
  ['unfinished run', r => r.status = 'in_progress'],
  ['unknown conclusion', r => r.conclusion = null],
  ['expired event', r => r.updated_at = '2026-09-19T00:00:00Z'],
  ['malicious URL', r => r.html_url = 'https://example.org/123'],
  ['wrong SHA', r => r.head_sha = 'b'.repeat(40)]
]) test('reject ' + name, () => { const r = run(); mutate(r); assert.throws(() => validate(r, r, sha, now)); });

test('a newer attempt invalidates an old event', () => {
  const r = {...run(), run_attempt: 2};
  assert.throws(() => validate(r, run(), sha, now), /run_attempt/);
});

function fixture(comments = []) {
  const r = {...run(), updated_at: new Date().toISOString()};
  let writes = 0;
  const args = {context: {eventName:'workflow_run', payload:{action:'completed', workflow_run:r},
    repo:{owner:'yotamfried-ux',repo:'Video-editing-with-drone'}}, core:{info(){}},
    github:{paginate: async () => comments, rest:{
      actions:{getWorkflowRun:async()=>({data:r}), listWorkflowRuns:async()=>({data:{workflow_runs:[r]}})},
      git:{getRef:async()=>({data:{object:{sha}}})},
      pulls:{get:async()=>({data:{state:'open',base:{repo:{full_name:config.repository}}}})},
      issues:{listComments(){}, createComment:async p=>{writes++; const c={user:{login:'github-actions[bot]'},body:p.body}; comments.push(c); return {data:{html_url:'https://github.com/comment'}};}}
    }}};
  return {args, writes:()=>writes};
}

test('redelivery emits once; durable bot-authored comment deduplicates', async () => {
  const f = fixture();
  assert.equal((await relay(f.args)).status, 'delivered');
  assert.equal((await relay(f.args)).status, 'duplicate');
  assert.equal(f.writes(), 1);
});
test('user comment cannot suppress a real completion', async () => {
  const f = fixture([{user:{login:'attacker'},body:`<!-- sportreel-completion:${config.repository}:123:1 -->`}]);
  assert.equal((await relay(f.args)).status, 'delivered');
});
test('superseded run cannot emit even at the same head SHA', async () => {
  const f = fixture();
  f.args.github.rest.actions.listWorkflowRuns = async()=>({data:{workflow_runs:[{id:124}]}});
  await assert.rejects(relay(f.args), /Superseded/);
  assert.equal(f.writes(),0);
});
test('closed controller and API failures fail closed', async () => {
  const f = fixture();
  f.args.github.rest.pulls.get = async()=>({data:{state:'closed'}});
  await assert.rejects(relay(f.args), /Controller/);
  f.args.github.rest.actions.getWorkflowRun = async()=>{throw Error('API unavailable');};
  await assert.rejects(relay(f.args), /API unavailable/);
  assert.equal(f.writes(),0);
});
test('CI trigger allowlist matches config and excludes relay itself', () => {
  const source=fs.readFileSync('.github/workflows/validation-completion-events.yml','utf8');
  const names=source.split('    workflows:\n')[1].split('    types:')[0].trim().split('\n').map(x=>x.trim().slice(2));
  assert.deepEqual(names.sort(),Object.keys(config.workflows).sort());
  assert.ok(!names.includes('Validation Completion Relay'));
  assert.ok(source.includes('ref: ${{ github.sha }}'));
  assert.ok(!source.includes('ref: ${{ github.event.workflow_run.head_sha }}'));
});
