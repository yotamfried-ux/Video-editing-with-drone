#!/usr/bin/env python3
"""One-shot deterministic patch for the three final P1 upload review findings."""

from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def patch_r2_storage() -> None:
    path = "web-api/src/lib/r2-storage.ts"
    source = read(path)
    source = replace_once(
        source,
        """function canonicalQuery(params: URLSearchParams): string {
  return [...params.entries()].sort(([a, aValue], [b, bValue]) => {
    const keyOrder = a.localeCompare(b);
    return keyOrder || aValue.localeCompare(bValue);
  }).map(([k, v]) => `${encode(k)}=${encode(v)}`).join('&');
}
""",
        """function compareSigV4Encoded(left: string, right: string): number {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function canonicalQuery(params: URLSearchParams): string {
  return [...params.entries()]
    .map(([name, value]) => [encode(name), encode(value)] as const)
    .sort(([leftName, leftValue], [rightName, rightValue]) => (
      compareSigV4Encoded(leftName, rightName)
      || compareSigV4Encoded(leftValue, rightValue)
    ))
    .map(([name, value]) => `${name}=${value}`)
    .join('&');
}
""",
        "SigV4 encoded byte ordering",
    )
    source = replace_once(
        source,
        """export function createR2UploadUrl(filename: string, requestedBatchId?: string | null): { uploadUrl: string; key: string; filename: string; batch_id: string } {
  const target = createR2UploadTarget(filename, requestedBatchId);
  return { uploadUrl: presign('PUT', target.key), ...target };
}
""",
        """export function createR2UploadUrl(filename: string, requestedBatchId?: string | null): { uploadUrl: string; key: string; filename: string; batch_id: string } {
  const target = createR2UploadTarget(filename, requestedBatchId);
  return { uploadUrl: presign('PUT', target.key), ...target };
}

export function createR2UploadUrlForKey(key: string): string {
  if (!key.startsWith('raw/')) throw new Error('Single-PUT upload URLs are limited to raw/ keys');
  return presign('PUT', key);
}
""",
        "stable-key single PUT URL",
    )
    if "localeCompare" in source:
        raise SystemExit("SigV4 canonical query must not use localeCompare")
    write(path, source)


def patch_mobile_pipeline() -> None:
    path = "mobile/src/app/(operator)/pipeline.tsx"
    source = read(path)
    source = replace_once(
        source,
        """type UploadSession = OperatorUploadInitResponse & {
  mimeType?: string | null;
  storage_key?: string;
  storage_backend?: string;
};
""",
        """type UploadSession = OperatorUploadInitResponse & {
  mimeType?: string | null;
  storage_key?: string;
  storage_backend?: string;
  client_upload_id?: string;
  upload_status?: string;
};
""",
        "mobile upload session fields",
    )
    source = replace_once(
        source,
        """  sourceSizeBytes?: number;
  progress: number;
""",
        """  sourceSizeBytes?: number;
  clientUploadId?: string;
  progress: number;
""",
        "mobile stable single-PUT id",
    )
    source = replace_once(
        source,
        """  const uploadAssetToSession = async (item: UploadFileState, session: UploadSession) => {
    if (!session.uploadUrl) throw new Error(`Missing upload URL for ${item.filename}`);

    updateUploadItem(item.id, {
""",
        """  const uploadAssetToSession = async (item: UploadFileState, session: UploadSession) => {
    if (session.upload_status === 'verified') {
      item.batch_id = session.batch_id;
      updateUploadItem(item.id, {
        status: 'verified',
        progress: 100,
        batch_id: session.batch_id,
        error: null,
      });
      return;
    }
    if (!session.uploadUrl) throw new Error(`Missing upload URL for ${item.filename}`);

    updateUploadItem(item.id, {
""",
        "verified single-PUT recovery",
    )
    source = replace_once(
        source,
        """  const requestUploadSession = async (item: UploadFileState): Promise<UploadSession> => {
    let sourceSizeBytes = item.sourceSizeBytes;
""",
        """  const requestUploadSession = async (item: UploadFileState): Promise<UploadSession> => {
    const clientUploadId = item.clientUploadId
      ?? `gallery_${Date.now()}_${Math.random().toString(36).slice(2, 12)}`;
    item.clientUploadId = clientUploadId;

    let sourceSizeBytes = item.sourceSizeBytes;
""",
        "stable client ID before upload init",
    )
    source = replace_once(
        source,
        """          filename: item.filename,
          mimeType: item.mimeType,
          size: sourceSizeBytes,
""",
        """          client_upload_id: clientUploadId,
          filename: item.filename,
          mimeType: item.mimeType,
          size: sourceSizeBytes,
""",
        "single-PUT client ID request",
    )
    source = replace_once(
        source,
        """        sourceSizeBytes: asset.fileSize ?? undefined,
        progress: 0,
""",
        """        sourceSizeBytes: asset.fileSize ?? undefined,
        clientUploadId: `gallery_${Date.now()}_${index}_${Math.random().toString(36).slice(2, 12)}`,
        progress: 0,
""",
        "gallery item client ID",
    )
    write(path, source)


