from pathlib import Path

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
    'function newClientBatchId()',
    'const batchIdForAllAttempts = startingBatchId ?? newClientBatchId()',
    'if (!startingBatchId) setActiveBatchId(batchIdForAllAttempts)',
    "'Resolve current uploads'",
    "uploadItems.some((item) => item.status !== 'verified')",
]
missing = [token for token in required_pipeline if token not in pipeline]
if missing:
    raise SystemExit(f'resilient mobile upload contract missing: {missing}')

copy_index = pipeline.index(
    'await FileSystem.copyAsync({ from: item.uri, to: temporaryUploadUri })',
    pipeline.index('uploadExternalItemWithRetries'),
)
loop_index = pipeline.index(
    'for (let attempt = 1; attempt <= MAX_UPLOAD_ATTEMPTS; attempt += 1)',
    copy_index,
)
delete_index = pipeline.index(
    'await FileSystem.deleteAsync(temporaryUploadUri, { idempotent: true })',
    loop_index,
)
if not copy_index < loop_index < delete_index:
    raise SystemExit('external source must be copied once, retried using that cache file, then cleaned')

batch_helper_index = pipeline.index('function newClientBatchId()')
sequential_index = pipeline.index('const uploadExternalItemsSequentially')
stable_batch_index = pipeline.index(
    'const batchIdForAllAttempts = startingBatchId ?? newClientBatchId()',
    sequential_index,
)
first_upload_index = pipeline.index(
    'batchId = await uploadExternalItemWithRetries(item, batchId)',
    stable_batch_index,
)
if not batch_helper_index < sequential_index < stable_batch_index < first_upload_index:
    raise SystemExit('client batch ID must be generated before the first initialization attempt')

selected_items_index = pipeline.index('const uploadSelectedItems')
replace_items_index = pipeline.index('setUploadItems(items)', selected_items_index)
unresolved_guard_index = pipeline.index(
    "uploadItems.some((item) => item.status !== 'verified')",
    selected_items_index,
)
if not unresolved_guard_index < replace_items_index:
    raise SystemExit('unresolved uploads must block replacement before new upload state is installed')

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
