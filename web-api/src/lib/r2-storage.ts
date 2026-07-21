import { createHash, createHmac } from 'crypto';
import { basename } from 'path';

const REGION = 'auto';
const SERVICE = 's3';
const DEFAULT_BUCKET = 'sportreel';
const EXPIRES = 3600;
const MIB = 1024 * 1024;
const MIN_MULTIPART_PART_SIZE = 5 * MIB;
const DEFAULT_MULTIPART_PART_SIZE = 8 * MIB;
const MAX_MULTIPART_PARTS = 10_000;

export type R2Object = { key: string; name: string; size: number | null; created_at: string };
export type R2MultipartPart = { partNumber: number; etag: string; size: number };
export type R2MultipartStatus = {
  state: 'in_progress' | 'completed' | 'missing';
  parts: R2MultipartPart[];
  uploadedBytes: number;
  objectSize: number | null;
};
export type R2MultipartSession = {
  key: string;
  filename: string;
  batch_id: string;
  upload_id: string;
  part_size_bytes: number;
  reused: boolean;
  already_complete: boolean;
  existing_size_bytes: number | null;
};

const env = (...names: string[]) => names.map((name) => process.env[name]?.trim() ?? '').find(Boolean) ?? '';
const required = (label: string, value: string) => {
  if (!value) throw new Error(`${label} not configured`);
  return value;
};
const accessKey = () => required('R2 access key', env('R2_ACCESS_KEY_ID', 'ACCESS_KEY_ID'));
const signingSecret = () => required('R2 secret key', env('R2_SECRET_ACCESS_KEY', 'SECRET_KEY_ID'));
const accountId = () => required('R2_ACCOUNT_ID', env('R2_ACCOUNT_ID'));
const bucket = () => env('R2_BUCKET') || DEFAULT_BUCKET;
const endpoint = () => (env('R2_ENDPOINT_URL') || `https://${accountId()}.r2.cloudflarestorage.com`).replace(/\/+$/, '');

export function isR2Configured(): boolean {
  return Boolean(env('R2_ACCOUNT_ID') && env('R2_ACCESS_KEY_ID', 'ACCESS_KEY_ID') && env('R2_SECRET_ACCESS_KEY', 'SECRET_KEY_ID'));
}

export function shouldUseR2Storage(): boolean {
  const backend = env('STORAGE_BACKEND').toLowerCase();
  if (backend === 'drive') return false;
  return backend === 'r2' || isR2Configured();
}

