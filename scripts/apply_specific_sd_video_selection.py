from pathlib import Path


pipeline_path = Path('mobile/src/app/(operator)/pipeline.tsx')
text = pipeline_path.read_text(encoding='utf-8')

text = text.replace(
    "import { View, StyleSheet, ScrollView, Alert, Platform } from 'react-native';",
    "import { View, StyleSheet, ScrollView, Alert, Platform, Pressable } from 'react-native';",
    1,
)

upload_type_marker = """type UploadFileState = {
  id: string;
  uri: string;
  filename: string;
  mimeType: string;
  progress: number;
  status: UploadItemStatus;
  batch_id?: string | null;
  error?: string | null;
  requiresLocalCopy?: boolean;
};
"""
upload_type_replacement = upload_type_marker + """
type ExternalVideoCandidate = {
  id: string;
  uri: string;
  filename: string;
  mimeType: string;
  selected: boolean;
};
"""
if upload_type_marker not in text:
    raise SystemExit('UploadFileState marker not found')
text = text.replace(upload_type_marker, upload_type_replacement, 1)

state_marker = """  const [selectingExternalStorage, setSelectingExternalStorage] = useState(false);
  const [uploadItems, setUploadItems] = useState<UploadFileState[]>([]);
"""
state_replacement = """  const [selectingExternalStorage, setSelectingExternalStorage] = useState(false);
  const [externalCandidates, setExternalCandidates] = useState<ExternalVideoCandidate[]>([]);
  const [uploadItems, setUploadItems] = useState<UploadFileState[]>([]);
"""
if state_marker not in text:
    raise SystemExit('external storage state marker not found')
text = text.replace(state_marker, state_replacement, 1)

folder_function_start = text.index('  const uploadExternalStorageFolder = async () => {')
folder_function_end = text.index('\n  const uploadBusy =', folder_function_start)
new_folder_flow = """  const toggleExternalCandidate = (id: string) => {
    setExternalCandidates((candidates) =>
      candidates.map((candidate) =>
        candidate.id === id ? { ...candidate, selected: !candidate.selected } : candidate
      )
    );
  };

  const uploadSelectedExternalVideos = async () => {
    const selectedCandidates = externalCandidates.filter((candidate) => candidate.selected);
    if (!selectedCandidates.length) {
      Alert.alert('Select videos', 'Choose at least one video from the folder before uploading.');
      return;
    }

    const items: UploadFileState[] = selectedCandidates.map((candidate, index) => ({
      id: `${Date.now()}_external_${index}_${candidate.filename}`,
      uri: candidate.uri,
      filename: candidate.filename,
      mimeType: candidate.mimeType,
      progress: 0,
      status: 'queued',
      batch_id: activeBatchId,
      error: null,
      requiresLocalCopy: true,
    }));

    setExternalCandidates([]);
    await uploadSelectedItems(items);
  };

  const uploadExternalStorageFolder = async () => {
    if (Platform.OS !== 'android') {
      Alert.alert('Android only', 'Direct SD / USB video selection is currently available on Android.');
      return;
    }

    setSelectingExternalStorage(true);
    try {
      const permission = await FileSystem.StorageAccessFramework.requestDirectoryPermissionsAsync();
      if (!permission.granted) return;

      const documentUris = await FileSystem.StorageAccessFramework.readDirectoryAsync(permission.directoryUri);
      const videoDocuments = documentUris
        .map((uri, index) => ({ uri, filename: filenameFromDocumentUri(uri, index) }))
        .filter((document) => isSupportedVideoFilename(document.filename))
        .sort((left, right) => left.filename.localeCompare(right.filename));

      if (!videoDocuments.length) {
        setExternalCandidates([]);
        Alert.alert(
          'No videos found',
          'Choose the SD / USB folder that directly contains the video clips, then try again.'
        );
        return;
      }

      setExternalCandidates(
        videoDocuments.map((document, index) => ({
          id: `${permission.directoryUri}_${index}_${document.filename}`,
          uri: document.uri,
          filename: document.filename,
          mimeType: mimeTypeForFilename(document.filename),
          selected: false,
        }))
      );
    } catch (e) {
      handleOperatorError(e);
    } finally {
      setSelectingExternalStorage(false);
    }
  };
"""
text = text[:folder_function_start] + new_folder_flow + text[folder_function_end:]

