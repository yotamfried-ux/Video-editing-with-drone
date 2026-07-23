export const MIB: number;
export const MIN_PART_SIZE_BYTES: number;
export const DEFAULT_PART_SIZE_BYTES: number;
export const MAX_MULTIPART_PARTS: number;
export const MULTIPART_PROTOCOL_VERSION: string;

export type MultipartPartInput = {
  partNumber?: number;
  PartNumber?: number;
  etag?: string;
  ETag?: string;
  sizeBytes?: number;
  size_bytes?: number;
};

export type NormalizedMultipartPart = {
  PartNumber: number;
  ETag: string;
  sizeBytes: number;
};

export function chooseMultipartPartSize(sourceSizeBytes: number, requestedPartSizeBytes?: number): number;
export function expectedMultipartPartCount(sourceSizeBytes: number, partSizeBytes: number): number;
export function expectedPartSize(sourceSizeBytes: number, partSizeBytes: number, partNumber: number): number;
export function normalizeCompletedParts(
  parts: MultipartPartInput[],
  sourceSizeBytes: number,
  partSizeBytes: number,
): NormalizedMultipartPart[];
