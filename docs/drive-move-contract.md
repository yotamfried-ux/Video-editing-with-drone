# Drive move contract

This note documents the Drive folder transitions that keep the operator app and pipeline state consistent.

## Invariant

A RAW source video must not be recorded in `processed.json` until the Drive move from `RAW_FOLDER_ID` to `PROCESSED_FOLDER_ID` is verified.

The Drive folder location is durable state. `processed.json` is only a local runner cache used to avoid duplicate work.

## Why this matters

If the pipeline writes the source file ID to `processed.json` before the Drive move succeeds, the next run can skip a file that still sits in RAW. That creates a false-success state: the operator app may show a run as complete while the source file remains in the input folder and is no longer processed.

## Required behavior

For every Drive transition:

1. Read the current Drive parents for the file.
2. Verify the file is in the expected source folder, unless it is already in the target folder.
3. Move the file with `addParents` and `removeParents`.
4. Verify the target folder is present and the source folder is gone.
5. Only then update local cache state such as `processed.json`.

The pipeline should support both files uploaded manually and files uploaded through the operator app.

## Failure behavior

If RAW to PROCESSED cannot be verified, the pipeline must fail loudly and must not mark the video as processed. The next run can retry instead of silently skipping the RAW file.

Delivery and payment moves may remain best-effort, but they should still use the same verified Drive transition helper so logs explain the failed path and current parents.

## Verification loop

1. Run a positive test with a source file in RAW and confirm it moves to PROCESSED.
2. Run a negative test with a file that is not in the expected source folder and confirm the move is refused.
3. Confirm `processed.json` changes only after a verified RAW to PROCESSED move.
4. Confirm the operator app does not see a false-success row for a file still stuck in RAW.
