import { ApiError } from '@/shared/lib/api';
import { isRetryableUploadError } from './uploadRetryPolicy';

describe('isRetryableUploadError', () => {
  it.each([401, 403, 404, 409, 422])('fails fast for permanent operator API status %s', (status) => {
    expect(isRetryableUploadError(new ApiError(status, 'permanent'))).toBe(false);
  });

  it.each([408, 425, 429, 500, 502, 503, 504])('retries transient operator API status %s', (status) => {
    expect(isRetryableUploadError(new ApiError(status, 'transient'))).toBe(true);
  });

  it('retries a signed object-storage 403 so the next attempt can fetch a fresh URL', () => {
    expect(isRetryableUploadError(new Error('Upload failed with status 403'))).toBe(true);
  });

  it('does not retry permanent object-storage 4xx failures', () => {
    expect(isRetryableUploadError(new Error('Upload failed with status 400'))).toBe(false);
  });

  it.each([
    'Network request failed',
    'fetch failed',
    'request timed out',
    'connection reset by peer',
    'service unavailable',
  ])('retries transient transport error: %s', (message) => {
    expect(isRetryableUploadError(new Error(message))).toBe(true);
  });

  it('fails fast for unrelated local validation errors', () => {
    expect(isRetryableUploadError(new Error('Cannot determine a stable positive source size'))).toBe(false);
  });
});
