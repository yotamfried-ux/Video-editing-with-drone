import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { createUploadSession } from '@/lib/google-drive';
import { createR2UploadUrl, newBatchId, safeBatchId, shouldUseR2Storage } from '@/lib/r2-storage';
import {
  registerUploadBatch,
  removeSourceUploadsAfterSetupFailure,
  resolveUploadBatchId,
} from '@/lib/upload-batch-manifest';
import {
  createSourceUploadManifests,
  SourceUploadManifestError,
} from '@/lib/source-upload-manifest';
import type { UploadFileResult, UploadInitResponse } from '@/types/operator-contracts';

const MAX_BATCH_FILES = 20;

type UploadFileInput = {
  filename?: string;
  mimeType?: string;
  size?: number;
};

type UploadBody = {
  filename?: string;
  mimeType?: string;
  size?: number;
  batch_id?: string;
  files?: UploadFileInput[];
};

type NormalizedUploadFile = {
  filename: string;
  uploadFilename: string;
  mimeType: string;
  sourceSizeBytes: number | null;
};

function normalizeUploadFiles(body: UploadBody): NormalizedUploadFile[] {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const rawFiles = Array.isArray(body.files) && body.files.length
    ? body.files
    : (body.filename ?? body.mimeType ?? body.size) !== undefined
      ? [{ filename: body.filename, mimeType: body.mimeType, size: body.size }]
      : [];
  const isBatch = rawFiles.length > 1;

  return rawFiles.map((file, index) => {
    const filename = (file.filename ?? '').trim() || `footage_${stamp}_${index + 1}.mp4`;
    const uniquePrefix = String(index + 1).padStart(3, '0');
    const sourceSizeBytes = Number.isFinite(file.size) && (file.size ?? 0) >= 0
      ? Math.trunc(file.size as number)
      : null;
    return {
      filename,
      uploadFilename: isBatch ? `${uniquePrefix}_${filename}` : filename,
      mimeType: (file.mimeType ?? '').trim() || 'video/mp4',
      sourceSizeBytes,
    };
  });
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

  let batchId: string;
  try {
    batchId = await resolveUploadBatchId(sanitizedRequestedBatchId) ?? newBatchId();
  } catch (error) {
    const status = error instanceof SourceUploadManifestError ? error.status : 503;
    return NextResponse.json({
      error: error instanceof Error ? error.message : 'Could not resolve upload batch',
    }, { status });
  }

  try {
    if (shouldUseR2Storage()) {
      const prepared = files.map((file) => ({ file, upload: createR2UploadUrl(file.uploadFilename, batchId) }));
      const uploadIds = await createSourceUploadManifests(prepared.map(({ file, upload }) => ({
        batchId,
        storageKey: upload.key,
        sourceFilename: file.filename,
        mimeType: file.mimeType,
        sourceSizeBytes: file.sourceSizeBytes,
      })));
      const manifestIds = [...uploadIds.values()];

      try {
        await registerUploadBatch({
          batchId,
          additionalFileCount: files.length,
          sourceKind: 'gallery',
          groupingKind: 'unassigned',
        });
      } catch (error) {
        try {
          await removeSourceUploadsAfterSetupFailure(manifestIds);
        } catch {
          // Preserve the batch registration failure; orphan cleanup remains visible.
        }
        throw error;
      }

      const uploads: UploadFileResult[] = prepared.map(({ file, upload }) => {
        const uploadId = uploadIds.get(upload.key);
        if (!uploadId) throw new SourceUploadManifestError(`Missing upload manifest id for ${upload.key}`, 503);
        return {
          uploadUrl: upload.uploadUrl,
          upload_id: uploadId,
          filename: upload.filename,
          source_filename: file.filename,
          mimeType: file.mimeType,
          batch_id: upload.batch_id,
          storage_backend: 'r2',
          storage_key: upload.key,
        };
      });

      return NextResponse.json<UploadInitResponse>({
        ...uploads[0],
        uploads,
        batch_id: batchId,
        storage_backend: 'r2',
      });
    }

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
      batch_id: batchId,
      storage_backend: 'drive',
    });
  } catch (e) {
    const status = e instanceof SourceUploadManifestError ? e.status : 502;
    return NextResponse.json({ error: e instanceof Error ? e.message : 'Upload init failed' }, { status });
  }
}