def patch_contracts() -> None:
    path = "web-api/src/types/operator-contracts.ts"
    source = read(path)
    source = replace_once(
        source,
        """  storage_backend: 'r2' | 'drive';
  storage_key?: string;
};
""",
        """  storage_backend: 'r2' | 'drive';
  storage_key?: string;
  client_upload_id?: string;
  upload_status?: string;
};
""",
        "web upload response contract",
    )
    write(path, source)

    path = "mobile/src/features/operator/types/contracts.ts"
    source = read(path)
    source = replace_once(
        source,
        """export type OperatorUploadInitResponse = {
  uploadUrl: string;
  filename: string;
  batch_id?: string | null;
};
""",
        """export type OperatorUploadInitResponse = {
  uploadUrl: string;
  filename: string;
  batch_id?: string | null;
  client_upload_id?: string;
  upload_status?: string;
};
""",
        "mobile upload response contract",
    )
    write(path, source)


def patch_operator_smoke_workflow() -> None:
    path = ".github/workflows/operator-smoke-check.yml"
    source = read(path)
    source = replace_once(
        source,
        """            'uploadFilename',
            'createR2UploadUrl(file.uploadFilename, batchId)',
            'createUploadSession(file.uploadFilename, rawFolder, file.mimeType)',
            'source_filename: file.filename',
            'storage_key: upload.key',
""",
        """            'uploadFilename',
            'client_upload_id?: string',
            'createSinglePutSourceManifest',
            'createR2UploadUrlForKey(session.storageKey)',
            'registerSourceUploadBatchMembership',
            'createUploadSession(file.uploadFilename, rawFolder, file.mimeType)',
            'source_filename: session.sourceFilename',
            'storage_key: session.storageKey',
""",
        "operator smoke upload contract",
    )
    write(path, source)


