import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { createUploadSession } from '@/lib/google-drive';
import { createR2UploadUrl, newBatchId, safeBatchId, shouldUseR2Storage } from '@/lib/r2-storage';
import type { UploadFileResult, UploadInitResponse } from '@/types/operator-contracts';

const MAX_BATCH_FILES = 20;

type UploadFileInput = {
  filename?: string;
  mimeType?: string;
  client_upload_id?: string;
};

type UploadBody = {
  filename?: string;
  mimeType?: string;
  batch_id?: string;
  files?: UploadFileInput[];
  upload_mode?: 'resilient_batch_item';
  client_upload_id?: string;
};

type NormalizedUploadFile = {
  filename: string;
  uploadFilename: string;
  mimeType: string;
  clientUploadId?: string;
};

function normalizeUploadFiles(body: UploadBody): NormalizedUploadFile[] {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const rawFiles = Array.isArray(body.files) && body.files.length
    ? body.files
    : (body.filename ?? body.mimeType) !== undefined
      ? [{ filename: body.filename, mimeType: body.mimeType, client_upload_id: body.client_upload_id }]
      : [];
  const isBatch = rawFiles.length > 1;

  return rawFiles.map((file, index) => {
    const filename = (file.filename ?? '').trim() || `footage_${stamp}_${index + 1}.mp4`;
    const uniquePrefix = String(index + 1).padStart(3, '0');
    return {
      filename,
      uploadFilename: isBatch ? `${uniquePrefix}_${filename}` : filename,
      mimeType: (file.mimeType ?? '').trim() || 'video/mp4',
      clientUploadId: (file.client_upload_id ?? '').trim() || undefined,
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

  const resilientBatchItem = body.upload_mode === 'resilient_batch_item' && files.length === 1;
  if (resilientBatchItem && !files[0]?.clientUploadId) {
    return NextResponse.json({ error: 'client_upload_id is required for resilient uploads' }, { status: 400 });
  }

  const limited = await enforceRateLimit(
    req,
    resilientBatchItem
      ? 'operator-upload-resilient-batch-item'
      : files.length > 1
        ? 'operator-upload-batch'
        : 'operator-upload',
    resilientBatchItem ? 120 : files.length > 1 ? 20 : 10,
    3600,
  );
  if (limited) return limited;

  const requestedBatchId = (body.batch_id ?? '').trim();
  const batchId = safeBatchId(requestedBatchId) || newBatchId();

  try {
    if (shouldUseR2Storage()) {
      const uploads: UploadFileResult[] = files.map((file) => {
        const upload = createR2UploadUrl(file.uploadFilename, batchId, file.clientUploadId);
        return {
          uploadUrl: upload.uploadUrl,
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
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : 'Upload init failed' }, { status: 502 });
  }
}
