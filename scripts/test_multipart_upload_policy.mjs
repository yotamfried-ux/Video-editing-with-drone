import assert from 'node:assert/strict';
import {
  DEFAULT_PART_SIZE_BYTES,
  MAX_MULTIPART_PARTS,
  MIB,
  MIN_PART_SIZE_BYTES,
  chooseMultipartPartSize,
  expectedMultipartPartCount,
  expectedPartSize,
  normalizeCompletedParts,
} from '../web-api/src/lib/multipart-policy.mjs';

assert.equal(MIN_PART_SIZE_BYTES, 5 * MIB);
assert.equal(DEFAULT_PART_SIZE_BYTES, 16 * MIB);
assert.equal(MAX_MULTIPART_PARTS, 10_000);

const sourceSize = 40 * MIB + 123;
const partSize = chooseMultipartPartSize(sourceSize);
assert.equal(partSize, 16 * MIB);
assert.equal(expectedMultipartPartCount(sourceSize, partSize), 3);
assert.equal(expectedPartSize(sourceSize, partSize, 1), partSize);
assert.equal(expectedPartSize(sourceSize, partSize, 2), partSize);
assert.equal(expectedPartSize(sourceSize, partSize, 3), 8 * MIB + 123);

const sorted = normalizeCompletedParts(
  [
    { partNumber: 3, etag: '"etag-3"', sizeBytes: 8 * MIB + 123 },
    { partNumber: 1, etag: '"etag-1"', sizeBytes: partSize },
    { partNumber: 2, etag: '"etag-2"', sizeBytes: partSize },
  ],
  sourceSize,
  partSize,
);
assert.deepEqual(sorted.map((part) => part.PartNumber), [1, 2, 3]);
assert.deepEqual(sorted.map((part) => part.ETag), ['"etag-1"', '"etag-2"', '"etag-3"']);

assert.throws(() => chooseMultipartPartSize(0), /positive safe integer/);
assert.throws(() => expectedMultipartPartCount(10 * MIB, 4 * MIB), /at least/);
assert.throws(
  () => normalizeCompletedParts([
    { partNumber: 1, etag: 'a', sizeBytes: partSize },
    { partNumber: 1, etag: 'b', sizeBytes: partSize },
    { partNumber: 3, etag: 'c', sizeBytes: 8 * MIB + 123 },
  ], sourceSize, partSize),
  /duplicate part number/,
);
assert.throws(
  () => normalizeCompletedParts([
    { partNumber: 1, etag: 'a', sizeBytes: partSize - 1 },
    { partNumber: 2, etag: 'b', sizeBytes: partSize },
    { partNumber: 3, etag: 'c', sizeBytes: 8 * MIB + 124 },
  ], sourceSize, partSize),
  /does not match expected/,
);
assert.throws(
  () => normalizeCompletedParts([
    { partNumber: 1, etag: '', sizeBytes: partSize },
    { partNumber: 2, etag: 'b', sizeBytes: partSize },
    { partNumber: 3, etag: 'c', sizeBytes: 8 * MIB + 123 },
  ], sourceSize, partSize),
  /missing ETag/,
);

const enormousSource = MAX_MULTIPART_PARTS * MIN_PART_SIZE_BYTES + 1;
const enlargedPartSize = chooseMultipartPartSize(enormousSource, MIN_PART_SIZE_BYTES);
assert.ok(enlargedPartSize > MIN_PART_SIZE_BYTES);
assert.ok(expectedMultipartPartCount(enormousSource, enlargedPartSize) <= MAX_MULTIPART_PARTS);

console.log('Multipart upload policy contract ok');
