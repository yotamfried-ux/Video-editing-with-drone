from pathlib import Path


PIPELINE = Path('mobile/src/app/(operator)/pipeline.tsx')
text = PIPELINE.read_text(encoding='utf-8')

text = text.replace(
    "const EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT = 1;\n",
    "const EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT = 1;\nconst MAX_UPLOAD_BATCH_FILES = 20;\nconst MAX_UPLOAD_ATTEMPTS = 3;\nconst UPLOAD_RETRY_DELAYS_MS = [2000, 5000];\n",
    1,
)
text = text.replace(
    "  requiresLocalCopy?: boolean;\n};",
    "  requiresLocalCopy?: boolean;\n  storage_key?: string | null;\n  attempt?: number;\n};",
    1,
)
text = text.replace(
    "function cacheSafeFilename(filename: string): string {\n  return filename.replace(/[^a-zA-Z0-9._-]/g, '_');\n}\n",
    "function cacheSafeFilename(filename: string): string {\n  return filename.replace(/[^a-zA-Z0-9._-]/g, '_');\n}\n\nfunction wait(ms: number): Promise<void> {\n  return new Promise((resolve) => setTimeout(resolve, ms));\n}\n",
    1,
)
text = text.replace(
    "  const [externalCandidates, setExternalCandidates] = useState<ExternalVideoCandidate[]>([]);\n  const [uploadItems, setUploadItems] = useState<UploadFileState[]>([]);",
    "  const [externalCandidates, setExternalCandidates] = useState<ExternalVideoCandidate[]>([]);\n  const [retryingFailedUploads, setRetryingFailedUploads] = useState(false);\n  const [uploadItems, setUploadItems] = useState<UploadFileState[]>([]);",
    1,
)

