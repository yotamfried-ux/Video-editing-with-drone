from pathlib import Path


pipeline_screen = Path('mobile/src/app/(operator)/pipeline.tsx').read_text(encoding='utf-8')
package_json = Path('mobile/package.json').read_text(encoding='utf-8')

required_tokens = [
    'StorageAccessFramework.requestDirectoryPermissionsAsync',
    'StorageAccessFramework.readDirectoryAsync',
    'requiresLocalCopy: true',
    'FileSystem.copyAsync({ from: item.uri, to: temporaryUploadUri })',
    'FileSystem.deleteAsync(temporaryUploadUri, { idempotent: true })',
    'EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT = 1',
    "Upload from SD / USB folder",
    "Upload from gallery",
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

copy_index = pipeline_screen.index('FileSystem.copyAsync({ from: item.uri, to: temporaryUploadUri })')
upload_index = pipeline_screen.index('FileSystem.createUploadTask(', copy_index)
delete_index = pipeline_screen.index('FileSystem.deleteAsync(temporaryUploadUri', upload_index)
if not copy_index < upload_index < delete_index:
    raise SystemExit('external storage files must be copied before upload and cleaned after upload')

print('External SD / USB upload contract checks passed')