old_external_ui = """            {Platform.OS === 'android' && (
              <>
                <Button
                  label={selectingExternalStorage ? 'Opening SD / USB...' : 'Upload from SD / USB folder'}
                  onPress={uploadExternalStorageFolder}
                  disabled={busy}
                  variant="secondary"
                  style={{ height: 44 }}
                />
                <Text variant="caption" color={Colors.textSecondary}>
                  Select the folder on the connected card or USB drive that directly contains the video clips.
                </Text>
              </>
            )}
"""
new_external_ui = """            {Platform.OS === 'android' && (
              <>
                <Button
                  label={selectingExternalStorage ? 'Opening SD / USB...' : 'Choose videos from SD / USB'}
                  onPress={uploadExternalStorageFolder}
                  disabled={busy}
                  variant="secondary"
                  style={{ height: 44 }}
                />
                <Text variant="caption" color={Colors.textSecondary}>
                  First choose the folder on the card or USB drive. Then select only the videos you want to upload.
                </Text>
                {externalCandidates.length > 0 && (
                  <View style={styles.externalSelectionPanel}>
                    <View style={styles.metaRow}>
                      <Text variant="caption" color={Colors.textPrimary}>
                        Select videos · {externalCandidates.filter((candidate) => candidate.selected).length}/{externalCandidates.length}
                      </Text>
                      <Button
                        label="Clear"
                        onPress={() => setExternalCandidates((candidates) => candidates.map((candidate) => ({ ...candidate, selected: false })))}
                        disabled={busy}
                        variant="ghost"
                        style={{ height: 34 }}
                      />
                    </View>
                    <Button
                      label="Select all"
                      onPress={() => setExternalCandidates((candidates) => candidates.map((candidate) => ({ ...candidate, selected: true })))}
                      disabled={busy}
                      variant="ghost"
                      style={{ height: 36 }}
                    />
                    {externalCandidates.map((candidate) => (
                      <Pressable
                        key={candidate.id}
                        onPress={() => toggleExternalCandidate(candidate.id)}
                        disabled={busy}
                        accessibilityRole="checkbox"
                        accessibilityState={{ checked: candidate.selected, disabled: busy }}
                        style={({ pressed }) => [
                          styles.externalSelectionRow,
                          candidate.selected && styles.externalSelectionRowSelected,
                          pressed && !busy && { opacity: 0.75 },
                        ]}
                      >
                        <View style={[styles.selectionIndicator, candidate.selected && styles.selectionIndicatorSelected]}>
                          <Text variant="caption" color={candidate.selected ? Colors.background : Colors.textSecondary}>
                            {candidate.selected ? '✓' : ''}
                          </Text>
                        </View>
                        <Text variant="caption" color={Colors.textPrimary} numberOfLines={2} style={{ flex: 1 }}>
                          {candidate.filename}
                        </Text>
                      </Pressable>
                    ))}
                    <Button
                      label={`Upload selected (${externalCandidates.filter((candidate) => candidate.selected).length})`}
                      onPress={uploadSelectedExternalVideos}
                      disabled={busy || !externalCandidates.some((candidate) => candidate.selected)}
                      variant="secondary"
                      style={{ height: 44 }}
                    />
                  </View>
                )}
              </>
            )}
"""
if old_external_ui not in text:
    raise SystemExit('external storage UI marker not found')
text = text.replace(old_external_ui, new_external_ui, 1)

styles_marker = """  uploadRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    borderRadius: 8,
    padding: Spacing.sm,
  },
"""
styles_replacement = styles_marker + """  externalSelectionPanel: {
    gap: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    borderRadius: 8,
    padding: Spacing.sm,
  },
  externalSelectionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    borderRadius: 8,
    padding: Spacing.sm,
  },
  externalSelectionRowSelected: {
    borderColor: Colors.accent,
  },
  selectionIndicator: {
    width: 24,
    height: 24,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    alignItems: 'center',
    justifyContent: 'center',
  },
  selectionIndicatorSelected: {
    backgroundColor: Colors.accent,
    borderColor: Colors.accent,
  },
"""
if styles_marker not in text:
    raise SystemExit('upload styles marker not found')
text = text.replace(styles_marker, styles_replacement, 1)
pipeline_path.write_text(text, encoding='utf-8')

contract_path = Path('scripts/test_external_storage_upload_contract.py')
contract_path.write_text("""from pathlib import Path


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
""", encoding='utf-8')