start = text.index('  const uploadAssetToSession = async')
end = text.index('  const uploadFootage = async', start)
replacement = r'''  const uploadAssetToSession = async (
    item: UploadFileState,
    session: UploadSession,
    preparedUploadUri?: string
  ) => {
    if (!session.uploadUrl) throw new Error(`Missing upload URL for ${item.filename}`);

    let uploadUri = preparedUploadUri ?? item.uri;
    let temporaryUploadUri: string | null = null;
    updateUploadItem(item.id, {
      status: item.requiresLocalCopy && !preparedUploadUri ? 'initializing' : 'uploading',
      progress: 0,
      batch_id: session.batch_id,
      storage_key: session.storage_key ?? null,
      error: null,
    });

    try {
      if (item.requiresLocalCopy && !preparedUploadUri) {
        if (!FileSystem.cacheDirectory) {
          throw new Error('App cache is unavailable for the selected SD / USB video.');
        }
        temporaryUploadUri = `${FileSystem.cacheDirectory}sportreel-upload-${Date.now()}-${cacheSafeFilename(item.id)}-${cacheSafeFilename(item.filename)}`;
        await FileSystem.copyAsync({ from: item.uri, to: temporaryUploadUri });
        uploadUri = temporaryUploadUri;
        updateUploadItem(item.id, { status: 'uploading' });
      }

      const task = FileSystem.createUploadTask(
        session.uploadUrl,
        uploadUri,
        {
          httpMethod: 'PUT',
          uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT,
          headers: { 'Content-Type': item.mimeType },
        },
        (progress) => {
          const expected = progress.totalBytesExpectedToSend || 1;
          const pct = Math.round((progress.totalBytesSent / expected) * 100);
          updateUploadItem(item.id, { progress: pct });
        }
      );
      const uploadResult = await task.uploadAsync();
      if (!uploadResult || uploadResult.status >= 300) {
        throw new Error(`Upload failed with status ${uploadResult?.status}`);
      }

      if (session.storage_key) {
        const verified = await operatorFetch<UploadVerify>('/api/operator/upload/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ storage_key: session.storage_key }),
        });
        if (!verified.exists) {
          throw new Error(`Upload finished but R2 verification failed for ${session.storage_key}`);
        }
      }

      updateUploadItem(item.id, {
        status: 'verified',
        progress: 100,
        batch_id: session.batch_id,
        storage_key: session.storage_key ?? null,
        error: null,
      });
    } finally {
      if (temporaryUploadUri) {
        try {
          await FileSystem.deleteAsync(temporaryUploadUri, { idempotent: true });
        } catch {
          // Cache cleanup must not hide the upload result.
        }
      }
    }
  };

  const initializeResilientUploadSession = async (
    item: UploadFileState,
    batchId: string | null
  ): Promise<UploadSession> => {
    const uploadInit = await operatorFetch<UploadInit>('/api/operator/upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: item.filename,
        mimeType: item.mimeType,
        batch_id: batchId,
        upload_mode: 'resilient_batch_item',
        client_upload_id: item.id,
      }),
    });
    return uploadInit.uploads?.[0] ?? uploadInit;
  };

  const uploadExternalItemWithRetries = async (
    item: UploadFileState,
    startingBatchId: string | null
  ): Promise<string | null> => {
    if (!FileSystem.cacheDirectory) {
      throw new Error('App cache is unavailable for the selected SD / USB video.');
    }

    const temporaryUploadUri = `${FileSystem.cacheDirectory}sportreel-upload-${Date.now()}-${cacheSafeFilename(item.id)}-${cacheSafeFilename(item.filename)}`;
    let batchId = startingBatchId;
    updateUploadItem(item.id, { status: 'initializing', progress: 0, error: null, attempt: 1 });

    try {
      await FileSystem.copyAsync({ from: item.uri, to: temporaryUploadUri });

      for (let attempt = 1; attempt <= MAX_UPLOAD_ATTEMPTS; attempt += 1) {
        try {
          updateUploadItem(item.id, {
            status: 'initializing',
            progress: 0,
            attempt,
            error: attempt > 1 ? `Retrying automatically (${attempt}/${MAX_UPLOAD_ATTEMPTS})` : null,
          });
          const session = await initializeResilientUploadSession(item, batchId);
          batchId = session.batch_id ?? batchId;
          if (batchId) setActiveBatchId(batchId);
          await uploadAssetToSession(
            { ...item, requiresLocalCopy: false, batch_id: batchId },
            session,
            temporaryUploadUri
          );
          return batchId;
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Upload failed';
          if (attempt >= MAX_UPLOAD_ATTEMPTS) throw error;
          updateUploadItem(item.id, {
            status: 'initializing',
            progress: 0,
            error: `${message} · retrying automatically`,
            attempt,
          });
          await wait(UPLOAD_RETRY_DELAYS_MS[attempt - 1] ?? 5000);
        }
      }
      return batchId;
    } finally {
      try {
        await FileSystem.deleteAsync(temporaryUploadUri, { idempotent: true });
      } catch {
        // Cache cleanup must not hide the final upload result.
      }
    }
  };

  const uploadExternalItemsSequentially = async (
    items: UploadFileState[],
    startingBatchId: string | null,
    announceResult: boolean
  ) => {
    let batchId = startingBatchId;
    let failedCount = 0;

    for (const item of items) {
      try {
        batchId = await uploadExternalItemWithRetries(item, batchId);
      } catch (error) {
        failedCount += 1;
        updateUploadItem(item.id, {
          status: 'failed',
          error: error instanceof Error ? error.message : 'Upload failed',
        });
      }
    }

    if (!announceResult) return;
    if (failedCount) {
      Alert.alert(
        'Some uploads failed',
        `${failedCount} of ${items.length} files failed after ${MAX_UPLOAD_ATTEMPTS} attempts. Check the connection, then use Retry all failed.`
      );
      return;
    }

    Alert.alert(
      'Uploaded to queue',
      `${items.length} file${items.length === 1 ? '' : 's'} verified in RAW batch ${batchId?.slice(0, 16) ?? 'current'}. Upload more footage, then run the pipeline only when the batch is ready.`
    );
  };

  const retryUploadItem = async (item: UploadFileState) => {
    updateUploadItem(item.id, { status: 'initializing', progress: 0, error: null });
    try {
      if (item.requiresLocalCopy) {
        await uploadExternalItemsSequentially([item], item.batch_id ?? activeBatchId, false);
        return;
      }

      const uploadInit = await operatorFetch<UploadInit>('/api/operator/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: item.filename,
          mimeType: item.mimeType,
          batch_id: item.batch_id ?? activeBatchId,
        }),
      });
      const session = uploadInit.uploads?.[0] ?? uploadInit;
      if (session.batch_id) setActiveBatchId(session.batch_id);
      await uploadAssetToSession(item, session);
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Upload failed';
      updateUploadItem(item.id, { status: 'failed', error: message });
      handleOperatorError(e);
    }
  };

  const retryAllFailedUploads = async () => {
    const failedItems = uploadItems.filter((item) => item.status === 'failed');
    if (!failedItems.length) return;

    setRetryingFailedUploads(true);
    try {
      const externalItems = failedItems.filter((item) => item.requiresLocalCopy);
      const galleryItems = failedItems.filter((item) => !item.requiresLocalCopy);
      if (externalItems.length) {
        await uploadExternalItemsSequentially(externalItems, activeBatchId, false);
      }
      for (const item of galleryItems) {
        await retryUploadItem(item);
      }
    } finally {
      setRetryingFailedUploads(false);
    }
  };

  const uploadSelectedItems = async (items: UploadFileState[]) => {
    if (items.length > MAX_UPLOAD_BATCH_FILES) {
      Alert.alert('Too many videos', `Select at most ${MAX_UPLOAD_BATCH_FILES} videos for one batch.`);
      return;
    }

    setUploadItems(items);
    if (items.some((item) => item.requiresLocalCopy)) {
      await uploadExternalItemsSequentially(items, activeBatchId, true);
      return;
    }

    try {
      setUploadItems((current) => current.map((item) => ({ ...item, status: 'initializing' })));
      const uploadInit = await operatorFetch<UploadInit>(
        '/api/operator/upload',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            files: items.map((item) => ({ filename: item.filename, mimeType: item.mimeType })),
            batch_id: activeBatchId,
          }),
        }
      );
      const sessions = uploadInit.uploads?.length ? uploadInit.uploads : [uploadInit];
      const batchId = uploadInit.batch_id ?? sessions[0]?.batch_id ?? activeBatchId;
      if (batchId) setActiveBatchId(batchId);

      const results: PromiseSettledResult<void>[] = new Array(items.length);
      let nextIndex = 0;
      const concurrencyLimit = UPLOAD_CONCURRENCY_LIMIT;
      const workerCount = Math.min(concurrencyLimit, items.length);
      await Promise.all(
        Array.from({ length: workerCount }, async () => {
          while (nextIndex < items.length) {
            const index = nextIndex;
            nextIndex += 1;
            const item = items[index];
            const session = sessions[index];
            try {
              if (!item) continue;
              if (!session) throw new Error(`Missing upload session for ${item.filename}`);
              await uploadAssetToSession(item, session);
              results[index] = { status: 'fulfilled', value: undefined };
            } catch (reason) {
              results[index] = { status: 'rejected', reason };
            }
          }
        })
      );

      const failed = results.filter((uploadResult) => uploadResult.status === 'rejected');
      if (failed.length) {
        results.forEach((uploadResult, index) => {
          if (uploadResult.status === 'rejected') {
            updateUploadItem(items[index].id, {
              status: 'failed',
              error: uploadResult.reason instanceof Error ? uploadResult.reason.message : 'Upload failed',
            });
          }
        });
        Alert.alert('Some uploads failed', `${failed.length} of ${items.length} files failed. Use Retry all failed before running the pipeline.`);
        return;
      }

      Alert.alert(
        'Uploaded to queue',
        `${items.length} file${items.length === 1 ? '' : 's'} verified in RAW batch ${batchId?.slice(0, 16) ?? 'current'}. Upload more footage for this athlete/session, then tap Run pipeline now when the batch is ready.`
      );
    } catch (e) {
      setUploadItems((current) => current.map((item) => ({ ...item, status: 'failed', error: e instanceof Error ? e.message : 'Upload failed' })));
      handleOperatorError(e);
    }
  };

'''
text = text[:start] + replacement + text[end:]

