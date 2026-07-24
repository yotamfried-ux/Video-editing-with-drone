import { NextRequest, NextResponse } from 'next/server';
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

        if (!session) {
          throw new SourceUploadManifestError('Single-PUT upload session could not be created or recovered', 503);
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
