# Upload-to-run smoke loop

This is the required operational smoke loop for the mobile upload path.

## Goal

Prove that a video uploaded from the operator app is visible to the pipeline and connected to a durable run row.

## Preconditions

- Operator app is pointed at the deployed API.
- Operator authorization is configured in the app.
- Drive folders and Supabase tables are configured for the environment.
- GitHub dispatch is configured for the pipeline workflow.

## Steps

1. Open the operator app and go to Pipeline.
2. Tap Upload footage.
3. Select a small real video file.
4. Wait for the upload success alert.
5. Record the uploaded filename shown by the app.
6. Record the run id prefix shown by the app.
7. Open the RAW Drive folder and confirm the uploaded filename exists there.
8. Open the operator Pipeline screen and confirm Recent pipeline runs contains the same run prefix.
9. Confirm the row moves away from queued after the workflow starts.
10. Confirm the row eventually reaches succeeded, failed, no_input, or dispatch_failed.

## Pass criteria

The smoke loop passes only if all are true:

- The uploaded file exists in RAW after the app upload.
- The app created a pipeline run and showed its run prefix.
- Recent pipeline runs shows the same run prefix.
- The pipeline run receives workflow updates rather than staying permanently queued.
- A failure is displayed as an actionable failure, not as success.

## Fail criteria

The smoke loop fails if any are true:

- Upload succeeds in the app but the file is missing from RAW.
- A pipeline run id is not shown after upload.
- Recent pipeline runs does not show the same run prefix.
- The run remains queued after the workflow should have started.
- The app shows success while the tracked row is failed or dispatch_failed.

## Notes

`pipeline_status` is a global live signal. Do not use it as proof that this specific upload is running. Use the returned run id and the Recent pipeline runs card.
