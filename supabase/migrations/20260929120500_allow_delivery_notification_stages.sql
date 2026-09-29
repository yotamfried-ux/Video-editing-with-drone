-- Allow durable notification evidence between Discover publish and final delivery completion.
-- The delivery worker stores the provider message id in delivery_runs.meta before
-- the workflow finalizer marks the run succeeded/finished.

alter table public.delivery_runs
  drop constraint if exists delivery_runs_stage_chk;

alter table public.delivery_runs
  add constraint delivery_runs_stage_chk check (
    stage in (
      'queued',
      'approved_moved_to_drive',
      'approved_moved_to_r2',
      'delivery_workflow_dispatched',
      'dispatch_failed',
      'starting',
      'scanning_approved',
      'no_approved_drafts',
      'previewing',
      'creating_preview',
      'preview_failed',
      'publishing_discover',
      'discover_published',
      'discover_publish_failed',
      'preview_upload_failed',
      'emailing_athlete',
      'notification_accepted',
      'notification_unverified',
      'finished',
      'failed'
    )
  );
