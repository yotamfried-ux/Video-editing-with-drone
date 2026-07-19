import { supabaseAdmin } from '@/lib/supabase-admin';

export type DraftPublishabilityAuthority = {
  storage_object_id: string;
  draft_name: string;
  pipeline_run_id: string | null;
  athlete_key: string | null;
  part_index: number;
  publishable: boolean;
  qa_evidence_recorded: boolean;
  qa_verdict: string | null;
  qa_passed: boolean;
  technical_issues: string[];
  approval_blocked_reasons: string[];
  media_specs_revision: string | null;
  manifest_revision: string;
  updated_at: string;
};

export class DraftPublishabilityError extends Error {
  status: number;
  authority: DraftPublishabilityAuthority | null;

  constructor(message: string, status = 409, authority: DraftPublishabilityAuthority | null = null) {
    super(message);
    this.name = 'DraftPublishabilityError';
    this.status = status;
    this.authority = authority;
  }
}

function normalize(row: Record<string, unknown>): DraftPublishabilityAuthority {
  return {
    storage_object_id: String(row.storage_object_id ?? ''),
    draft_name: String(row.draft_name ?? ''),
    pipeline_run_id: row.pipeline_run_id ? String(row.pipeline_run_id) : null,
    athlete_key: row.athlete_key ? String(row.athlete_key) : null,
    part_index: Number(row.part_index ?? 0),
    publishable: row.publishable === true,
    qa_evidence_recorded: row.qa_evidence_recorded === true,
    qa_verdict: row.qa_verdict ? String(row.qa_verdict).toUpperCase() : null,
    qa_passed: row.qa_passed === true,
    technical_issues: Array.isArray(row.technical_issues) ? row.technical_issues.map(String) : [],
    approval_blocked_reasons: Array.isArray(row.approval_blocked_reasons)
      ? row.approval_blocked_reasons.map(String)
      : [],
    media_specs_revision: row.media_specs_revision ? String(row.media_specs_revision) : null,
    manifest_revision: String(row.manifest_revision ?? ''),
    updated_at: String(row.updated_at ?? ''),
  };
}

const AUTHORITY_COLUMNS = [
  'storage_object_id',
  'draft_name',
  'pipeline_run_id',
  'athlete_key',
  'part_index',
  'publishable',
  'qa_evidence_recorded',
  'qa_verdict',
  'qa_passed',
  'technical_issues',
  'approval_blocked_reasons',
  'media_specs_revision',
  'manifest_revision',
  'updated_at',
].join(',');

export async function loadAuthoritativeDraftPublishability(
  drafts: Array<{ id: string }>,
): Promise<Map<string, DraftPublishabilityAuthority>> {
  const result = new Map<string, DraftPublishabilityAuthority>();
  if (!drafts.length) return result;

  const objectIds = [...new Set(drafts.map((draft) => draft.id).filter(Boolean))];
  if (!objectIds.length) return result;

  const { data, error } = await supabaseAdmin
    .from('draft_publishability')
    .select(AUTHORITY_COLUMNS)
    .in('storage_object_id', objectIds);
  if (error) throw new DraftPublishabilityError(`Could not read draft publishability: ${error.message}`, 503);

  for (const row of (data ?? []) as unknown as Record<string, unknown>[]) {
    const authority = normalize(row);
    if (authority.storage_object_id) result.set(authority.storage_object_id, authority);
  }
  return result;
}

export async function requireAuthoritativeDraftPublishability(input: {
  storageObjectId: string;
  draftName: string;
}): Promise<DraftPublishabilityAuthority> {
  const authorities = await loadAuthoritativeDraftPublishability([
    { id: input.storageObjectId },
  ]);
  const authority = authorities.get(input.storageObjectId) ?? null;
  if (!authority) {
    throw new DraftPublishabilityError(
      'Authoritative publishability evidence is missing for this storage object. The draft cannot be approved.',
      409,
    );
  }
  if (authority.draft_name !== input.draftName) {
    throw new DraftPublishabilityError(
      'Authoritative publishability evidence does not match the current storage object name.',
      409,
      authority,
    );
  }
  const valid = authority.publishable
    && authority.qa_evidence_recorded
    && authority.qa_verdict === 'PASS'
    && authority.qa_passed
    && authority.technical_issues.length === 0;
  if (!valid) {
    throw new DraftPublishabilityError(
      'The authoritative pipeline result does not allow this draft to be published.',
      409,
      authority,
    );
  }
  return authority;
}
