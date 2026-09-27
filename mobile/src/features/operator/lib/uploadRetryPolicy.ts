import { ApiError } from '@/shared/lib/api';

const TRANSIENT_NETWORK_MARKERS = [
  'network request failed',
  'network error',
  'fetch failed',
  'timed out',
  'timeout',
  'connection reset',
  'connection refused',
  'socket',
  'temporarily unavailable',
  'service unavailable',
  'unavailable',
  'aborted',
];

function retryableHttpStatus(status: number): boolean {
  return status === 408 || status === 425 || status === 429 || status >= 500;
}

export function isRetryableUploadError(error: unknown): boolean {
  if (error instanceof ApiError) {
    return retryableHttpStatus(error.status);
  }

  if (!(error instanceof Error)) return false;

  // Object-storage signed URLs can expire independently of the operator API.
  // A retry creates/re-fetches the upload session immediately before the next
  // attempt, so a storage-level 403 is safe and useful to retry.
  const storageStatus = error.message.match(/Upload failed with status\s+(\d{3})/i);
  if (storageStatus) {
    const status = Number(storageStatus[1]);
    return status === 403 || retryableHttpStatus(status);
  }

  const message = error.message.toLowerCase();
  return TRANSIENT_NETWORK_MARKERS.some((marker) => message.includes(marker));
}
