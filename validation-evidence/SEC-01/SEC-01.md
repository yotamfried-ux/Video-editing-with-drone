# SEC-01 — Unauthorized access to the operator boundary

**Result: PASS**

| Field | Value |
| --- | --- |
| Executed | 2026-09-19T10:01:14Z–10:01:18Z |
| Workflow run | [35436251541](https://github.com/yotamfried-ux/Video-editing-with-drone/actions/runs/35436251541) |
| Job | 105879288503, attempt 1, conclusion success |
| Harness commit | `099aeaa180e557a632fa375283cdc752cb01f660` |
| Target | `https://video-editing-with-drone.vercel.app` |
| Target deployment | `dpl_BrGpP43YvLgvitTLBBpKqa9QxKYt`, target=production, state=READY |
| Deployed commit | `356d5812097ba935401ecf3a145a2608cda68cb9` (= `main` HEAD) |

## What was executed

Eleven real HTTP requests to the live production API with **no**
`x-operator-secret` header, plus one with a deliberately wrong secret.

```
SEC01 read-pipeline-status    GET  /api/operator/pipeline/status         expect=401 got=401 {"error":"Unauthorized"}
SEC01 read-pipeline-runs      GET  /api/operator/pipeline/runs           expect=401 got=401 {"error":"Unauthorized"}
SEC01 read-reels              GET  /api/operator/reels                   expect=401 got=401 {"error":"Unauthorized"}
SEC01 read-drafts             GET  /api/operator/drafts                  expect=401 got=401 {"error":"Unauthorized"}
SEC01 read-diagnostics        GET  /api/operator/discover-diagnostics    expect=401 got=401 {"error":"Unauthorized"}
SEC01 mutate-pipeline-start   POST /api/operator/pipeline/start          expect=401 got=401 {"error":"Unauthorized"}
SEC01 mutate-pipeline-reset   POST /api/operator/pipeline/reset          expect=401 got=401 {"error":"Unauthorized"}
SEC01 mutate-draft-approve    POST /api/operator/drafts/approve          expect=401 got=401 {"error":"Unauthorized"}
SEC01 mutate-reprocess        POST /api/operator/reprocess               expect=401 got=401 {"error":"Unauthorized"}
SEC01 mutate-mpu-start        POST /api/operator/upload/multipart/start  expect=401 got=401 {"error":"Unauthorized"}
SEC01 wrong-secret-rejected                                              expect=401 got=401
SEC01_PROBE_FAIL=0
```

## Proof that no mutation occurred

Durable `pipeline_runs` row count was read from Supabase immediately before and
immediately after the probe sequence:

```
SEC01_PIPELINE_RUNS_BEFORE=55
SEC01_PIPELINE_RUNS_AFTER=55
SEC01_NO_MUTATION=true
```

No pipeline run was created, so no `repository_dispatch` was emitted and no
GitHub Actions run was started by the unauthorized attempts.

## Safety design used to probe the dispatch endpoint

`/api/operator/pipeline/start` can dispatch a real pipeline. To probe it safely
the request carried `{"batch_id":"../bad id!"}`. In
`web-api/src/app/api/operator/pipeline/start/route.ts` the `safeBatchId()`
rejection returns 400 **immediately after** `requireOperator()` and **before**
batch resolution, the `pipeline_runs` insert, or the dispatch call. So the two
outcomes are distinguishable while neither can start a run:

- `401` → auth blocked the request (**observed**)
- `400` → auth did not block it; request reached input validation (would be a finding)

## Scope of this result

Proven: the `x-operator-secret` boundary rejects absent and incorrect
credentials on all ten routes tested, and rejection is durable-side-effect free.

**Not** proven by this experiment: authorization *between* authenticated
operators, token leakage, rate-limit behaviour under abuse, webhook signature
verification (`/api/webhooks/stripe`, `/api/webhooks/meshulam`), or
protected-media token scoping (`/api/download/[token]`, `/api/stream/[token]`).
Those remain untested.
