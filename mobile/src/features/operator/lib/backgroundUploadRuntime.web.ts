export function isBackgroundUploadAvailable(): boolean {
  return false;
}

export function getBackgroundUploadClient(): never {
  throw new Error('Native background upload service is Android-only; browser uploads run in the active tab.');
}

export async function reconcilePendingBackgroundUploads(): Promise<void> {}
