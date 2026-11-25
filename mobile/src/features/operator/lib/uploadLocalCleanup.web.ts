export const SPORTREEL_UPLOAD_CACHE_PREFIX = 'sportreel-upload-';

export type LocalCleanupEvidence = {
  artifactCount: number;
  reclaimedBytes: number;
  sourcePreserved: true;
};

export function isSportReelOwnedUploadTempUri(): boolean {
  return false;
}

export async function cleanupVerifiedUploadArtifacts(): Promise<LocalCleanupEvidence> {
  return { artifactCount: 0, reclaimedBytes: 0, sourcePreserved: true };
}

export async function cleanupVerifiedUploadCacheArtifacts(): Promise<LocalCleanupEvidence> {
  return { artifactCount: 0, reclaimedBytes: 0, sourcePreserved: true };
}

export async function sweepStaleSportReelUploadArtifacts(): Promise<LocalCleanupEvidence> {
  return { artifactCount: 0, reclaimedBytes: 0, sourcePreserved: true };
}
