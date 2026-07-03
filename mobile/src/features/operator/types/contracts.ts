export type OperatorErrorResponse = {
  error: string;
};

export type PipelineStatus = {
  stage: string;
  progress: number;
  meta: Record<string, unknown>;
  updated_at: string;
};

export type PipelineStatusResponse = {
  status: PipelineStatus | null;
  latest_run?: PipelineRun | null;
  global_live_stale?: boolean;
  global_live_stale_reason?: string | null;
};

export type PipelineRunSource = 'manual' | 'upload' | 'reset' | 'reprocess' | 'drive_watcher' | string;
export type PipelineRunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'no_input' | 'dispatch_failed' | string;

export type PipelineRun = {
  id: string;
  source: PipelineRunSource;
  status: PipelineRunStatus;
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

export type PipelineRunsResponse = {
  runs: PipelineRun[];
};

export type PipelineDispatchResponse = {
  ok: true;
  pipeline_run_id: string;
  github_actions_url?: string;
};

export type PipelineResetResponse = PipelineDispatchResponse & {
  full_clean: boolean;
};

export type OperatorUploadInitResponse = {
  uploadUrl: string;
  filename: string;
};

export type ReprocessRow = {
  id: string;
  draft_name: string | null;
  notes: string;
  status: string;
  created_at: string;
  processed_at?: string | null;
};

export type ReprocessListResponse = {
  requests: ReprocessRow[];
};

export type ReprocessSubmitResponse = {
  ok: true;
  request_id: string;
  pipeline_run_id: string;
  github_actions_url?: string;
};

export type DraftRow = {
  id: string;
  name: string;
  created_at: string;
  size: number | null;
  watch_url: string | null;
};

export type DraftsResponse = {
  drafts: DraftRow[];
};

export type ApproveDraftResponse = {
  ok?: true;
  drive_move_completed?: boolean;
  delivery_started: boolean;
  delivery_run_id: string;
  github_actions_url?: string;
};

export type DeliveryRunStatus = 'queued' | 'running' | 'discover_published' | 'succeeded' | 'failed' | 'dispatch_failed' | string;

export type DeliveryRun = {
  id: string;
  approved_file_id?: string | null;
  approved_file_name: string | null;
  source_video: string | null;
  status: DeliveryRunStatus;
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

export type DeliveryStatusResponse = {
  runs: DeliveryRun[];
};

export type OperatorReelRow = {
  id: string;
  token: string;
  sport: string | null;
  athlete_desc: string | null;
  status: string;
  expires_at: string;
  recording_date: string | null;
};

export type OperatorReelsResponse = {
  reels: OperatorReelRow[];
};

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

export type SupportReplyResponse = {
  ok: true;
};

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

export type OperatorAnalyticsSummary = {
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
