// Multipart invariants mirror Cloudflare R2 limits and the official
// @aws-sdk/lib-storage Upload implementation. Keep this module dependency-free
// so the exact policy can be executed by repository contract tests.

export const MIB = 1024 * 1024;
export const MIN_PART_SIZE_BYTES = 5 * MIB;
export const DEFAULT_PART_SIZE_BYTES = 16 * MIB;
export const MAX_MULTIPART_PARTS = 10_000;
export const MULTIPART_PROTOCOL_VERSION = 'r2-multipart-v1';

function positiveSafeInteger(value, label) {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`${label} must be a positive safe integer`);
  }
  return value;
}

export function chooseMultipartPartSize(sourceSizeBytes, requestedPartSizeBytes = DEFAULT_PART_SIZE_BYTES) {
  positiveSafeInteger(sourceSizeBytes, 'sourceSizeBytes');
  positiveSafeInteger(requestedPartSizeBytes, 'requestedPartSizeBytes');

  const minimumForPartLimit = Math.ceil(sourceSizeBytes / MAX_MULTIPART_PARTS);
  const unrounded = Math.max(MIN_PART_SIZE_BYTES, requestedPartSizeBytes, minimumForPartLimit);
  return Math.ceil(unrounded / MIB) * MIB;
}

export function expectedMultipartPartCount(sourceSizeBytes, partSizeBytes) {
  positiveSafeInteger(sourceSizeBytes, 'sourceSizeBytes');
  positiveSafeInteger(partSizeBytes, 'partSizeBytes');
  if (partSizeBytes < MIN_PART_SIZE_BYTES) {
    throw new Error(`partSizeBytes must be at least ${MIN_PART_SIZE_BYTES}`);
  }
  const count = Math.ceil(sourceSizeBytes / partSizeBytes);
  if (count > MAX_MULTIPART_PARTS) {
    throw new Error(`multipart upload would exceed ${MAX_MULTIPART_PARTS} parts`);
  }
  return count;
}

export function expectedPartSize(sourceSizeBytes, partSizeBytes, partNumber) {
  const partCount = expectedMultipartPartCount(sourceSizeBytes, partSizeBytes);
  if (!Number.isSafeInteger(partNumber) || partNumber < 1 || partNumber > partCount) {
    throw new Error(`partNumber must be between 1 and ${partCount}`);
  }
  if (partNumber < partCount) return partSizeBytes;
  return sourceSizeBytes - partSizeBytes * (partCount - 1);
}

export function normalizeCompletedParts(parts, sourceSizeBytes, partSizeBytes) {
  const expectedCount = expectedMultipartPartCount(sourceSizeBytes, partSizeBytes);
  if (!Array.isArray(parts) || parts.length !== expectedCount) {
    throw new Error(`expected ${expectedCount} completed parts, received ${Array.isArray(parts) ? parts.length : 0}`);
  }

  const seen = new Set();
  let uploadedBytes = 0;
  const normalized = parts.map((part) => {
    const partNumber = Number(part.partNumber ?? part.PartNumber);
    const etag = String(part.etag ?? part.ETag ?? '').trim();
    const sizeBytes = Number(part.sizeBytes ?? part.size_bytes);

    if (!Number.isSafeInteger(partNumber) || partNumber < 1 || partNumber > expectedCount) {
      throw new Error(`invalid part number ${partNumber}`);
    }
    if (seen.has(partNumber)) throw new Error(`duplicate part number ${partNumber}`);
    seen.add(partNumber);
    if (!etag) throw new Error(`part ${partNumber} is missing ETag`);

    const expectedSize = expectedPartSize(sourceSizeBytes, partSizeBytes, partNumber);
    if (!Number.isSafeInteger(sizeBytes) || sizeBytes !== expectedSize) {
      throw new Error(`part ${partNumber} size ${sizeBytes} does not match expected ${expectedSize}`);
    }
    uploadedBytes += sizeBytes;
    return { PartNumber: partNumber, ETag: etag, sizeBytes };
  });

  if (uploadedBytes !== sourceSizeBytes) {
    throw new Error(`completed part bytes ${uploadedBytes} do not match source size ${sourceSizeBytes}`);
  }

  normalized.sort((a, b) => a.PartNumber - b.PartNumber);
  return normalized;
}