text = text.replace(
    "  const uploadBusy = uploadItems.some((item) => ['queued', 'initializing', 'uploading'].includes(item.status));\n  const verifiedUploads = uploadItems.filter((item) => item.status === 'verified').length;\n  const busy = triggering || resetting || selectingExternalStorage || uploadBusy;",
    "  const uploadBusy = uploadItems.some((item) => ['queued', 'initializing', 'uploading'].includes(item.status));\n  const failedUploads = uploadItems.filter((item) => item.status === 'failed');\n  const verifiedUploads = uploadItems.filter((item) => item.status === 'verified').length;\n  const pipelineBlockedByUploads = uploadItems.length > 0 && verifiedUploads !== uploadItems.length;\n  const busy = triggering || resetting || selectingExternalStorage || retryingFailedUploads || uploadBusy;",
    1,
)
text = text.replace(
    '<Button label={triggering ? \'Triggering...\' : \'Run pipeline now\'} onPress={runPipeline} disabled={busy} variant="secondary" style={{ height: 44 }} />',
    '<Button label={triggering ? \'Triggering...\' : \'Run pipeline now\'} onPress={runPipeline} disabled={busy || pipelineBlockedByUploads} variant="secondary" style={{ height: 44 }} />',
    1,
)
text = text.replace(
    "                <Text variant=\"caption\" color={Colors.textSecondary}>Upload batch progress</Text>\n                {uploadItems.map((item) => (",
    "                <View style={styles.metaRow}>\n                  <Text variant=\"caption\" color={failedUploads.length ? Colors.danger : Colors.textSecondary}>\n                    Upload batch progress · {verifiedUploads}/{uploadItems.length} verified\n                  </Text>\n                  {failedUploads.length > 0 && (\n                    <Button\n                      label={retryingFailedUploads ? 'Retrying...' : `Retry all failed (${failedUploads.length})`}\n                      onPress={retryAllFailedUploads}\n                      disabled={busy}\n                      variant=\"ghost\"\n                      style={{ height: 36 }}\n                    />\n                  )}\n                </View>\n                {pipelineBlockedByUploads && (\n                  <Text variant=\"caption\" color={Colors.danger}>\n                    Pipeline start is blocked until every selected upload is verified.\n                  </Text>\n                )}\n                {uploadItems.map((item) => (",
    1,
)
PIPELINE.write_text(text, encoding='utf-8')