existing_audit = Path('docs/audit/direct-sd-usb-upload-plan.md')
audit_text = existing_audit.read_text(encoding='utf-8')
audit_text = audit_text.replace(
    'Status: implementation, targeted contract, mobile type-check, operator smoke validation, and fallback self-review complete; merge, deployment, and physical-device validation pending.',
    'Status: folder-level upload was merged and published; physical testing exposed that it uploaded every video in the chosen folder. A follow-up PR adds individual video selection before upload.',
    1,
)
audit_text += """

## Physical-test finding — 2026-07-19

The Android Storage Access Framework screen intentionally grants access to a folder; it does not select individual files. The first implementation immediately uploaded every supported video in that folder. The user's real card-reader test proved this behavior was not sufficient.

Follow-up implementation:

- [x] Keep the folder permission step so the app can access connected SD / USB storage without a new native dependency.
- [x] Stage the videos found in that folder instead of uploading immediately.
- [x] Show an in-app checkbox list with Select all, Clear, and Upload selected controls.
- [x] Preserve the existing sequential external-file cache copy, R2 verification, progress, retry, and manual pipeline-start behavior.
- [ ] Follow-up CI is green.
- [ ] Follow-up PR is merged and published through EAS Update.
- [ ] Physical retest proves only checked videos are uploaded.
"""
existing_audit.write_text(audit_text, encoding='utf-8')

followup_audit = Path('docs/audit/specific-sd-video-selection-plan.md')
followup_audit.write_text("""# Specific SD / USB video selection — follow-up plan

Date: 2026-07-19
Status: implementation prepared; CI, review, merge, EAS publication, and physical retest pending.

## Observed problem

A real Android test with a connected DJI SD card reached the correct external folder, but the system control only offered **Use this folder**. The app then uploaded all supported videos from that folder, so the operator could not choose specific clips.

## Root cause

`StorageAccessFramework.requestDirectoryPermissionsAsync()` grants directory access. The first implementation enumerated the directory and immediately passed the complete list to `uploadSelectedItems()`.

## Required behavior

1. Choose the folder on SD / USB storage.
2. Display only supported videos found directly in that folder.
3. Let the operator check one or more individual videos.
4. Upload only checked videos into the current RAW batch.
5. Keep pipeline execution manual.

## Validation checklist

- [x] Folder selection no longer starts an upload.
- [x] Individual video rows expose checkbox accessibility state.
- [x] Select all and Clear controls are available.
- [x] Upload selected is disabled when zero files are checked.
- [x] Only checked candidates are converted into upload items.
- [x] Existing temporary-copy cleanup and R2 verification remain in place.
- [x] No new native dependency is introduced, so the fix remains eligible for EAS Update.
- [ ] External Storage Upload Check passes.
- [ ] Mobile Check passes.
- [ ] Operator Smoke Check passes.
- [ ] PR review is complete with no unresolved findings.
- [ ] Merge and EAS publication complete.
- [ ] Physical retest confirms unselected videos are not uploaded.
""", encoding='utf-8')

matrix_path = Path('docs/pipeline-gap-status-matrix-20260705.md')
matrix = matrix_path.read_text(encoding='utf-8')
old_fragment = '| REAL-UPLOAD-002 | Operator can upload videos directly from a connected SD card or USB storage without importing them into the media gallery first. | PR #183 adds an Android Storage Access Framework folder picker, filters supported video files, copies one selected source at a time into app cache immediately before the existing verified R2 upload, preserves shared batch/progress/retry behavior, and removes the temporary cache copy in a `finally` block. The dedicated External Storage Upload Check passes; physical-device validation remains pending. | #183 pending merge | Implementation + targeted contract; physical-device validation pending | Pending real-run validation | After final CI and merge, deploy the mobile JavaScript update and validate folder selection plus verified upload with a real Android phone, card reader, and SD card before starting the pipeline. |'
new_fragment = '| REAL-UPLOAD-002 | Operator can upload specific videos directly from a connected SD card or USB storage without importing them into the media gallery first. | #183 added Android folder access and verified R2 upload, but the first physical test showed that choosing a folder uploaded every supported video. A follow-up PR stages discovered videos in an in-app checkbox list and uploads only checked items while preserving sequential cache-copy cleanup, shared batch/progress/retry, and manual pipeline start. | #183 merged; follow-up PR pending | #183 contract + physical finding; follow-up implementation pending CI | Partial | Complete follow-up CI/review/merge/EAS publication, then physically prove selected files upload and unselected files do not. |'
if old_fragment not in matrix:
    raise SystemExit('REAL-UPLOAD-002 matrix row marker not found')
matrix = matrix.replace(old_fragment, new_fragment, 1)
matrix_path.write_text(matrix, encoding='utf-8')
