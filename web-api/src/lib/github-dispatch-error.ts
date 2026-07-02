export function githubDispatchError(status: number, rawText: string): string {
  const detail = rawText.trim().slice(0, 200);

  switch (status) {
    case 403:
      return (
        'GitHub dispatch token is missing required permissions. ' +
        'Update GITHUB_DISPATCH_TOKEN in Vercel with a fine-grained PAT that has ' +
        'Actions: Read and write and Contents: Read and write for yotamfried-ux/Video-editing-with-drone.'
      );
    case 404:
      return (
        'GitHub repo or workflow was not found, or the token has no access to it. ' +
        'Check GITHUB_REPO and ensure GITHUB_DISPATCH_TOKEN is scoped to yotamfried-ux/Video-editing-with-drone.'
      );
    case 422:
      return `GitHub rejected the dispatch payload (422): ${detail}`;
    default:
      return `GitHub dispatch failed (${status}): ${detail || 'No response body'}`;
  }
}