ROUTE = Path('web-api/src/app/api/operator/upload/route.ts')
route = ROUTE.read_text(encoding='utf-8')
route = route.replace(
    "type UploadFileInput = {\n  filename?: string;\n  mimeType?: string;\n};",
    "type UploadFileInput = {\n  filename?: string;\n  mimeType?: string;\n  client_upload_id?: string;\n};",
    1,
)
route = route.replace(
    "  files?: UploadFileInput[];\n};",
    "  files?: UploadFileInput[];\n  upload_mode?: 'resilient_batch_item';\n  client_upload_id?: string;\n};",
    1,
)
route = route.replace(
    "  mimeType: string;\n};",
    "  mimeType: string;\n  clientUploadId?: string;\n};",
    1,
)
route = route.replace(
    "      ? [{ filename: body.filename, mimeType: body.mimeType }]",
    "      ? [{ filename: body.filename, mimeType: body.mimeType, client_upload_id: body.client_upload_id }]",
    1,
)
route = route.replace(
    "      mimeType: (file.mimeType ?? '').trim() || 'video/mp4',\n    };",
    "      mimeType: (file.mimeType ?? '').trim() || 'video/mp4',\n      clientUploadId: (file.client_upload_id ?? '').trim() || undefined,\n    };",
    1,
)
route = route.replace(
    "  const limited = await enforceRateLimit(\n    req,\n    files.length > 1 ? 'operator-upload-batch' : 'operator-upload',\n    files.length > 1 ? 20 : 10,\n    3600,\n  );",
    "  const resilientBatchItem = body.upload_mode === 'resilient_batch_item' && files.length === 1;\n  const limited = await enforceRateLimit(\n    req,\n    resilientBatchItem ? 'operator-upload-resilient-batch-item' : files.length > 1 ? 'operator-upload-batch' : 'operator-upload',\n    resilientBatchItem ? 120 : files.length > 1 ? 20 : 10,\n    3600,\n  );",
    1,
)
route = route.replace(
    "const upload = createR2UploadUrl(file.uploadFilename, batchId);",
    "const upload = createR2UploadUrl(file.uploadFilename, batchId, file.clientUploadId);",
    1,
)
ROUTE.write_text(route, encoding='utf-8')


