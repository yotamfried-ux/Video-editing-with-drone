export function githubDispatchError(status: number, rawText: string): string {
  switch (status) {
    case 403:
      return (
        'GitHub dispatch token is missing required permissions. ' +
        'Update GITHUB_DISPATCH_TOKEN in Vercel with a fine-grained PAT ' +
        'that has Actions: Read and write + Contents: Read and write.'
      );
    case 404:
      return (
        'GitHub repo or workflow not found, or the token has no access to this repository. ' +
        'Check GITHUB_REPO and ensure the PAT is scoped to yotamfried-ux/Video-editing-with-drone.'
      );
    case 422:
      return (
        `GitHub rejected the dispatch payload (422): ${rawText.slice(0, 200)}`
      );
    default:
      return `GitHub dispatch failed (${status}): ${rawText.slice(0, 200)}`;
  }
}
