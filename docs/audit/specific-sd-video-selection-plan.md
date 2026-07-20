# Specific SD / USB video selection — follow-up plan

Date: 2026-07-19
Status: implementation, trusted validation, and review complete; merge, EAS publication, and physical retest pending.

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
- [x] External Storage Upload Check passes in trusted validation for the exact PR head.
- [x] Mobile Check passes (`npm ci` and TypeScript validation) in trusted validation for the exact PR head.
- [x] Operator Smoke Check command set passes in trusted validation for the exact PR head.
- [x] PR review is complete with no unresolved findings; the earlier workflow finding is outdated, fixed by removal, and resolved.
- [ ] Merge and EAS publication complete.
- [ ] Physical retest confirms unselected videos are not uploaded.
