from pathlib import Path


pipeline_path = Path('mobile/src/app/(operator)/pipeline.tsx')
text = pipeline_path.read_text(encoding='utf-8')

wait_marker = """function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
"""
wait_replacement = wait_marker + """
function newClientBatchId(): string {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  return `batch_mobile_${stamp}_${Math.random().toString(36).slice(2, 8)}`;
}
"""
if wait_marker not in text:
    raise SystemExit('wait helper marker not found')
text = text.replace(wait_marker, wait_replacement, 1)

batch_marker = """  ) => {
    let batchId = startingBatchId;
    let failedCount = 0;

    for (const item of items) {
"""
batch_replacement = """  ) => {
    const batchIdForAllAttempts = startingBatchId ?? newClientBatchId();
    let batchId = batchIdForAllAttempts;
    let failedCount = 0;
    if (!startingBatchId) setActiveBatchId(batchIdForAllAttempts);

    for (const item of items) {
"""
if batch_marker not in text:
    raise SystemExit('sequential upload batch marker not found')
text = text.replace(batch_marker, batch_replacement, 1)

selected_external_marker = """  const uploadSelectedExternalVideos = async () => {
    const selectedCandidates = externalCandidates.filter((candidate) => candidate.selected);
    if (!selectedCandidates.length) {
      Alert.alert('Select videos', 'Choose at least one video from the folder before uploading.');
      return;
    }

    const items: UploadFileState[] = selectedCandidates.map((candidate, index) => ({
"""
selected_external_replacement = """  const uploadSelectedExternalVideos = async () => {
    const selectedCandidates = externalCandidates.filter((candidate) => candidate.selected);
    if (!selectedCandidates.length) {
      Alert.alert('Select videos', 'Choose at least one video from the folder before uploading.');
      return;
    }
    if (selectedCandidates.length > MAX_UPLOAD_BATCH_FILES) {
      Alert.alert('Too many videos', `Select at most ${MAX_UPLOAD_BATCH_FILES} videos for one batch.`);
      return;
    }
    if (uploadItems.some((item) => item.status !== 'verified')) {
      Alert.alert(
        'Resolve current uploads',
        'Retry or complete every failed upload before adding more footage to this batch.'
      );
      return;
    }

    const items: UploadFileState[] = selectedCandidates.map((candidate, index) => ({
"""
if selected_external_marker not in text:
    raise SystemExit('selected external upload marker not found')
text = text.replace(selected_external_marker, selected_external_replacement, 1)

selected_items_marker = """  const uploadSelectedItems = async (items: UploadFileState[]) => {
    if (items.length > MAX_UPLOAD_BATCH_FILES) {
      Alert.alert('Too many videos', `Select at most ${MAX_UPLOAD_BATCH_FILES} videos for one batch.`);
      return;
    }

    setUploadItems(items);
"""
selected_items_replacement = """  const uploadSelectedItems = async (items: UploadFileState[]) => {
    if (items.length > MAX_UPLOAD_BATCH_FILES) {
      Alert.alert('Too many videos', `Select at most ${MAX_UPLOAD_BATCH_FILES} videos for one batch.`);
      return;
    }
    if (uploadItems.some((item) => item.status !== 'verified')) {
      Alert.alert(
        'Resolve current uploads',
        'Retry or complete every failed upload before adding more footage to this batch.'
      );
      return;
    }

    setUploadItems(items);
"""
if selected_items_marker not in text:
    raise SystemExit('upload selected items marker not found')
text = text.replace(selected_items_marker, selected_items_replacement, 1)

retry_button_marker = """                        onPress={() => retryUploadItem(item)}
                        variant="ghost"
"""
retry_button_replacement = """                        onPress={() => retryUploadItem(item)}
                        disabled={busy}
                        variant="ghost"
"""
if retry_button_marker not in text:
    raise SystemExit('per-file retry button marker not found')
text = text.replace(retry_button_marker, retry_button_replacement, 1)

pipeline_path.write_text(text, encoding='utf-8')

contract_path = Path('scripts/test_resilient_upload_contract.py')
contract = contract_path.read_text(encoding='utf-8')
contract = contract.replace(
    "    'Pipeline start is blocked until every selected upload is verified.',\n",
    "    'Pipeline start is blocked until every selected upload is verified.',\n    'function newClientBatchId()',\n    'const batchIdForAllAttempts = startingBatchId ?? newClientBatchId()',\n    'if (!startingBatchId) setActiveBatchId(batchIdForAllAttempts)',\n    \"'Resolve current uploads'\",\n    'uploadItems.some((item) => item.status !== \'verified\')',\n",
    1,
)
contract += """

batch_helper_index = pipeline.index('function newClientBatchId()')
sequential_index = pipeline.index('const uploadExternalItemsSequentially')
stable_batch_index = pipeline.index('const batchIdForAllAttempts = startingBatchId ?? newClientBatchId()', sequential_index)
first_upload_index = pipeline.index('batchId = await uploadExternalItemWithRetries(item, batchId)', stable_batch_index)
if not batch_helper_index < sequential_index < stable_batch_index < first_upload_index:
    raise SystemExit('client batch ID must be generated before the first initialization attempt')

selected_items_index = pipeline.index('const uploadSelectedItems')
replace_items_index = pipeline.index('setUploadItems(items)', selected_items_index)
unresolved_guard_index = pipeline.index("uploadItems.some((item) => item.status !== 'verified')", selected_items_index)
if not unresolved_guard_index < replace_items_index:
    raise SystemExit('unresolved uploads must block replacement before new upload state is installed')
"""
contract_path.write_text(contract, encoding='utf-8')

audit_path = Path('docs/audit/resilient-r2-upload-retry-plan.md')
audit = audit_path.read_text(encoding='utf-8')
audit = audit.replace(
    'Status: implementation prepared; CI, review, merge, EAS publication, and physical retest pending.',
    'Status: implementation prepared; initial CI is green; two P1 review findings are addressed and final CI/review are pending.',
    1,
)
audit = audit.replace(
    '- [x] Reuse a stable client upload ID so retries overwrite the same R2 object instead of creating duplicates.\n',
    '- [x] Reuse a stable client upload ID so retries overwrite the same R2 object instead of creating duplicates.\n- [x] Generate and persist a client batch ID before the first initialization request, so a lost response cannot split retries across batches.\n- [x] Prevent a new selection from replacing unresolved failed items and accidentally unblocking the pipeline.\n',
    1,
)
audit = audit.replace(
    '- [ ] Mobile and Web API type-checks pass.\n- [ ] Operator Smoke and Resilient Upload checks pass.\n',
    '- [x] Initial Mobile and Web API type-checks passed.\n- [x] Initial Operator Smoke, External Storage Upload, and Resilient Upload checks passed.\n- [ ] Final checks pass after the P1 review fixes.\n',
    1,
)
audit_path.write_text(audit, encoding='utf-8')
