#!/usr/bin/env python3
from pathlib import Path

path = Path('scripts/apply_final_upload_review_fixes.py')
text = path.read_text(encoding='utf-8')

replacements = [
    (
        """  storage_key?: string;
  client_upload_id?: string;
  upload_status?: string;
""",
        """  storage_key?: string;
  upload_id?: string;
  client_upload_id?: string;
  upload_status?: string;
""",
        'web response upload id',
    ),
    (
        """        assertSinglePutSourceMatches({ session, file, batchId: resolved.batchId });
        try {
""",
        """        if (!session) {
          throw new SourceUploadManifestError('Single-PUT upload session could not be created or recovered', 503);
        }
        assertSinglePutSourceMatches({ session, file, batchId: resolved.batchId });
        try {
""",
        'explicit single-PUT session guard',
    ),
    (
        "sourceUploadSession(data as SourceUploadRow)",
        "sourceUploadSession(data as unknown as SourceUploadRow)",
        'Supabase row cast',
    ),
    (
        """        \"client_upload_id\",
        \"createSinglePutSourceManifest\",
        \"sourceSizeBytes: file.sourceSizeBytes\",
        \"upload_id: session.uploadId\",
""",
        """        \"client_upload_id\",
        \"createSinglePutSourceManifest\",
        \"sourceSizeBytes: file.sourceSizeBytes as number\",
        \"upload_id: session.uploadId\",
""",
        'exact-source narrowed size contract',
    ),
]

for old, new, label in replacements:
    count = text.count(old)
    if count < 1:
        raise SystemExit(f'{label}: expected at least one match, found {count}')
    text = text.replace(old, new)

path.write_text(text, encoding='utf-8')
print('Final upload patch type corrections applied')