R2 = Path('web-api/src/lib/r2-storage.ts')
r2 = R2.read_text(encoding='utf-8')
r2 = r2.replace(
    "export const safeBatchId = (batchId?: string | null) => (batchId ?? '').replace(/[^A-Za-z0-9_-]/g, '_').replace(/^_+|_+$/g, '').slice(0, 80);",
    "export const safeBatchId = (batchId?: string | null) => (batchId ?? '').replace(/[^A-Za-z0-9_-]/g, '_').replace(/^_+|_+$/g, '').slice(0, 80);\nconst safeUploadId = (uploadId?: string | null) => (uploadId ?? '').replace(/[^A-Za-z0-9_-]/g, '_').replace(/^_+|_+$/g, '').slice(0, 96);",
    1,
)
r2 = r2.replace(
    "export function createR2UploadUrl(filename: string, requestedBatchId?: string | null): { uploadUrl: string; key: string; filename: string; batch_id: string } {\n  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);\n  const batchId = safeBatchId(requestedBatchId) || newBatchId();\n  const storageName = `${stamp}_${safeFilename(filename)}`;",
    "export function createR2UploadUrl(filename: string, requestedBatchId?: string | null, clientUploadId?: string | null): { uploadUrl: string; key: string; filename: string; batch_id: string } {\n  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);\n  const batchId = safeBatchId(requestedBatchId) || newBatchId();\n  const stableUploadId = safeUploadId(clientUploadId);\n  const storageName = stableUploadId ? `${stableUploadId}_${safeFilename(filename)}` : `${stamp}_${safeFilename(filename)}`;",
    1,
)
R2.write_text(r2, encoding='utf-8')


WORKFLOW = Path('.github/workflows/operator-smoke-check.yml')
workflow = WORKFLOW.read_text(encoding='utf-8')
workflow = workflow.replace(
    "'createR2UploadUrl(file.uploadFilename, batchId)',",
    "'createR2UploadUrl(file.uploadFilename, batchId, file.clientUploadId)',",
    1,
)
WORKFLOW.write_text(workflow, encoding='utf-8')


