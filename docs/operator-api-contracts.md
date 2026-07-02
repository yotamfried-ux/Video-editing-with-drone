# Operator API response contracts

This document is the source-of-truth map for operator-facing API response shapes used by the mobile app.

The mobile TypeScript mirror lives at:

- `mobile/src/features/operator/types/contracts.ts`

The mobile app should import response and row types from that file instead of redefining local interfaces inside screens/components/hooks. The web-api route implementation should be checked against this document whenever a route response changes.

## Contract rule

Every privileged/operator flow must keep these invariants:

1. Mobile calls privileged data/actions through `operatorFetch(...)`.
2. Routes validate `requireOperator(req)` before service-role reads, Drive operations, dispatches, or operator-only summaries.
3. Route success responses use stable field names documented here.
4. Route error responses include `error: string`; partial success responses must include explicit booleans such as `delivery_started` or `drive_move_completed`.
5. Any route shape change must update this file and `mobile/src/features/operator/types/contracts.ts` in the same PR.

## Shared error response

```ts
type OperatorErrorResponse = {
  error: string;
};
```

## Pipeline dispatch

### `POST /api/operator/pipeline/start`

Creates a durable `pipeline_runs` row and dispatches `.github/workflows/pipeline-run.yml` through repository dispatch.

Success:

```ts
type PipelineDispatchResponse = {
  ok: true;
  pipeline_run_id: string;
  github_actions_url?: string;
};
```

Dispatch failure:

```ts
type OperatorErrorResponse & {
  pipeline_run_id: string;
};
```

### `POST /api/operator/pipeline/reset`

Creates a durable reset run and dispatches `.github/workflows/pipeline-run.yml` through workflow dispatch.

Success:

```ts
type PipelineResetResponse = PipelineDispatchResponse & {
  full_clean: boolean;
};
```

Dispatch failure follows the same error shape as `/pipeline/start` with `pipeline_run_id`.

### `GET /api/operator/pipeline/status`

Reads the singleton live progress row.

```ts
type PipelineStatus = {
  stage: string;
  progress: number;
  meta: Record<string, unknown>;
  updated_at: string;
};

type PipelineStatusResponse = {
  status: PipelineStatus | null;
};
```

This is a global live signal, not proof that a specific app-triggered action is running.

### `GET /api/operator/pipeline/runs?limit=...`

Reads durable run history.

```ts
type PipelineRun = {
  id: string;
  source: 'manual' | 'upload' | 'reset' | 'reprocess' | 'drive_watcher' | string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'no_input' | 'dispatch_failed' | string;
  stage: string | null;
  progress: number | null;
  github_run_url: string | null;
  input_files?: unknown;
  output_drafts?: unknown;
  error: string | null;
  meta?: Record<string, unknown> | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
};

type PipelineRunsResponse = {
  runs: PipelineRun[];
};
```

## Upload

### `POST /api/operator/upload`

Creates a resumable Drive upload session. Mobile uploads bytes directly to the returned URL and then calls `/api/operator/pipeline/start`.

```ts
type OperatorUploadInitResponse = {
  uploadUrl: string;
  filename: string;
};
```

## Reprocess

### `GET /api/operator/reprocess`

```ts
type ReprocessRow = {
  id: string;
  draft_name: string | null;
  notes: string;
  status: string;
  created_at: string;
  processed_at?: string | null;
};

type ReprocessListResponse = {
  requests: ReprocessRow[];
};
```

### `POST /api/operator/reprocess`

Creates a reprocess request and immediately dispatches a tracked pipeline run.

Success:

```ts
type ReprocessSubmitResponse = {
  ok: true;
  request_id: string;
  pipeline_run_id: string;
  github_actions_url?: string;
};
```

Failure after creating a request may include:

```ts
{
  error: string;
  request_id?: string;
  pipeline_run_id?: string;
}
```

Mobile must display the returned `pipeline_run_id` when present. It must not tell the operator that reprocess waits for the next unrelated pipeline run.

