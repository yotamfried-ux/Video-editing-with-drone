# Reset Drive OAuth fallback

This branch keeps the reset workflow from crashing immediately when the stored Google Drive OAuth credentials can no longer refresh.

Expected behavior:

1. Try the stored user OAuth credentials.
2. If Google returns `invalid_grant` / expired-or-revoked during refresh, print a clear warning.
3. Fall back to the configured Google service account.
4. Continue the reset so per-file Drive permission problems are logged by the existing reset steps.

This does not permanently replace the user OAuth credentials. If the service account does not have enough Drive permissions to move or delete user-owned files, regenerate the user OAuth JSON and update the GitHub Actions secret used by the workflow.
