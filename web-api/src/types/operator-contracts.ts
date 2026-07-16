/**
 * Typed response shapes for operator API routes (GAP-009).
 *
 * There is no shared package/workspace linking web-api and mobile, so this
 * file cannot be imported directly by mobile — it is the web-api-side source
 * of truth. `mobile/src/features/operator/types/contracts.ts` hand-maintains
 * the mobile-side equivalent independently; when a route's response shape
 * changes here, update that file too. Typing each route's `NextResponse.json`
 * calls against these types means web-api's own `tsc --noEmit` catches
 * response-shape drift within web-api itself, even though it cannot catch
 * drift against mobile's copy automatically.
 */

export type OperatorErrorResponse = {
  error: string;
  [key: string]: unknown;
};

// GET /api/operator/pipeline/status
export type PipelineStatusRow = {
  stage: string;
  progress: number;
  meta: Record<string, unknown> | null;
  updated_at: string | null;
};

export type PipelineRunRow = {
  id: string;
  source: string;
  status: string;
  stage: string | null;
  progress: number | null;
  github_run_url: string | null;
  input_files?: unknown;
  output_drafts?: unknown;
  error: string | null;
  meta: Record<string, unknown> | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
};

export type PipelineStatusResponse = {
  status: PipelineStatusRow | null;
  latest_run: PipelineRunRow | null;
  global_live_stale: boolean;
  global_live_stale_reason: string | null;
};

// GET /api/operator/pipeline/runs
export type PipelineRunsResponse = {
  runs: PipelineRunRow[];
};

// POST /api/operator/pipeline/start (and legacy alias /api/operator/pipeline/run)
export type PipelineDispatchResponse = {
  ok: true;
  pipeline_run_id: string;
  batch_id: string | null;
  github_actions_url: string;
};

// POST /api/operator/pipeline/reset
export type PipelineResetResponse = {
  ok: true;
  pipeline_run_id: string;
  batch_id: string | null;
  full_clean: boolean;
  github_actions_url: string;
};

// POST /api/operator/upload
export type UploadFileResult = {
  uploadUrl: string;
  filename: string;
  source_filename: string;
  mimeType: string;
  batch_id: string;
  storage_backend: 'r2' | 'drive';
  storage_key?: string;
};

export type UploadInitResponse = UploadFileResult & {
  uploads: UploadFileResult[];
};

// POST /api/operator/upload/verify
export type UploadVerifyResponse =
  | { ok: true; exists: true; storage_backend: 'drive' }
  | {
      ok: boolean;
      exists: boolean;
      storage_backend: 'r2';
      storage_key: string;
      size: number | null;
      r2_status: number;
    };

// Shared by GET /api/operator/drafts and the reprocess routes.
export type ReprocessRow = {
  id: string;
  draft_name: string | null;
  notes: string;
  status: string;
  origin?: string | null;
  qa_defects?: unknown;
  approval_blocked_reasons?: string[] | null;
  attempt_count?: number | null;
  max_attempts?: number | null;
  last_pipeline_run_id?: string | null;
  created_at: string;
  processed_at?: string | null;
};

// GET /api/operator/drafts
export type DraftRow = {
  id: string;
  name: string;
  created_at: string;
  size: number | null;
  watch_url: string | null;
  storage_backend: 'r2' | 'drive';
  storage_key?: string;
  review_required: boolean;
  approval_blocked: boolean;
  approval_blocked_reasons: string[];
  approval_policy_version: string;
  reedit_task: ReprocessRow | null;
};

export type DraftsResponse = {
  drafts: DraftRow[];
};

// POST /api/operator/drafts/approve
export type ApproveDraftResponse = {
  ok: true;
  storage_move_completed: true;
  delivery_started: true;
  delivery_run_id: string;
  github_actions_url: string;
  storage_backend: string;
};

// GET /api/operator/reprocess
export type ReprocessListResponse = {
  requests: ReprocessRow[];
};

// POST /api/operator/reprocess
export type ReprocessSubmitResponse = {
  ok: true;
  request_id: string;
  pipeline_run_id: string;
  github_actions_url: string;
};

// GET /api/operator/delivery-status
export type DeliveryRunRow = {
  id: string;
  approved_file_id: string | null;
  approved_file_name: string | null;
  source_video: string | null;
  status: string;
  stage: string;
  github_run_url: string | null;
  discover_reel_id: string | null;
  error: string | null;
  meta: Record<string, unknown> | null;
  approved_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
};

export type DeliveryStatusResponse = {
  runs: DeliveryRunRow[];
};

// GET /api/operator/discover-diagnostics
export type DiscoverDiagnosticReel = {
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

export type DiscoverDiagnosticSession = {
  recording_date: string | null;
  sport: string;
  reels: DiscoverDiagnosticReel[];
};

export type DiscoverDiagnosticsResponse = {
  ok: true;
  eligibleStatuses: string[];
  activeStatuses: string[];
  reelCount: number;
  activeReelCount: number;
  missingExpiryCount: number;
  expiredActiveCount: number;
  sessions: DiscoverDiagnosticSession[];
  reels: DiscoverDiagnosticReel[];
};

// GET /api/operator/reels
export type OperatorReelRow = {
  id: string;
  token: string | null;
  sport: string | null;
  athlete_desc: string | null;
  status: string;
  expires_at: string;
  recording_date: string | null;
};

export type OperatorReelsResponse = {
  reels: OperatorReelRow[];
};

// GET /api/operator/support
export type OperatorSupportTicket = {
  id: string;
  message: string;
  status: string;
  operator_reply: string | null;
  created_at: string;
};

export type OperatorSuggestion = {
  id: string;
  message: string;
  created_at: string;
};

export type OperatorSupportResponse = {
  tickets: OperatorSupportTicket[];
  suggestions: OperatorSuggestion[];
};