const hmac = (key: Buffer | string, value: string) => createHmac('sha256', key).update(value).digest();
const sha256Hex = (value: string) => createHash('sha256').update(value).digest('hex');
const encode = (value: string) => encodeURIComponent(value).replace(/[!'()*]/g, (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`);
const encodeKey = (key: string) => key.split('/').map(encode).join('/');
const safeFilename = (filename: string) => basename(filename).replace(/[\\/]+/g, '_').trim() || `footage_${Date.now()}.mp4`;
export const safeBatchId = (batchId?: string | null) => (batchId ?? '').replace(/[^A-Za-z0-9_-]/g, '_').replace(/^_+|_+$/g, '').slice(0, 80);
export const safeUploadId = (uploadId?: string | null) => (uploadId ?? '').replace(/[^A-Za-z0-9_-]/g, '_').replace(/^_+|_+$/g, '').slice(0, 96);
export const newBatchId = (now = new Date()) => `batch_${now.toISOString().replace(/[:.]/g, '-').slice(0, 19)}_${Math.random().toString(36).slice(2, 8)}`;
const objectPath = (key = '') => (key ? `/${bucket()}/${encodeKey(key)}` : `/${bucket()}`);

export const r2Basename = (key: string) => basename(key.replace(/\/+$/, ''));
export const isSafeRawR2Key = (key: string) => key.startsWith('raw/') && !key.includes('..') && !key.includes('\\');

function amzDate(now = new Date()) {
  const timestamp = now.toISOString().replace(/[:-]|\.\d{3}/g, '');
  return { dateStamp: timestamp.slice(0, 8), timestamp };
}

function signingKey(dateStamp: string) {
  const kDate = hmac(`AWS4${signingSecret()}`, dateStamp);
  const kRegion = hmac(kDate, REGION);
  const kService = hmac(kRegion, SERVICE);
  return hmac(kService, 'aws4_request');
}

function canonicalQuery(params: URLSearchParams): string {
  return [...params.entries()]
    .map(([key, value]) => [encode(key), encode(value)] as const)
    .sort(([leftKey, leftValue], [rightKey, rightValue]) => {
      if (leftKey < rightKey) return -1;
      if (leftKey > rightKey) return 1;
      if (leftValue < rightValue) return -1;
      if (leftValue > rightValue) return 1;
      return 0;
    })
    .map(([key, value]) => `${key}=${value}`)
    .join('&');
}

function normalizedHeaders(headers: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(headers).map(([name, value]) => [name.toLowerCase().trim(), value.trim().replace(/\s+/g, ' ')]),
  );
}

function presign(
  method: 'GET' | 'PUT' | 'POST' | 'DELETE' | 'HEAD',
  key: string,
  expires = EXPIRES,
  requiredHeaders: Record<string, string> = {},
  requestQuery = new URLSearchParams(),
): string {
  const host = new URL(endpoint()).host;
  const { dateStamp, timestamp } = amzDate();
  const scope = `${dateStamp}/${REGION}/${SERVICE}/aws4_request`;
  const headers = normalizedHeaders({ host, ...requiredHeaders });
  const signedHeaders = Object.keys(headers).sort().join(';');
  const canonicalHeaders = Object.keys(headers).sort().map((header) => `${header}:${headers[header]}\n`).join('');
  const params = new URLSearchParams(requestQuery.toString());
  params.set('X-Amz-Algorithm', 'AWS4-HMAC-SHA256');
  params.set('X-Amz-Credential', `${accessKey()}/${scope}`);
  params.set('X-Amz-Date', timestamp);
  params.set('X-Amz-Expires', String(expires));
  params.set('X-Amz-SignedHeaders', signedHeaders);
  const canonical = [method, objectPath(key), canonicalQuery(params), canonicalHeaders, signedHeaders, 'UNSIGNED-PAYLOAD'].join('\n');
  const stringToSign = ['AWS4-HMAC-SHA256', timestamp, scope, sha256Hex(canonical)].join('\n');
  params.set('X-Amz-Signature', createHmac('sha256', signingKey(dateStamp)).update(stringToSign).digest('hex'));
  return `${endpoint()}${objectPath(key)}?${canonicalQuery(params)}`;
}

export function createR2SignedGetUrl(key: string): string {
  return presign('GET', key);
}

function objectIdentity(
  filename: string,
  requestedBatchId?: string | null,
  clientUploadId?: string | null,
): { key: string; filename: string; batch_id: string } {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const batchId = safeBatchId(requestedBatchId) || newBatchId();
  const stableUploadId = safeUploadId(clientUploadId);
  const storageName = stableUploadId
    ? `${stableUploadId}_${safeFilename(filename)}`
    : `${stamp}_${safeFilename(filename)}`;
  return { key: `raw/${batchId}/${storageName}`, filename: storageName, batch_id: batchId };
}

/**
 * Create a just-in-time single PUT URL for legacy/small-object callers. The
 * multipart operator path below is used by the mobile video uploader.
 */
export function createR2UploadUrl(
  filename: string,
  requestedBatchId?: string | null,
  clientUploadId?: string | null,
  mimeType = 'application/octet-stream',
): { uploadUrl: string; key: string; filename: string; batch_id: string } {
  const identity = objectIdentity(filename, requestedBatchId, clientUploadId);
  return {
    uploadUrl: presign('PUT', identity.key, EXPIRES, { 'content-type': mimeType }),
    ...identity,
  };
}

async function signedFetch(
  method: string,
  key: string,
  query = new URLSearchParams(),
  extraHeaders: Record<string, string> = {},
  body?: string,
) {
  const host = new URL(endpoint()).host;
  const { dateStamp, timestamp } = amzDate();
  const scope = `${dateStamp}/${REGION}/${SERVICE}/aws4_request`;
  const payloadHash = body === undefined ? 'UNSIGNED-PAYLOAD' : sha256Hex(body);
  const headers: Record<string, string> = normalizedHeaders({
    host,
    'x-amz-content-sha256': payloadHash,
    'x-amz-date': timestamp,
    ...extraHeaders,
  });
  const signedHeaders = Object.keys(headers).sort().join(';');
  const canonicalHeaders = Object.keys(headers).sort().map((header) => `${header}:${headers[header]}\n`).join('');
  const canonical = [method, objectPath(key), canonicalQuery(query), canonicalHeaders, signedHeaders, payloadHash].join('\n');
  const stringToSign = ['AWS4-HMAC-SHA256', timestamp, scope, sha256Hex(canonical)].join('\n');
  const signature = createHmac('sha256', signingKey(dateStamp)).update(stringToSign).digest('hex');
  const authorization = `AWS4-HMAC-SHA256 Credential=${accessKey()}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;
  const encodedQuery = canonicalQuery(query);
  const url = `${endpoint()}${objectPath(key)}${encodedQuery ? `?${encodedQuery}` : ''}`;
  const outbound = { ...headers, Authorization: authorization };
  delete (outbound as Record<string, string>).host;
  return fetch(url, { method, headers: outbound, body });
}

const decodeXml = (value: string) => value.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
const xmlEscape = (value: string) => value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const xmlTag = (xml: string, tag: string) => decodeXml(xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`))?.[1] ?? '');

