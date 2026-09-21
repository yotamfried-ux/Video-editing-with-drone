'use strict';

const config = require('../validation-completion.json');
const terminal = new Set(['success', 'failure', 'cancelled', 'timed_out', 'action_required', 'neutral', 'skipped', 'stale', 'startup_failure']);

function validate(run, eventRun, branchSha, now = Date.now()) {
  if (run.repository?.full_name !== config.repository || run.head_repository?.full_name !== config.repository) throw Error('Foreign repository');
  if (!config.workflows[run.name] || config.workflows[run.name] !== run.path) throw Error('Workflow not allowed');
  if (!['push', 'workflow_dispatch'].includes(run.event)) throw Error('Untrusted triggering event');
  if (!(run.head_branch?.startsWith('validation/') || run.head_branch === 'main')) throw Error('Branch not allowed');
  if (!Number.isSafeInteger(run.id) || run.id <= 0 || !Number.isSafeInteger(run.run_attempt) || run.run_attempt < 1) throw Error('Invalid run identity');
  if (run.status !== 'completed' || !terminal.has(run.conclusion)) throw Error('Run not terminal');
  if (!/^[a-f0-9]{40}$/.test(run.head_sha) || run.head_sha !== branchSha) throw Error('Stale branch head');
  for (const field of ['id', 'run_attempt', 'head_sha', 'head_branch', 'workflow_id']) {
    if (run[field] !== eventRun[field]) throw Error('Stale or mismatched event: ' + field);
  }
  const age = now - Date.parse(run.updated_at);
  if (!Number.isFinite(age) || age < -300000 || age > config.max_event_age_hours * 3600000) throw Error('Stale event timestamp');
  const expectedUrl = `https://github.com/${config.repository}/actions/runs/${run.id}`;
  if (run.html_url !== expectedUrl) throw Error('Unexpected run URL');
  return {
    schema_version: 1,
    event_key: `${config.repository}:${run.id}:${run.run_attempt}`,
    repository: config.repository,
    workflow: run.name,
    workflow_id: run.workflow_id,
    workflow_path: run.path,
    run_id: run.id,
    run_attempt: run.run_attempt,
    branch: run.head_branch,
    ref: `refs/heads/${run.head_branch}`,
    head_sha: run.head_sha,
    conclusion: run.conclusion,
    run_url: expectedUrl,
    completed_at: run.updated_at,
    acceptance_status: 'UNVERIFIED'
  };
}

async function relay({github, context, core}) {
  if (context.eventName !== 'workflow_run' || context.payload.action !== 'completed') throw Error('Expected workflow_run.completed');
  if (`${context.repo.owner}/${context.repo.repo}` !== config.repository) throw Error('Wrong observer repository');
  const eventRun = context.payload.workflow_run;
  const {data: run} = await github.rest.actions.getWorkflowRun({...context.repo, run_id: eventRun.id});
  const {data: ref} = await github.rest.git.getRef({...context.repo, ref: 'heads/' + run.head_branch});
  const event = validate(run, eventRun, ref.object.sha);
  const {data: latest} = await github.rest.actions.listWorkflowRuns({...context.repo,
    workflow_id: run.workflow_id, branch: run.head_branch, per_page: 1});
  if (latest.workflow_runs?.[0]?.id !== run.id) throw Error('Superseded workflow run');
  const {data: controller} = await github.rest.pulls.get({...context.repo, pull_number: config.controller_pr});
  if (controller.state !== 'open' || controller.base.repo.full_name !== config.repository) throw Error('Controller PR unavailable');
  const marker = `<!-- sportreel-completion:${event.event_key} -->`;
  const comments = await github.paginate(github.rest.issues.listComments, {...context.repo, issue_number: config.controller_pr, per_page: 100});
  if (comments.some(c => c.user?.login === 'github-actions[bot]' && c.body?.includes(marker))) {
    core.info('Completion already delivered: ' + event.event_key);
    return {status: 'duplicate', event};
  }
  const {data: comment} = await github.rest.issues.createComment({...context.repo,
    issue_number: config.controller_pr,
    body: 'SPORTREEL_VALIDATION_COMPLETED\n' + marker + '\n\n```json\n' + JSON.stringify(event, null, 2) + '\n```'
  });
  core.info('Completion delivered: ' + comment.html_url);
  return {status: 'delivered', event, comment_url: comment.html_url};
}

module.exports = {validate, relay};