contract = Path('scripts/test_resilient_upload_contract.py')
contract.write_text(r'''from pathlib import Path

pipeline = Path('mobile/src/app/(operator)/pipeline.tsx').read_text(encoding='utf-8')
route = Path('web-api/src/app/api/operator/upload/route.ts').read_text(encoding='utf-8')
r2 = Path('web-api/src/lib/r2-storage.ts').read_text(encoding='utf-8')

required_pipeline = [
    'MAX_UPLOAD_ATTEMPTS = 3',
    'initializeResilientUploadSession',
    "upload_mode: 'resilient_batch_item'",
    'client_upload_id: item.id',
    'uploadExternalItemWithRetries',
    'FileSystem.copyAsync({ from: item.uri, to: temporaryUploadUri })',
    'for (let attempt = 1; attempt <= MAX_UPLOAD_ATTEMPTS; attempt += 1)',
    'Retry all failed (',
    'pipelineBlockedByUploads',
    'Pipeline start is blocked until every selected upload is verified.',
]
missing = [token for token in required_pipeline if token not in pipeline]
if missing:
    raise SystemExit(f'resilient mobile upload contract missing: {missing}')

copy_index = pipeline.index('await FileSystem.copyAsync({ from: item.uri, to: temporaryUploadUri })', pipeline.index('uploadExternalItemWithRetries'))
loop_index = pipeline.index('for (let attempt = 1; attempt <= MAX_UPLOAD_ATTEMPTS; attempt += 1)', copy_index)
delete_index = pipeline.index('await FileSystem.deleteAsync(temporaryUploadUri, { idempotent: true })', loop_index)
if not copy_index < loop_index < delete_index:
    raise SystemExit('external source must be copied once, retried using that cache file, then cleaned')

required_route = [
    "upload_mode?: 'resilient_batch_item'",
    'client_upload_id?: string',
    "'operator-upload-resilient-batch-item'",
    'resilientBatchItem ? 120',
    'createR2UploadUrl(file.uploadFilename, batchId, file.clientUploadId)',
]
missing = [token for token in required_route if token not in route]
if missing:
    raise SystemExit(f'resilient upload route contract missing: {missing}')

required_r2 = [
    'safeUploadId',
    'clientUploadId?: string | null',
    'const stableUploadId = safeUploadId(clientUploadId)',
    'stableUploadId ? `${stableUploadId}_${safeFilename(filename)}`',
]
missing = [token for token in required_r2 if token not in r2]
if missing:
    raise SystemExit(f'idempotent R2 key contract missing: {missing}')

print('Resilient R2 upload retry contract checks passed')
''', encoding='utf-8')


check = Path('.github/workflows/resilient-upload-check.yml')
check.write_text("""name: Resilient Upload Check

on:
  pull_request:
    paths:
      - 'mobile/src/app/(operator)/pipeline.tsx'
      - 'web-api/src/app/api/operator/upload/route.ts'
      - 'web-api/src/lib/r2-storage.ts'
      - 'scripts/test_resilient_upload_contract.py'
      - '.github/workflows/resilient-upload-check.yml'

jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: python scripts/test_resilient_upload_contract.py
""", encoding='utf-8')


audit = Path('docs/audit/resilient-r2-upload-retry-plan.md')
audit.write_text("""# Resilient R2 upload retry plan

Date: 2026-07-20
Status: implementation prepared; CI, review, merge, EAS publication, and physical retest pending.

## Physical finding

During a real 20-file Android SD-card upload, 19 files failed. Most errors were DNS failures resolving the Cloudflare R2 host; one upload reached 63% and timed out after 60 seconds. The pipeline was not run.

## Required behavior

- [x] Copy each external-storage source into app cache once per manual upload action.
- [x] Request a fresh presigned URL immediately before each file attempt.
- [x] Retry each failed transfer automatically up to three times with delays.
- [x] Reuse a stable client upload ID so retries overwrite the same R2 object instead of creating duplicates.
- [x] Keep one external file active at a time.
- [x] Add one-tap **Retry all failed** after connectivity is restored.
- [x] Keep individual Retry controls.
- [x] Block pipeline start while any selected upload is unverified.
- [x] Preserve the 20-video batch selection limit.
- [x] Add deterministic mobile/API/R2 contract coverage.
- [ ] Mobile and Web API type-checks pass.
- [ ] Operator Smoke and Resilient Upload checks pass.
- [ ] PR review has no unresolved findings.
- [ ] Merge and EAS publication complete.
- [ ] Physical retest proves recovery from a temporary network interruption without duplicate R2 objects.

## Safety

This change never starts the pipeline automatically. The user must still explicitly start a run after all selected files show Verified at 100% and after the human ground-truth list is recorded.
""", encoding='utf-8')
