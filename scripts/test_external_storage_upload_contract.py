from pathlib import Path


pipeline_screen = Path('mobile/src/app/(operator)/pipeline.tsx').read_text(encoding='utf-8')
package_json = Path('mobile/package.json').read_text(encoding='utf-8')
client = Path('mobile/src/features/operator/lib/multipartUploadClient.ts').read_text(encoding='utf-8')
ledger = Path('mobile/src/features/operator/lib/multipartUploadLedger.ts').read_text(encoding='utf-8')
cleanup = Path('mobile/src/features/operator/lib/uploadLocalCleanup.ts').read_text(encoding='utf-8')
reader = Path(
    'mobile/modules/sportreel-source-reader/android/src/main/java/'
    'expo/modules/sportreelsourcereader/SportReelSourceReaderModule.kt'
).read_text(encoding='utf-8')

required_screen_tokens = [
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
    "uploadMode: 'multipart'",
    'uploadLargeExternalSource({',
    'sweepAbandonedUploadCache()',
    'EXTERNAL_STORAGE_UPLOAD_CONCURRENCY_LIMIT = 1',
    'Choose videos from SD / USB',
    'Upload from gallery',
    'await uploadSelectedItems(items)',
    'Retry',
    'without a full phone copy',
    'The original SD / USB files were preserved',
]
missing = [token for token in required_screen_tokens if token not in pipeline_screen]
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
for token in ['candidate.selected', "uploadMode: 'multipart'", 'await uploadSelectedItems(items)']:
    if token not in selected_block:
        raise SystemExit(f'selected external upload block missing: {token}')

if 'FileSystem.copyAsync({ from: item.uri' in pipeline_screen:
    raise SystemExit('SD / USB upload must not copy the complete source into phone cache')
if 'requiresLocalCopy: true' in pipeline_screen:
    raise SystemExit('legacy whole-file local-copy mode must not remain enabled for SD / USB')

required_client_tokens = [
    'findDurableMultipartUpload',
    'reconcileWithServer',
    'completed_parts',
    'reader.readRange',
    'MAX_PART_ATTEMPTS = 3',
    "'/api/operator/upload/multipart/part-url'",
    "'/api/operator/upload/multipart/record-part'",
    "'/api/operator/upload/multipart/complete'",
    "'/api/operator/upload/multipart/cleanup'",
    "response.headers.get('etag')",
    'cleanupVerifiedUploadArtifacts',
    'removeDurableMultipartUpload',
    'source_not_seekable',
]
missing_client = [token for token in required_client_tokens if token not in client]
if missing_client:
    raise SystemExit(f'resumable multipart client missing: {missing_client}')

required_ledger_tokens = [
    "sportreel:multipart-upload-ledger:v1",
    'uploadId: string',
    'completedParts: DurableMultipartPart[]',
    'AsyncStorage.setItem',
    'serializeMutation',
    'activeMultipartTemporaryUris',
]
missing_ledger = [token for token in required_ledger_tokens if token not in ledger]
if missing_ledger:
    raise SystemExit(f'durable multipart ledger missing: {missing_ledger}')

required_reader_tokens = [
    'MAX_RANGE_BYTES = 64 * 1024 * 1024',
    'ContentResolver.SCHEME_CONTENT',
    'Os.lseek',
    'channel.position(offset)',
    'ByteArray(length)',
    'source_not_seekable',
]
missing_reader = [token for token in required_reader_tokens if token not in reader]
if missing_reader:
    raise SystemExit(f'bounded Android source reader missing: {missing_reader}')

required_cleanup_tokens = [
    'SPORTREEL_UPLOAD_CACHE_PREFIX',
    'Refusing to delete non-SportReel upload artifact',
    'Refusing to delete the selected SD / USB source',
    'Temporary upload artifact still exists after deletion',
    'sweepStaleSportReelUploadArtifacts',
]
missing_cleanup = [token for token in required_cleanup_tokens if token not in cleanup]
if missing_cleanup:
    raise SystemExit(f'phone-storage cleanup contract missing: {missing_cleanup}')

print('Specific resumable external SD / USB video upload contract checks passed')