def patch_test_contracts() -> None:
    path = "scripts/test_batch_scope_contract.py"
    source = read(path)
    source = replace_once(
        source,
        """            "resolveUploadBatchId",
            "createR2UploadUrl(file.uploadFilename, batchId)",
            "registerUploadBatch",
            "batch_id: upload.batch_id",
            "uploads,",
""",
        """            "resolveUploadBatchId",
            "client_upload_id",
            "createSinglePutSourceManifest",
            "createR2UploadUrlForKey(session.storageKey)",
            "registerSourceUploadBatchMembership",
            "batch_id: session.batchId",
            "uploads,",
""",
        "batch scope single-PUT contract",
    )
    write(path, source)

    path = "scripts/test_exact_source_upload_dedup_contract.py"
    source = read(path)
    source = replace_once(
        source,
        """    require("upload init manifest", upload_route, [
        "createSourceUploadManifests",
        "sourceSizeBytes: file.sourceSizeBytes",
        "upload_id: uploadId",
    ])
""",
        """    require("upload init manifest", upload_route, [
        "client_upload_id",
        "createSinglePutSourceManifest",
        "sourceSizeBytes: file.sourceSizeBytes",
        "upload_id: session.uploadId",
        "registerSourceUploadBatchMembership",
    ])
""",
        "exact dedup upload init contract",
    )
    write(path, source)

    path = "scripts/test_upload_batch_verified_gate_contract.py"
    source = read(path)
    source = replace_once(
        source,
        """            "resolveUploadBatchId",
            "createSourceUploadManifests",
            "registerUploadBatch",
            "additionalFileCount: files.length",
            "sourceKind: 'gallery'",
            "removeSourceUploadsAfterSetupFailure",
""",
        """            "resolveUploadBatchId",
            "client_upload_id",
            "findSourceUploadByClientUploadId",
            "createSinglePutSourceManifest",
            "registerSourceUploadBatchMembership",
            "createR2UploadUrlForKey(session.storageKey)",
            "upload_status: session.status",
""",
        "verified batch single-PUT idempotency contract",
    )
    write(path, source)

    path = "scripts/test_large_upload_foundation_contract.py"
    source = read(path)
    source = replace_once(
        source,
        """            "x-amz-content-sha256",
        ],
""",
        """            "x-amz-content-sha256",
            "compareSigV4Encoded",
            ".map(([name, value]) => [encode(name), encode(value)] as const)",
            "createR2UploadUrlForKey",
        ],
""",
        "large upload SigV4 contract",
    )
    source = replace_once(
        source,
        """            "multipart_etag_is_source_md5: true",
        ],
""",
        """            "multipart_etag_is_source_md5: true",
            "localeCompare",
        ],
""",
        "forbid locale-aware SigV4 sorting",
    )
    source = replace_once(
        source,
        """    require(part_url, ["getMultipartSession", "createR2MultipartPartUploadUrl", "size_bytes"], "part URL endpoint")
""",
        """    require(part_url, ["getMultipartSession", "createR2MultipartPartUploadUrl", "R2_MAX_MULTIPART_PARTS * 2", "uploadId", "size_bytes"], "part URL endpoint")
""",
        "part URL rate-limit contract",
    )
    write(path, source)