function multipartPartSize(totalBytes?: number | null): number {
  const knownBytes = Number.isFinite(totalBytes) && Number(totalBytes) > 0 ? Number(totalBytes) : 0;
  const minimumForPartLimit = knownBytes ? Math.ceil(knownBytes / MAX_MULTIPART_PARTS) : 0;
  const raw = Math.max(DEFAULT_MULTIPART_PART_SIZE, MIN_MULTIPART_PART_SIZE, minimumForPartLimit);
  return Math.ceil(raw / MIB) * MIB;
}

async function findActiveMultipartUpload(key: string): Promise<string | null> {
  const query = new URLSearchParams({ uploads: '', prefix: key, 'max-uploads': '1000' });
  const response = await signedFetch('GET', '', query);
  const text = await response.text();
  if (!response.ok) throw new Error(`R2 multipart list failed (${response.status}): ${text.slice(0, 300)}`);

  const matches = [...text.matchAll(/<Upload>([\s\S]*?)<\/Upload>/g)]
    .map((match) => ({
      key: xmlTag(match[1], 'Key'),
      uploadId: xmlTag(match[1], 'UploadId'),
      initiated: xmlTag(match[1], 'Initiated'),
    }))
    .filter((upload) => upload.key === key && upload.uploadId)
    .sort((left, right) => left.initiated.localeCompare(right.initiated));
  return matches.at(-1)?.uploadId ?? null;
}

export async function createR2MultipartUpload(
  filename: string,
  requestedBatchId?: string | null,
  clientUploadId?: string | null,
  mimeType = 'application/octet-stream',
  totalBytes?: number | null,
): Promise<R2MultipartSession> {
  const identity = objectIdentity(filename, requestedBatchId, clientUploadId);
  const object = await verifyR2Object(identity.key);
  const expectedBytes = Number.isSafeInteger(totalBytes) && Number(totalBytes) > 0 ? Number(totalBytes) : null;
  if (object.exists && (expectedBytes === null || object.size === expectedBytes)) {
    return {
      ...identity,
      upload_id: '',
      part_size_bytes: multipartPartSize(totalBytes),
      reused: true,
      already_complete: true,
      existing_size_bytes: object.size,
    };
  }

  // A stable key can contain a truncated object from an older single-PUT flow.
  // Do not treat a wrong-size object as complete; a successful multipart
  // completion atomically replaces it at the same key.
  const existingUploadId = await findActiveMultipartUpload(identity.key);
  if (existingUploadId) {
    return {
      ...identity,
      upload_id: existingUploadId,
      part_size_bytes: multipartPartSize(totalBytes),
      reused: true,
      already_complete: false,
      existing_size_bytes: object.exists ? object.size : null,
    };
  }

  const response = await signedFetch(
    'POST',
    identity.key,
    new URLSearchParams({ uploads: '' }),
    { 'content-type': mimeType },
  );
  const text = await response.text();
  if (!response.ok) throw new Error(`R2 multipart init failed (${response.status}): ${text.slice(0, 300)}`);
  const uploadId = xmlTag(text, 'UploadId');
  if (!uploadId) throw new Error('R2 multipart init did not return an upload id');

  return {
    ...identity,
    upload_id: uploadId,
    part_size_bytes: multipartPartSize(totalBytes),
    reused: false,
    already_complete: false,
    existing_size_bytes: object.exists ? object.size : null,
  };
}

