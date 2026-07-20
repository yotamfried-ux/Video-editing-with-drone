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
    'FileSystem.copyAsync({ from: item.uri, to: temporaryUploadUri })',
    'FileSystem.deleteAsync(temporaryUploadUri, { idempotent: true })',
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
]
present = [token for token in forbidden_tokens if token in pipeline_screen or token in package_json]
if present:
    raise SystemExit(f'external storage upload unexpectedly adds a native picker dependency: {present}')

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

copy_index = pipeline_screen.index('FileSystem.copyAsync({ from: item.uri, to: temporaryUploadUri })')
upload_index = pipeline_screen.index('FileSystem.createUploadTask(', copy_index)
delete_index = pipeline_screen.index('FileSystem.deleteAsync(temporaryUploadUri', upload_index)
if not copy_index < upload_index < delete_index:
    raise SystemExit('external storage files must be copied before upload and cleaned after upload')

print('Specific external SD / USB video selection contract checks passed')