def write_source_manifest() -> None:
    write(
        "web-api/src/lib/source-upload-manifest.ts",
        """import { supabaseAdmin } from '@/lib/supabase-admin';

export class SourceUploadManifestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'SourceUploadManifestError';
  }
}

type SourceUploadManifestInput = {
  batchId: string;
  storageKey: string;
  sourceFilename: string;
  mimeType: string;
  sourceSizeBytes?: number | null;
};

type SinglePutSourceManifestInput = {
  clientUploadId: string;
  batchId: string;
  storageKey: string;
  sourceFilename: string;
  mimeType: string;
  sourceSizeBytes: number;
};

export type SourceUploadSession = {
  uploadId: string;
  clientUploadId: string | null;
  batchId: string;
  storageKey: string;
  sourceFilename: string;
  mimeType: string | null;
  sourceSizeBytes: number | null;
  status: string;
  uploadProtocol: string;
};

type VerifySourceUploadResult = {
  upload_id: string;
  status: 'verified' | 'size_mismatch';
  source_size_bytes: number | null;
  verified_size_bytes: number;
  verified_at: string | null;
};

type SourceUploadRow = {
  id: unknown;
  client_upload_id: unknown;
  batch_id: unknown;
  storage_key: unknown;
  source_filename: unknown;
  mime_type: unknown;
  source_size_bytes: unknown;
  status: unknown;
  upload_protocol: unknown;
};

const SOURCE_SESSION_COLUMNS = 'id,client_upload_id,batch_id,storage_key,source_filename,mime_type,source_size_bytes,status,upload_protocol';

function sourceUploadSession(row: SourceUploadRow): SourceUploadSession {
  return {
    uploadId: String(row.id),
    clientUploadId: row.client_upload_id == null ? null : String(row.client_upload_id),
    batchId: String(row.batch_id),
    storageKey: String(row.storage_key),
    sourceFilename: String(row.source_filename),
    mimeType: row.mime_type == null ? null : String(row.mime_type),
    sourceSizeBytes: row.source_size_bytes == null ? null : Number(row.source_size_bytes),
    status: String(row.status),
    uploadProtocol: String(row.upload_protocol),
  };
}

export async function findSourceUploadByClientUploadId(
  clientUploadId: string,
): Promise<SourceUploadSession | null> {
  const { data, error } = await supabaseAdmin
    .from('source_uploads')
    .select(SOURCE_SESSION_COLUMNS)
    .eq('client_upload_id', clientUploadId)
    .maybeSingle();
  if (error) {
    throw new SourceUploadManifestError(`Could not recover source upload: ${error.message}`, 503);
  }
  return data ? sourceUploadSession(data as SourceUploadRow) : null;
}

export async function createSinglePutSourceManifest(
  input: SinglePutSourceManifestInput,
): Promise<{ session: SourceUploadSession; created: boolean }> {
  if (!Number.isSafeInteger(input.sourceSizeBytes) || input.sourceSizeBytes <= 0) {
    throw new SourceUploadManifestError('Single-PUT source size must be a positive integer', 400);
  }
  const now = new Date().toISOString();
  const { data, error } = await supabaseAdmin
    .from('source_uploads')
    .insert({
      client_upload_id: input.clientUploadId,
      batch_id: input.batchId,
      storage_key: input.storageKey,
      source_filename: input.sourceFilename,
      mime_type: input.mimeType,
      source_size_bytes: input.sourceSizeBytes,
      source_size_evidence: 'client_declared',
      status: 'uploading',
      upload_protocol: 'single_put',
      local_cleanup_required: false,
      local_cleanup_status: 'not_required',
      updated_at: now,
    })
    .select(SOURCE_SESSION_COLUMNS)
    .single();

  if (!error && data) {
    return { session: sourceUploadSession(data as SourceUploadRow), created: true };
  }
  if (error?.code === '23505') {
    const existing = await findSourceUploadByClientUploadId(input.clientUploadId);
    if (existing) return { session: existing, created: false };
  }
  throw new SourceUploadManifestError(
    `Could not persist single-PUT upload manifest: ${error?.message ?? 'missing source upload row'}`,
    503,
  );
}

export async function registerSourceUploadBatchMembership(
  uploadId: string,
  sourceKind: 'operator' | 'android_external' | 'gallery' | 'api',
  groupingKind: 'unassigned' | 'one_athlete' | 'session_multiple_athletes' | 'other',
): Promise<void> {
  const { error } = await supabaseAdmin.rpc('register_source_upload_batch_membership', {
    p_upload_id: uploadId,
    p_source_kind: sourceKind,
    p_grouping_kind: groupingKind,
  });
  if (error) {
    const status = /not found|cannot accept|invalid|mismatch/i.test(error.message) ? 409 : 503;
    throw new SourceUploadManifestError(`Could not register source upload batch membership: ${error.message}`, status);
  }
}

export async function createSourceUploadManifests(
  inputs: SourceUploadManifestInput[],
): Promise<Map<string, string>> {
  if (!inputs.length) return new Map();
  const now = new Date().toISOString();
  const rows = inputs.map((input) => ({
    batch_id: input.batchId,
    storage_key: input.storageKey,
    source_filename: input.sourceFilename,
    mime_type: input.mimeType,
    source_size_bytes:
      Number.isFinite(input.sourceSizeBytes) && (input.sourceSizeBytes ?? 0) >= 0
        ? Math.trunc(input.sourceSizeBytes as number)
        : null,
    status: 'uploading',
    updated_at: now,
  }));
  const { data, error } = await supabaseAdmin
    .from('source_uploads')
    .insert(rows)
    .select('id,storage_key');

  if (error || !data || data.length !== rows.length) {
    throw new SourceUploadManifestError(
      `Could not persist upload manifest: ${error?.message ?? 'incomplete source upload rows'}`,
      503,
    );
  }
  return new Map(data.map((row) => [String(row.storage_key), String(row.id)]));
}

export async function markSourceUploadVerified(storageKey: string, verifiedSizeBytes: number): Promise<{
  uploadId: string;
  verifiedAt: string;
  status: 'verified';
}> {
  const { data, error } = await supabaseAdmin.rpc('verify_source_upload', {
    p_storage_key: storageKey,
    p_verified_size_bytes: verifiedSizeBytes,
  });

  if (error) {
    const status = /not found|superseded/i.test(error.message) ? 409 : 503;
    throw new SourceUploadManifestError(`Could not verify upload manifest: ${error.message}`, status);
  }

  const raw = Array.isArray(data) && data.length === 1 ? data[0] : data;
  const result = raw as VerifySourceUploadResult | null;
  if (!result?.upload_id || !result.status) {
    throw new SourceUploadManifestError('Upload verification returned an invalid manifest result', 503);
  }
  if (result.status === 'size_mismatch') {
    throw new SourceUploadManifestError(
      `Uploaded object size mismatch: expected ${result.source_size_bytes}, got ${result.verified_size_bytes}`,
      409,
    );
  }
  if (result.status !== 'verified' || !result.verified_at) {
    throw new SourceUploadManifestError(`Upload manifest did not reach verified state for ${storageKey}`, 503);
  }

  return {
    uploadId: String(result.upload_id),
    verifiedAt: result.verified_at,
    status: 'verified',
  };
}
""",
    )