export function createR2MultipartPartUrl(key: string, uploadId: string, partNumber: number): string {
  if (!isSafeRawR2Key(key)) throw new Error('Unsafe R2 multipart key');
  if (!uploadId.trim()) throw new Error('upload_id required');
  if (!Number.isInteger(partNumber) || partNumber < 1 || partNumber > MAX_MULTIPART_PARTS) {
    throw new Error(`part_number must be between 1 and ${MAX_MULTIPART_PARTS}`);
  }
  return presign('PUT', key, EXPIRES, {}, new URLSearchParams({
    partNumber: String(partNumber),
    uploadId,
  }));
}

export async function listR2MultipartParts(key: string, uploadId: string): Promise<{ exists: boolean; parts: R2MultipartPart[] }> {
  if (!isSafeRawR2Key(key)) throw new Error('Unsafe R2 multipart key');
  const parts: R2MultipartPart[] = [];
  let marker = '';

  do {
    const query = new URLSearchParams({ uploadId, 'max-parts': '1000' });
    if (marker) query.set('part-number-marker', marker);
    const response = await signedFetch('GET', key, query);
    const text = await response.text();
    if (response.status === 404 || text.includes('<Code>NoSuchUpload</Code>')) return { exists: false, parts: [] };
    if (!response.ok) throw new Error(`R2 list parts failed (${response.status}): ${text.slice(0, 300)}`);

    for (const match of text.matchAll(/<Part>([\s\S]*?)<\/Part>/g)) {
      const partNumber = Number(xmlTag(match[1], 'PartNumber'));
      const size = Number(xmlTag(match[1], 'Size'));
      const etag = xmlTag(match[1], 'ETag');
      if (Number.isInteger(partNumber) && partNumber > 0 && Number.isFinite(size) && size >= 0 && etag) {
        parts.push({ partNumber, size, etag });
      }
    }

    const truncated = xmlTag(text, 'IsTruncated').toLowerCase() === 'true';
    marker = truncated ? xmlTag(text, 'NextPartNumberMarker') : '';
    if (truncated && !marker) throw new Error('R2 list parts response was truncated without a continuation marker');
  } while (marker);

  parts.sort((left, right) => left.partNumber - right.partNumber);
  return { exists: true, parts };
}

export async function getR2MultipartStatus(key: string, uploadId: string): Promise<R2MultipartStatus> {
  const listed = await listR2MultipartParts(key, uploadId);
  if (listed.exists) {
    return {
      state: 'in_progress',
      parts: listed.parts,
      uploadedBytes: listed.parts.reduce((sum, part) => sum + part.size, 0),
      objectSize: null,
    };
  }

  const object = await verifyR2Object(key);
  if (object.exists) {
    return { state: 'completed', parts: [], uploadedBytes: object.size ?? 0, objectSize: object.size };
  }
  return { state: 'missing', parts: [], uploadedBytes: 0, objectSize: null };
}

function validateCompleteParts(parts: R2MultipartPart[], expectedSizeBytes: number): R2MultipartPart[] {
  const sorted = [...parts].sort((left, right) => left.partNumber - right.partNumber);
  if (!sorted.length) throw new Error('Cannot complete an empty multipart upload');
  if (!Number.isInteger(expectedSizeBytes) || expectedSizeBytes <= 0) throw new Error('expected_size_bytes must be a positive integer');

  let standardSize: number | null = null;
  sorted.forEach((part, index) => {
    if (part.partNumber !== index + 1) throw new Error(`Multipart upload is missing part ${index + 1}`);
    const isLast = index === sorted.length - 1;
    if (!isLast) {
      if (part.size < MIN_MULTIPART_PART_SIZE) throw new Error(`Multipart part ${part.partNumber} is smaller than 5 MiB`);
      standardSize ??= part.size;
      if (part.size !== standardSize) throw new Error('All non-final multipart parts must use the same byte size');
    } else if (standardSize !== null && part.size > standardSize) {
      throw new Error('The final multipart part cannot be larger than the standard part size');
    }
  });

  const actualSize = sorted.reduce((sum, part) => sum + part.size, 0);
  if (actualSize !== expectedSizeBytes) {
    throw new Error(`Multipart byte total mismatch: expected ${expectedSizeBytes}, found ${actualSize}`);
  }
  return sorted;
}