## Draft review and delivery

### `GET /api/operator/drafts`

```ts
type DraftRow = {
  id: string;
  name: string;
  created_at: string;
  size: number | null;
  watch_url: string | null;
};

type DraftsResponse = {
  drafts: DraftRow[];
};
```

### `POST /api/operator/drafts/approve`

Moves the draft from REVIEW to APPROVED, creates a delivery run, and tries to dispatch `.github/workflows/deliver.yml`.

Success:

```ts
type ApproveDraftResponse = {
  ok?: true;
  drive_move_completed?: boolean;
  delivery_started: boolean;
  delivery_run_id: string;
  github_actions_url?: string;
};
```

Partial success/failure must keep the same explicit fields when applicable:

- `drive_move_completed: true` means Drive already moved the file.
- `delivery_started: false` means the delivery workflow did not start.
- `delivery_run_id` lets the operator find the durable status row.

### `GET /api/operator/delivery-status?limit=...`

```ts
type DeliveryRun = {
  id: string;
  approved_file_id?: string | null;
  approved_file_name: string | null;
  source_video: string | null;
  status: 'queued' | 'running' | 'discover_published' | 'succeeded' | 'failed' | 'dispatch_failed' | string;
  stage: string;
  github_run_url?: string | null;
  discover_reel_id: string | null;
  error: string | null;
  meta?: Record<string, unknown> | null;
  approved_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at: string | null;
};

type DeliveryStatusResponse = {
  runs: DeliveryRun[];
};
```

## Reels and Discover

### `GET /api/operator/reels`

```ts
type OperatorReelRow = {
  id: string;
  token: string;
  sport: string | null;
  athlete_desc: string | null;
  status: string;
  expires_at: string;
  recording_date: string | null;
};

type OperatorReelsResponse = {
  reels: OperatorReelRow[];
};
```

### `GET /api/operator/discover-diagnostics`

```ts
type DiscoverDiagnosticReel = {
  id: string;
  token: string | null;
  sport: string | null;
  recording_date: string | null;
  stream_uid: string | null;
  status: string | null;
  expires_at: string | null;
  created_at: string | null;
  source_video?: string | null;
  storage_path?: string | null;
};

type DiscoverDiagnosticsResponse = {
  ok: true;
  eligibleStatuses: string[];
  activeStatuses: string[];
  reelCount: number;
  activeReelCount: number;
  missingExpiryCount: number;
  expiredActiveCount: number;
  sessions: { recording_date: string | null; sport: string; reels: DiscoverDiagnosticReel[] }[];
  reels: DiscoverDiagnosticReel[];
};
```

## Support and analytics

### `GET /api/operator/support`

```ts
type OperatorSupportResponse = {
  tickets: {
    id: string;
    message: string;
    status: string;
    operator_reply: string | null;
    created_at: string;
  }[];
  suggestions: {
    id: string;
    message: string;
    created_at: string;
  }[];
};
```

### `PATCH /api/support/[id]`

This route is not under `/api/operator`, but it is operator-only and still uses `requireOperator(req)`.

```ts
type SupportReplyResponse = {
  ok: true;
};
```

### `GET /api/analytics`

This route is operator-only and returns a server-computed summary.

```ts
type OperatorAnalyticsSummary = {
  todayRevenue: number;
  weekRevenue: number;
  monthRevenue: number;
  totalReels: number;
  soldReels: number;
  expiredReels: number;
  funnelViewed: number;
  funnelCheckout: number;
  funnelPaid: number;
};
```

## Review checklist for future PRs

Before merging any operator API or mobile operator change:

1. Search for `operatorFetch<` and confirm each call imports a named contract type from `mobile/src/features/operator/types/contracts.ts`.
2. Check the matching web-api route response shape against this document.
3. For partial success routes, verify the mobile UI uses explicit fields instead of optimistic copy.
4. Run Mobile Check when `mobile/**` changes.
5. Check Vercel preview before merge and the main deployment status after merge.