def write_upload_route() -> None:
    write(
        "web-api/src/app/api/operator/upload/route.ts",
        """import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { createUploadSession } from '@/lib/google-drive';
import {
  createR2UploadTarget,
  createR2UploadUrlForKey,
  newBatchId,
  r2Basename,
  safeBatchId,
  shouldUseR2Storage,
} from '@/lib/r2-storage';
import {
  removeSourceUploadsAfterSetupFailure,
  resolveUploadBatchId,
} from '@/lib/upload-batch-manifest';
import {
  createSinglePutSourceManifest,
  findSourceUploadByClientUploadId,
  registerSourceUploadBatchMembership,
  SourceUploadManifestError,
  type SourceUploadSession,
} from '@/lib/source-upload-manifest';
import type { UploadFileResult, UploadInitResponse } from '@/types/operator-contracts';

const MAX_BATCH_FILES = 20;
const CLIENT_UPLOAD_ID_PATTERN = /^[A-Za-z0-9_-]{16,128}$/;

type UploadFileInput = {
  client_upload_id?: string;
  filename?: string;
  mimeType?: string;
  size?: number;
};

type UploadBody = {
  client_upload_id?: string;
  filename?: string;
  mimeType?: string;
  size?: number;
  batch_id?: string;
  files?: UploadFileInput[];
};

type NormalizedUploadFile = {
  clientUploadId: string;
  filename: string;
  uploadFilename: string;
  mimeType: string;
  sourceSizeBytes: number | null;
};

function normalizeUploadFiles(body: UploadBody): NormalizedUploadFile[] {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const rawFiles = Array.isArray(body.files) && body.files.length
    ? body.files
    : (body.filename ?? body.mimeType ?? body.size ?? body.client_upload_id) !== undefined
      ? [{
          client_upload_id: body.client_upload_id,
          filename: body.filename,
          mimeType: body.mimeType,
          size: body.size,
        }]
      : [];
  const isBatch = rawFiles.length > 1;

  return rawFiles.map((file, index) => {
    const filename = (file.filename ?? '').trim() || `footage_${stamp}_${index + 1}.mp4`;
    const uniquePrefix = String(index + 1).padStart(3, '0');
    const sourceSizeBytes = Number.isFinite(file.size) && (file.size ?? 0) > 0
      ? Math.trunc(file.size as number)
      : null;
    return {
      clientUploadId: (file.client_upload_id ?? '').trim(),
      filename,
      uploadFilename: isBatch ? `${uniquePrefix}_${filename}` : filename,
      mimeType: (file.mimeType ?? '').trim() || 'video/mp4',
      sourceSizeBytes,
    };
  });
}

function assertSinglePutSourceMatches(input: {
  session: SourceUploadSession;
  file: NormalizedUploadFile;
  batchId: string;
}): void {
  const { session, file, batchId } = input;
  if (session.clientUploadId !== file.clientUploadId) {
    throw new SourceUploadManifestError('Idempotent single-PUT source identifier mismatch', 409);
  }
  if (session.uploadProtocol !== 'single_put') {
    throw new SourceUploadManifestError('Idempotent source is not a single-PUT upload', 409);
  }
  if (session.batchId !== batchId) {
    throw new SourceUploadManifestError(`Idempotent source belongs to batch ${session.batchId}, not ${batchId}`, 409);
  }
  if (session.sourceFilename !== file.filename) {
    throw new SourceUploadManifestError('Idempotent single-PUT source filename changed', 409);
  }
  if (session.sourceSizeBytes !== file.sourceSizeBytes) {
    throw new SourceUploadManifestError('Idempotent single-PUT source size changed', 409);
  }
  if (session.mimeType && session.mimeType !== file.mimeType) {
    throw new SourceUploadManifestError('Idempotent single-PUT source MIME type changed', 409);
  }
  if (!['uploading', 'verified'].includes(session.status)) {
    throw new SourceUploadManifestError(`Single-PUT upload cannot resume from status ${session.status}`, 409);
  }
}

async function resolveSinglePutBatchId(
  files: NormalizedUploadFile[],
  requestedBatchId: string,
): Promise<{ batchId: string; existing: Map<string, SourceUploadSession> }> {
  const existing = new Map<string, SourceUploadSession>();
  for (const file of files) {
    if (!CLIENT_UPLOAD_ID_PATTERN.test(file.clientUploadId)) {
      throw new SourceUploadManifestError(
        'client_upload_id must be a stable 16-128 character identifier for every R2 single-PUT source',
        400,
      );
    }
    if (file.sourceSizeBytes == null) {
      throw new SourceUploadManifestError('A positive integer source size is required for every R2 upload', 400);
    }
    const session = await findSourceUploadByClientUploadId(file.clientUploadId);
    if (session) existing.set(file.clientUploadId, session);
  }

  const existingBatchIds = [...new Set([...existing.values()].map((session) => session.batchId))];
  if (existingBatchIds.length > 1) {
    throw new SourceUploadManifestError('Requested files already belong to multiple durable batches', 409);
  }
  if (requestedBatchId && existingBatchIds[0] && existingBatchIds[0] !== requestedBatchId) {
    throw new SourceUploadManifestError(
      `Idempotent upload belongs to batch ${existingBatchIds[0]}, not ${requestedBatchId}`,
      409,
    );
  }
  const batchId = existingBatchIds[0]
    ?? await resolveUploadBatchId(requestedBatchId)
    ?? newBatchId();
  return { batchId, existing };
}

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  let body: UploadBody = {};
  try {
    body = await req.json();
  } catch {}

  const files = normalizeUploadFiles(body);
  if (!files.length) return NextResponse.json({ error: 'No files requested' }, { status: 400 });
  if (files.length > MAX_BATCH_FILES) {
    return NextResponse.json({ error: `Too many files in one batch. Max is ${MAX_BATCH_FILES}.` }, { status: 413 });
  }

  const limited = await enforceRateLimit(
    req,
    files.length > 1 ? 'operator-upload-batch' : 'operator-upload',
    files.length > 1 ? 20 : 10,
    3600,
  );
  if (limited) return limited;

  const requestedBatchId = (body.batch_id ?? '').trim();
  const sanitizedRequestedBatchId = safeBatchId(requestedBatchId);
  if (requestedBatchId && sanitizedRequestedBatchId !== requestedBatchId) {
    return NextResponse.json({ error: 'batch_id contains unsupported characters' }, { status: 400 });
  }

  try {
    if (shouldUseR2Storage()) {
      const resolved = await resolveSinglePutBatchId(files, sanitizedRequestedBatchId);
      const uploads: UploadFileResult[] = [];

      for (const file of files) {
        const prior = resolved.existing.get(file.clientUploadId);
        let session = prior;
        let created = false;
        if (!session) {
          const target = createR2UploadTarget(file.uploadFilename, resolved.batchId);
          const result = await createSinglePutSourceManifest({
            clientUploadId: file.clientUploadId,
            batchId: resolved.batchId,
            storageKey: target.key,
            sourceFilename: file.filename,
            mimeType: file.mimeType,
            sourceSizeBytes: file.sourceSizeBytes as number,
          });
          session = result.session;
          created = result.created;
        }

        assertSinglePutSourceMatches({ session, file, batchId: resolved.batchId });
        try {
          await registerSourceUploadBatchMembership(session.uploadId, 'gallery', 'unassigned');
        } catch (error) {
          if (created) {
            try {
              await removeSourceUploadsAfterSetupFailure([session.uploadId]);
            } catch {
              // Preserve the membership failure; orphan cleanup remains visible.
            }
          }
          throw error;
        }

        uploads.push({
          uploadUrl: createR2UploadUrlForKey(session.storageKey),
          upload_id: session.uploadId,
          client_upload_id: file.clientUploadId,
          upload_status: session.status,
          filename: r2Basename(session.storageKey),
          source_filename: session.sourceFilename,
          mimeType: session.mimeType ?? file.mimeType,
          batch_id: session.batchId,
          storage_backend: 'r2',
          storage_key: session.storageKey,
        });
      }

      return NextResponse.json<UploadInitResponse>({
        ...uploads[0],
        uploads,
      });
    }

    const batchId = await resolveUploadBatchId(sanitizedRequestedBatchId) ?? newBatchId();
    const rawFolder = process.env.RAW_FOLDER_ID;
    if (!rawFolder) return NextResponse.json({ error: 'RAW_FOLDER_ID not configured' }, { status: 503 });

    const uploads: UploadFileResult[] = await Promise.all(
      files.map(async (file) => ({
        uploadUrl: await createUploadSession(file.uploadFilename, rawFolder, file.mimeType),
        filename: file.uploadFilename,
        source_filename: file.filename,
        mimeType: file.mimeType,
        batch_id: batchId,
        storage_backend: 'drive' as const,
      })),
    );

    return NextResponse.json<UploadInitResponse>({
      ...uploads[0],
      uploads,
    });
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 502;
    return NextResponse.json({ error: error instanceof Error ? error.message : 'Upload init failed' }, { status });
  }
}
""",
    )


