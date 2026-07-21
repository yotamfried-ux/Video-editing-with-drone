from pathlib import Path


pipeline_screen = Path('mobile/src/app/(operator)/pipeline.tsx').read_text(encoding='utf-8')
package_json = Path('mobile/package.json').read_text(encoding='utf-8')

required_tokens = [
    'StorageAccessFramework.requestDirectoryPermissionsAsync',
    'StorageAccessFramework.readDirectoryAsync',
    'type ExternalVideoCandidate',
    'setExternalCandidates(',
    'selected: false',
    'toggleExternalCandidate',
    'externalCandidates.filter((candidate) => candidate.selected)',
    'accessibilityRole="checkbox"',
    'Select all',
    'Upload selected (',
    'requiresLocalCopy: true',
    'const prepareUpload',
    'await FileSystem.copyAsync({ from: item.uri, to: temporaryUri })',
    'await FileSystem.deleteAsync(temporaryUri, { idempotent: true })',
    'const uploadItemWithRetries',
    'let prepared: PreparedUpload | null = null',
    'prepared = await prepareUpload(item)',
    'await uploadPreparedFile(item, session, prepared!.uri)',
    'if (prepared) await prepared.cleanup()',
    "status: 'failed'",
    'EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT = 1',
    'Choose videos from SD / USB',
    'Upload from gallery',
    'await uploadSelectedItems(items)',
    'Retry',
]
missing = [token for token in required_tokens if token not in pipeline_screen]
if missing:
    raise SystemExit(f'external storage upload contract missing: {missing}')

forbidden_tokens = [
    "import * as DocumentPicker from 'expo-document-picker'",
    'expo-document-picker',
    'const prepared = await prepareUpload(item);\n    try {',
]
present = [token for token in forbidden_tokens if token in pipeline_screen or token in package_json]
if present:
    raise SystemExit(f'external storage upload unexpectedly contains unsafe/deprecated flow: {present}')

folder_start = pipeline_screen.index('const uploadExternalStorageFolder')
folder_end = pipeline_screen.index('const uploadBusy', folder_start)
folder_block = pipeline_screen[folder_start:folder_end]
if 'await uploadSelectedItems(items)' in folder_block:
    raise SystemExit('choosing an SD / USB folder must not immediately upload every video')
if 'setExternalCandidates(' not in folder_block:
    raise SystemExit('folder selection must stage videos for individual selection')

selected_start = pipeline_screen.index('const uploadSelectedExternalVideos')
selected_end = pipeline_screen.index('const uploadExternalStorageFolder', selected_start)
selected_block = pipeline_screen[selected_start:selected_end]
for token in ['candidate.selected', 'requiresLocalCopy: true', 'await uploadSelectedItems(items)']:
    if token not in selected_block:
        raise SystemExit(f'selected external upload block missing: {token}')

prepare_start = pipeline_screen.index('const prepareUpload')
prepare_end = pipeline_screen.index('const requestUploadSession', prepare_start)
prepare_block = pipeline_screen[prepare_start:prepare_end]
copy_index = prepare_block.index('await FileSystem.copyAsync({ from: item.uri, to: temporaryUri })')
delete_index = prepare_block.index('await FileSystem.deleteAsync(temporaryUri, { idempotent: true })')
if copy_index >= delete_index:
    raise SystemExit('external source must be copied before its cleanup callback is defined')

retry_start = pipeline_screen.index('const uploadItemWithRetries')
retry_end = pipeline_screen.index('const runUploadQueue', retry_start)
retry_block = pipeline_screen[retry_start:retry_end]
try_index = retry_block.index('try {')
prepare_call = retry_block.index('prepared = await prepareUpload(item)')
upload_call = retry_block.index('await uploadPreparedFile(item, session, prepared!.uri)')
catch_index = retry_block.index('catch (error)')
failed_state = retry_block.index("status: 'failed'", catch_index)
finally_index = retry_block.index('finally')
cleanup_call = retry_block.index('if (prepared) await prepared.cleanup()', finally_index)
if not try_index < prepare_call < upload_call < catch_index < failed_state < finally_index < cleanup_call:
    raise SystemExit('external preparation and upload must share one guarded failed/retry/cleanup lifecycle')

queue_start = pipeline_screen.index('const runUploadQueue')
queue_end = pipeline_screen.index('const retryUploadItem', queue_start)
queue_block = pipeline_screen[queue_start:queue_end]
for token in [
    'items.some((item) => item.requiresLocalCopy)',
    'EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT',
    'runQueue(items, (item) => uploadItemWithRetries(item, stableBatchId), concurrency)',
]:
    if token not in queue_block:
        raise SystemExit(f'external queue safety missing: {token}')

print('Specific external SD / USB video selection and guarded retry lifecycle checks passed')
