import * as FileSystem from 'expo-file-system';

export const SPORTREEL_UPLOAD_CACHE_PREFIX = 'sportreel-upload-';

export type LocalCleanupEvidence = {
  artifactCount: number;
  reclaimedBytes: number;
  sourcePreserved: true;
};

function normalizedUri(uri: string): string {
  try {
    return decodeURIComponent(uri);
  } catch {
    return uri;
  }
}

export function isSportReelOwnedUploadTempUri(
  uri: string,
  cacheDirectory: string | null = FileSystem.cacheDirectory,
): boolean {
  if (!cacheDirectory || !uri.startsWith('file://')) return false;
  const normalizedCache = normalizedUri(cacheDirectory).replace(/\/+$/, '') + '/';
  const normalizedCandidate = normalizedUri(uri);
  if (!normalizedCandidate.startsWith(normalizedCache)) return false;
  const relative = normalizedCandidate.slice(normalizedCache.length);
  return Boolean(relative)
    && !relative.includes('/')
    && !relative.includes('..')
    && relative.startsWith(SPORTREEL_UPLOAD_CACHE_PREFIX);
}

async function readableSourceSnapshot(sourceUri: string): Promise<{ exists: boolean; size: number | null }> {
  const info = await FileSystem.getInfoAsync(sourceUri, { size: true });
  return {
    exists: info.exists,
    size: info.exists && 'size' in info && typeof info.size === 'number' ? info.size : null,
  };
}

async function assertSourcePreserved(
  sourceUri: string,
  expectedSourceSize: number | null,
): Promise<void> {
  const source = await readableSourceSnapshot(sourceUri);
  if (!source.exists) throw new Error('Selected SD / USB source is no longer available after cleanup.');
  if (
    expectedSourceSize != null
    && source.size != null
    && source.size !== expectedSourceSize
  ) {
    throw new Error(`Selected source size changed during cleanup: expected ${expectedSourceSize}, got ${source.size}.`);
  }
}

export async function cleanupVerifiedUploadArtifacts(input: {
  sourceUri: string;
  expectedSourceSize: number | null;
  temporaryUris: string[];
}): Promise<LocalCleanupEvidence> {
  if (!input.sourceUri.startsWith('content://') && !input.sourceUri.startsWith('file://')) {
    throw new Error('Unsupported source URI. Cleanup was not attempted.');
  }

  await assertSourcePreserved(input.sourceUri, input.expectedSourceSize);

  let reclaimedBytes = 0;
  let artifactCount = 0;
  const uniqueTemporaryUris = [...new Set(input.temporaryUris)];

  for (const uri of uniqueTemporaryUris) {
    if (!isSportReelOwnedUploadTempUri(uri)) {
      throw new Error(`Refusing to delete non-SportReel upload artifact: ${uri}`);
    }
    if (uri === input.sourceUri) {
      throw new Error('Refusing to delete the selected SD / USB source.');
    }

    const before = await FileSystem.getInfoAsync(uri, { size: true });
    if (before.exists) {
      if ('size' in before && typeof before.size === 'number') reclaimedBytes += before.size;
      artifactCount += 1;
    }

    await FileSystem.deleteAsync(uri, { idempotent: true });
    const after = await FileSystem.getInfoAsync(uri, { size: true });
    if (after.exists) {
      throw new Error(`Temporary upload artifact still exists after deletion: ${uri}`);
    }
  }

  await assertSourcePreserved(input.sourceUri, input.expectedSourceSize);
  return { artifactCount, reclaimedBytes, sourcePreserved: true };
}

export async function sweepStaleSportReelUploadArtifacts(input: {
  activeTemporaryUris: ReadonlySet<string>;
}): Promise<{ artifactCount: number; reclaimedBytes: number; failures: string[] }> {
  const cacheDirectory = FileSystem.cacheDirectory;
  if (!cacheDirectory) return { artifactCount: 0, reclaimedBytes: 0, failures: ['App cache is unavailable.'] };

  const names = await FileSystem.readDirectoryAsync(cacheDirectory);
  let artifactCount = 0;
  let reclaimedBytes = 0;
  const failures: string[] = [];

  for (const name of names) {
    if (!name.startsWith(SPORTREEL_UPLOAD_CACHE_PREFIX)) continue;
    const uri = `${cacheDirectory}${name}`;
    if (input.activeTemporaryUris.has(uri)) continue;
    if (!isSportReelOwnedUploadTempUri(uri, cacheDirectory)) {
      failures.push(`Rejected unsafe stale artifact path: ${uri}`);
      continue;
    }

    try {
      const before = await FileSystem.getInfoAsync(uri, { size: true });
      if (before.exists) {
        if ('size' in before && typeof before.size === 'number') reclaimedBytes += before.size;
        artifactCount += 1;
      }
      await FileSystem.deleteAsync(uri, { idempotent: true });
      const after = await FileSystem.getInfoAsync(uri, { size: true });
      if (after.exists) throw new Error('artifact still exists after deletion');
    } catch (error) {
      failures.push(`${uri}: ${error instanceof Error ? error.message : 'cleanup failed'}`);
    }
  }

  return { artifactCount, reclaimedBytes, failures };
}