def write_ratelimit() -> None:
    write(
        "web-api/src/lib/ratelimit.ts",
        """import { NextRequest, NextResponse } from 'next/server';
import { Ratelimit } from '@upstash/ratelimit';
import { Redis } from '@upstash/redis';

/**
 * Upstash-backed rate limiting. Serverless functions don't share memory across
 * invocations, so an in-memory limiter is useless on Vercel — a central store
 * (Upstash Redis) is required.
 *
 * If UPSTASH_REDIS_REST_URL/TOKEN are unset (e.g. local dev), limiting is
 * disabled (fail-open) rather than erroring, so the API still runs.
 */
const redis =
  process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN
    ? Redis.fromEnv()
    : null;

const limiters = new Map<string, Ratelimit>();

function getLimiter(name: string, limit: number, windowSec: number): Ratelimit | null {
  if (!redis) return null;
  const key = `${name}:${limit}:${windowSec}`;
  let limiter = limiters.get(key);
  if (!limiter) {
    limiter = new Ratelimit({
      redis,
      limiter: Ratelimit.slidingWindow(limit, `${windowSec} s`),
      prefix: `rl:${name}`,
    });
    limiters.set(key, limiter);
  }
  return limiter;
}

function clientIp(req: NextRequest): string {
  const forwarded = req.headers.get('x-forwarded-for');
  if (forwarded) return forwarded.split(',')[0].trim();
  return req.headers.get('x-real-ip') ?? 'unknown';
}

/**
 * Enforce a rate limit for the given route name. `subject` scopes high-volume,
 * authenticated operations such as multipart part URLs to one durable upload
 * rather than making unrelated files behind the same mobile IP consume one cap.
 */
export async function enforceRateLimit(
  req: NextRequest,
  name: string,
  limit: number,
  windowSec: number,
  subject?: string,
): Promise<NextResponse | null> {
  const limiter = getLimiter(name, limit, windowSec);
  if (!limiter) return null;
  const identity = subject?.trim() || clientIp(req);
  const { success } = await limiter.limit(`${name}:${identity}`);
  if (!success) {
    return NextResponse.json({ error: 'Too many requests' }, { status: 429 });
  }
  return null;
}
""",
    )