export async function completeR2MultipartUpload(
  key: string,
  uploadId: string,
  expectedSizeBytes: number,
): Promise<{ key: string; size: number; etag: string | null; parts: R2MultipartPart[] }> {
  const status = await getR2MultipartStatus(key, uploadId);
  if (status.state === 'completed') {
    if (status.objectSize !== expectedSizeBytes) {
      throw new Error(`Completed R2 object size mismatch: expected ${expectedSizeBytes}, found ${status.objectSize ?? 'unknown'}`);
    }
    return { key, size: expectedSizeBytes, etag: null, parts: [] };
  }
  if (status.state === 'missing') throw new Error('R2 multipart upload no longer exists');

  const parts = validateCompleteParts(status.parts, expectedSizeBytes);
  const xml = `<CompleteMultipartUpload>${parts.map((part) => `<Part><PartNumber>${part.partNumber}</PartNumber><ETag>${xmlEscape(part.etag)}</ETag></Part>`).join('')}</CompleteMultipartUpload>`;
  const response = await signedFetch(
    'POST',
    key,
    new URLSearchParams({ uploadId }),
    { 'content-type': 'application/xml' },
    xml,
  );
  const text = await response.text();
  if (!response.ok || text.includes('<Error>')) throw new Error(`R2 multipart complete failed (${response.status}): ${text.slice(0, 500)}`);

  let verified: Awaited<ReturnType<typeof verifyR2Object>> = { exists: false, size: null, status: 404 };
  for (let attempt = 0; attempt < 5; attempt += 1) {
    verified = await verifyR2Object(key);
    if (verified.exists && verified.size === expectedSizeBytes) break;
    await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
  }
  if (!verified.exists || verified.size !== expectedSizeBytes) {
    throw new Error(`R2 completed-object verification failed: expected ${expectedSizeBytes}, found ${verified.size ?? 'missing'}`);
  }

  return { key, size: expectedSizeBytes, etag: xmlTag(text, 'ETag') || null, parts };
}

export async function abortR2MultipartUpload(key: string, uploadId: string): Promise<void> {
  if (!isSafeRawR2Key(key)) throw new Error('Unsafe R2 multipart key');
  const response = await signedFetch('DELETE', key, new URLSearchParams({ uploadId }));
  const text = await response.text();
  if (!response.ok && response.status !== 404 && !text.includes('<Code>NoSuchUpload</Code>')) {
    throw new Error(`R2 multipart abort failed (${response.status}): ${text.slice(0, 300)}`);
  }
}

export async function listR2Prefix(prefix: string): Promise<R2Object[]> {
  const objects: R2Object[] = [];
  let token = '';
  do {
    const query = new URLSearchParams({ 'list-type': '2', prefix });
    if (token) query.set('continuation-token', token);
    const response = await signedFetch('GET', '', query);
    const text = await response.text();
    if (!response.ok) throw new Error(`R2 list failed (${response.status}): ${text.slice(0, 200)}`);
    for (const match of text.matchAll(/<Contents>([\s\S]*?)<\/Contents>/g)) {
      const key = xmlTag(match[1], 'Key');
      if (!key || key.endsWith('/')) continue;
      objects.push({ key, name: r2Basename(key), created_at: xmlTag(match[1], 'LastModified') || new Date().toISOString(), size: Number(xmlTag(match[1], 'Size') || '0') });
    }
    token = xmlTag(text, 'NextContinuationToken');
  } while (token);
  return objects;
}

export async function moveR2Object(sourceKey: string, destinationPrefix: string): Promise<string> {
  const destKey = `${destinationPrefix.replace(/\/+$/, '')}/${r2Basename(sourceKey)}`;
  const copyResponse = await signedFetch('PUT', destKey, new URLSearchParams(), { 'x-amz-copy-source': `/${bucket()}/${encodeKey(sourceKey)}` });
  const copyText = await copyResponse.text();
  if (!copyResponse.ok) throw new Error(`R2 copy failed (${copyResponse.status}): ${copyText.slice(0, 200)}`);
  const deleteResponse = await signedFetch('DELETE', sourceKey);
  const deleteText = await deleteResponse.text();
  if (!deleteResponse.ok) throw new Error(`R2 delete failed (${deleteResponse.status}): ${deleteText.slice(0, 200)}`);
  return destKey;
}

export async function verifyR2Object(key: string): Promise<{ exists: boolean; size: number | null; status: number }> {
  const response = await signedFetch('HEAD', key);
  return {
    exists: response.ok,
    size: response.ok ? Number(response.headers.get('content-length') ?? '0') : null,
    status: response.status,
  };
}
