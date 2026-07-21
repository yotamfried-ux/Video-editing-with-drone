from pathlib import Path


pipeline_screen = Path('mobile/src/app/(operator)/pipeline.tsx').read_text(encoding='utf-8')
multipart_mobile = Path('mobile/src/features/operator/lib/resumableMultipartUpload.ts').read_text(encoding='utf-8')
package_json = Path('mobile/package.json').read_text(encoding='utf-8')

required_pipeline_tokens = [
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
    'externalSource: true',
    'const prepareLegacyUpload',
    'await FileSystem.copyAsync({ from: item.uri, to: temporaryUri })',
    'await FileSystem.deleteAsync(temporaryUri, { idempotent: true })',
    "session.storage_backend === 'r2' && session.upload_mode === 'multipart_resumable'",
    'resumeMultipartUpload({',
    'sourceUri: item.uri',
    'externalSource: Boolean(item.externalSource)',
    'EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT = 1',
    'Choose videos from SD / USB',
    'Upload from gallery',
    'await uploadSelectedItems(items)',
    'abortPersistedMultipartUpload',
    'Discard interrupted upload?',
    'Resume',
]
missing = [token for token in required_pipeline_tokens if token not in pipeline_screen]
if missing:
    raise SystemExit(f'external storage upload contract missing: {missing}')

required_multipart_tokens = [
    'FileSystem.readAsStringAsync(sourceUri',
    'FileSystem.EncodingType.Base64',
    'position: offset',
    'length,',
    'const bytes = decode(encoded)',
    'bytes.byteLength',
    'PART_UPLOAD_ATTEMPTS = 3',
    'await saveRecord(record)',
    'loadActiveMultipartBatch',
    'abortPersistedMultipartUpload',
]
missing = [token for token in required_multipart_tokens if token not in multipart_mobile]
if missing:
    raise SystemExit(f'external multipart reader contract missing: {missing}')

forbidden_global_tokens = [
    "import * as DocumentPicker from 'expo-document-picker'",
    'expo-document-picker',
]
present = [token for token in forbidden_global_tokens if token in pipeline_screen or token in package_json]
if present:
    raise SystemExit(f'external storage upload unexpectedly contains unsafe/deprecated flow: {present}')

forbidden_multipart_tokens = [
    'FileSystem.copyAsync',
    'FileSystem.createUploadTask',
    '.slice(',
]
present = [token for token in forbidden_multipart_tokens if token in multipart_mobile]
if present:
    raise SystemExit(f'multipart SD / USB path must not copy or materialize the whole video: {present}')

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
for token in ['candidate.selected', 'externalSource: true', 'await uploadSelectedItems(items)']:
    if token not in selected_block:
        raise SystemExit(f'selected external upload block missing: {token}')

upload_start = pipeline_screen.index('const uploadItemWithRetries')
upload_end = pipeline_screen.index('const runUploadQueue', upload_start)
upload_block = pipeline_screen[upload_start:upload_end]
branch_index = upload_block.index("session.storage_backend === 'r2' && session.upload_mode === 'multipart_resumable'")
resume_index = upload_block.index('await resumeMultipartUpload({', branch_index)
legacy_prepare_index = upload_block.index('await prepareLegacyUpload(item)', resume_index)
legacy_upload_index = upload_block.index('await uploadLegacyPreparedFile', legacy_prepare_index)
if not branch_index < resume_index < legacy_prepare_index < legacy_upload_index:
    raise SystemExit('R2 must stream parts directly; whole-file copy is allowed only in the legacy non-R2 fallback')

queue_start = pipeline_screen.index('const runUploadQueue')
queue_end = pipeline_screen.index('const retryUploadItem', queue_start)
queue_block = pipeline_screen[queue_start:queue_end]
for token in [
    'items.some((item) => item.externalSource)',
    'EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT',
    'runQueue(items, (item) => uploadItemWithRetries(item, stableBatchId), concurrency)',
]:
    if token not in queue_block:
        raise SystemExit(f'external queue safety missing: {token}')

print('Specific external SD / USB selection and direct persisted multipart resume checks passed')