def write_part_url_route() -> None:
    write(
        "web-api/src/app/api/operator/upload/multipart/part-url/route.ts",
        """import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import {
  createR2MultipartPartUploadUrl,
  R2_MAX_MULTIPART_PARTS,
} from '@/lib/r2-storage';
import { getMultipartSession } from '@/lib/multipart-upload-manifest';
import { SourceUploadManifestError } from '@/lib/source-upload-manifest';

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  let body: { upload_id?: string; part_number?: number };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const uploadId = (body.upload_id ?? '').trim();
  const partNumber = Number(body.part_number);
  if (!uploadId) return NextResponse.json({ error: 'upload_id required' }, { status: 400 });
  if (!Number.isInteger(partNumber)) {
    return NextResponse.json({ error: 'part_number must be an integer' }, { status: 400 });
  }

  try {
    const session = await getMultipartSession(uploadId);
    const limited = await enforceRateLimit(
      req,
      'operator-multipart-part-url',
      R2_MAX_MULTIPART_PARTS * 2,
      3600,
      uploadId,
    );
    if (limited) return limited;

    if (!['uploading', 'paused'].includes(session.status)) {
      return NextResponse.json({
        error: `Multipart part URL is unavailable while upload is ${session.status}`,
      }, { status: 409 });
    }
    if (partNumber < 1 || partNumber > session.expected_part_count) {
      return NextResponse.json({
        error: `part_number must be between 1 and ${session.expected_part_count}`,
      }, { status: 400 });
    }

    const sizeBytes = partNumber < session.expected_part_count
      ? session.part_size_bytes
      : session.source_size_bytes - (session.part_size_bytes * (session.expected_part_count - 1));
    const uploadUrl = createR2MultipartPartUploadUrl(
      session.storage_key,
      session.multipart_upload_id,
      partNumber,
    );

    return NextResponse.json({
      ok: true,
      upload_id: uploadId,
      part_number: partNumber,
      size_bytes: sizeBytes,
      upload_url: uploadUrl,
      expires_in_seconds: 900,
    });
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 502;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Multipart part URL failed',
    }, { status });
  }
}
""",
    )


def main() -> int:
    patch_r2_storage()
    patch_mobile_pipeline()
    patch_contracts()
    patch_operator_smoke_workflow()
    patch_test_contracts()
    write_source_manifest()
    write_upload_route()
    write_ratelimit()
    write_part_url_route()

    required = {
        "web-api/src/lib/r2-storage.ts": ["compareSigV4Encoded", "createR2UploadUrlForKey"],
        "web-api/src/app/api/operator/upload/route.ts": ["client_upload_id", "createSinglePutSourceManifest", "registerSourceUploadBatchMembership"],
        "mobile/src/app/(operator)/pipeline.tsx": ["clientUploadId", "client_upload_id: clientUploadId", "upload_status === 'verified'"],
        "web-api/src/app/api/operator/upload/multipart/part-url/route.ts": ["R2_MAX_MULTIPART_PARTS * 2", "uploadId"],
    }
    for path, tokens in required.items():
        text = read(path)
        missing = [token for token in tokens if token not in text]
        if missing:
            raise SystemExit(f"{path} missing final review fixes: {missing}")

    print("Final upload review fixes applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
