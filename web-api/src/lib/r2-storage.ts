import { createHash, createHmac } from 'crypto';
import { basename } from 'path';

const REGION = 'auto';
const SERVICE = 's3';
const DEFAULT_BUCKET = 'sportreel';
const EXPIRES = 3600;
const MULTIPART_PART_URL_EXPIRES = 900;

export const R2_MIN_MULTIPART_PART_SIZE = 5 * 1024 * 1024;
export const R2_MAX_MULTIPART_PART_SIZE = 5 * 1024 * 1024 * 1024;
export const R2_MAX_MULTIPART_PARTS = 10_000;

export type R2Object = { key: string; name: string; size: number | null; created_at: string };
export type R2CompletedPart = { partNumber: number; etag: string };

const env = (...names: string[]) => names.map((n) => process.env[n]?.trim() ?? '').find(Boolean) ?? '';
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
const encode = (value: string) => encodeURIComponent(value).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
const encodeKey = (key: string) => key.split('/').map(encode).join('/');
const safeFilename = (filename: string) => basename(filename).replace(/[\\/]+/g, '_').trim() || `footage_${Date.now()}.mp4`;
export const safeBatchId = (batchId?: string | null) => (batchId ?? '').replace(/[^A-Za-z0-9_-]/g, '_').replace(/^_+|_+$/g, '').slice(0, 80);
export const newBatchId = (now = new Date()) => `batch_${now.toISOString().replace(/[:.]/g, '-').slice(0, 19)}_${Math.random().toString(36).slice(2, 8)}`;
const objectPath = (key = '') => (key ? `/${bucket()}/${encodeKey(key)}` : `/${bucket()}`);

export const r2Basename = (key: string) => basename(key.replace(/\/+$/, ''));

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

function compareSigV4Encoded(left: string, right: string): number {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function canonicalQuery(params: URLSearchParams): string {
  return [...params.entries()]
    .map(([name, value]) => [encode(name), encode(value)] as const)
    .sort(([leftName, leftValue], [rightName, rightValue]) => (
      compareSigV4Encoded(leftName, rightName)
      || compareSigV4Encoded(leftValue, rightValue)
    ))
    .map(([name, value]) => `${name}=${value}`)
    .join('&');
}

function presign(
  method: 'GET' | 'PUT',
  key: string,
  expires = EXPIRES,
  operationQuery = new URLSearchParams(),
): string {
  const host = new URL(endpoint()).host;
  const { dateStamp, timestamp } = amzDate();
  const scope = `${dateStamp}/${REGION}/${SERVICE}/aws4_request`;
  const params = new URLSearchParams(operationQuery);
  params.set('X-Amz-Algorithm', 'AWS4-HMAC-SHA256');
  params.set('X-Amz-Credential', `${accessKey()}/${scope}`);
  params.set('X-Amz-Date', timestamp);
  params.set('X-Amz-Expires', String(expires));
  params.set('X-Amz-SignedHeaders', 'host');
  const canonical = [method, objectPath(key), canonicalQuery(params), `host:${host}\n`, 'host', 'UNSIGNED-PAYLOAD'].join('\n');
  const stringToSign = ['AWS4-HMAC-SHA256', timestamp, scope, sha256Hex(canonical)].join('\n');
  params.set('X-Amz-Signature', createHmac('sha256', signingKey(dateStamp)).update(stringToSign).digest('hex'));
  return `${endpoint()}${objectPath(key)}?${canonicalQuery(params)}`;
}

export function createR2SignedGetUrl(key: string): string {
  return presign('GET', key);
}

export function createR2UploadTarget(
  filename: string,
  requestedBatchId?: string | null,
): { key: string; filename: string; batch_id: string } {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const batchId = safeBatchId(requestedBatchId) || newBatchId();
  const storageName = `${stamp}_${safeFilename(filename)}`;
  const key = `raw/${batchId}/${storageName}`;
  return { key, filename: storageName, batch_id: batchId };
}

export function createR2UploadUrl(filename: string, requestedBatchId?: string | null): { uploadUrl: string; key: string; filename: string; batch_id: string } {
  const target = createR2UploadTarget(filename, requestedBatchId);
  return { uploadUrl: presign('PUT', target.key), ...target };
}

export function createR2UploadUrlForKey(key: string): string {
  if (!key.startsWith('raw/')) throw new Error('Single-PUT upload URLs are limited to raw/ keys');
  return presign('PUT', key);
}

export function createR2MultipartPartUploadUrl(
  key: string,
  multipartUploadId: string,
  partNumber: number,
  expires = MULTIPART_PART_URL_EXPIRES,
): string {
  if (!key.startsWith('raw/')) throw new Error('Multipart part URLs are limited to raw/ keys');
  if (!multipartUploadId.trim()) throw new Error('Multipart upload id is required');
  if (!Number.isInteger(partNumber) || partNumber < 1 || partNumber > R2_MAX_MULTIPART_PARTS) {
    throw new Error(`Multipart part number must be between 1 and ${R2_MAX_MULTIPART_PARTS}`);
  }
  const query = new URLSearchParams({
    partNumber: String(partNumber),
    uploadId: multipartUploadId,
  });
  return presign('PUT', key, expires, query);
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
  const headers: Record<string, string> = {
    host,
    'x-amz-content-sha256': payloadHash,
    'x-amz-date': timestamp,
    ...Object.fromEntries(Object.entries(extraHeaders).map(([k, v]) => [k.toLowerCase(), v])),
  };
  const signedHeaders = Object.keys(headers).sort().join(';');
  const canonicalHeaders = Object.keys(headers).sort().map((k) => `${k}:${headers[k].trim()}\n`).join('');
  const queryString = canonicalQuery(query);
  const canonical = [method, objectPath(key), queryString, canonicalHeaders, signedHeaders, payloadHash].join('\n');
  const stringToSign = ['AWS4-HMAC-SHA256', timestamp, scope, sha256Hex(canonical)].join('\n');
  const signature = createHmac('sha256', signingKey(dateStamp)).update(stringToSign).digest('hex');
  const authorization = `AWS4-HMAC-SHA256 Credential=${accessKey()}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;
  const url = `${endpoint()}${objectPath(key)}${queryString ? `?${queryString}` : ''}`;
  const outbound = { ...headers, Authorization: authorization };
  delete (outbound as Record<string, string>).host;
  return fetch(url, { method, headers: outbound, body });
}

const decodeXml = (value: string) => value.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
const xmlTag = (xml: string, tag: string) => decodeXml(xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`))?.[1] ?? '');
const escapeXml = (value: string) => value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

async function r2ResponseError(label: string, response: Response): Promise<Error> {
  const text = await response.text();
  const code = xmlTag(text, 'Code');
  const message = xmlTag(text, 'Message');
  const detail = [code, message].filter(Boolean).join(': ') || text.slice(0, 300);
  return new Error(`${label} (${response.status})${detail ? `: ${detail}` : ''}`);
}

export async function createR2MultipartUpload(key: string, mimeType = 'application/octet-stream'): Promise<string> {
  if (!key.startsWith('raw/')) throw new Error('Multipart uploads are limited to raw/ keys');
  const response = await signedFetch(
    'POST',
    key,
    new URLSearchParams({ uploads: '' }),
    { 'content-type': mimeType || 'application/octet-stream' },
  );
  if (!response.ok) throw await r2ResponseError('R2 multipart create failed', response);
  const xml = await response.text();
  const uploadId = xmlTag(xml, 'UploadId').trim();
  if (!uploadId) throw new Error('R2 multipart create returned no UploadId');
  return uploadId;
}

export async function completeR2MultipartUpload(
  key: string,
  multipartUploadId: string,
  parts: R2CompletedPart[],
): Promise<{ etag: string | null }> {
  if (!multipartUploadId.trim()) throw new Error('Multipart upload id is required');
  if (!parts.length) throw new Error('Multipart completion requires at least one part');
  const sorted = [...parts].sort((left, right) => left.partNumber - right.partNumber);
  const seen = new Set<number>();
  for (const part of sorted) {
    if (!Number.isInteger(part.partNumber) || part.partNumber < 1 || part.partNumber > R2_MAX_MULTIPART_PARTS) {
      throw new Error(`Invalid multipart part number ${part.partNumber}`);
    }
    if (seen.has(part.partNumber)) throw new Error(`Duplicate multipart part number ${part.partNumber}`);
    if (!part.etag.trim()) throw new Error(`Missing ETag for multipart part ${part.partNumber}`);
    seen.add(part.partNumber);
  }
  const body = `<CompleteMultipartUpload>${sorted.map((part) => (
    `<Part><ETag>${escapeXml(part.etag.trim())}</ETag><PartNumber>${part.partNumber}</PartNumber></Part>`
  )).join('')}</CompleteMultipartUpload>`;
  const response = await signedFetch(
    'POST',
    key,
    new URLSearchParams({ uploadId: multipartUploadId }),
    { 'content-type': 'application/xml' },
    body,
  );
  if (!response.ok) throw await r2ResponseError('R2 multipart completion failed', response);
  const xml = await response.text();
  return { etag: xmlTag(xml, 'ETag').trim() || null };
}

export async function abortR2MultipartUpload(key: string, multipartUploadId: string): Promise<void> {
  if (!multipartUploadId.trim()) throw new Error('Multipart upload id is required');
  const response = await signedFetch(
    'DELETE',
    key,
    new URLSearchParams({ uploadId: multipartUploadId }),
  );
  if (!response.ok && response.status !== 404) {
    throw await r2ResponseError('R2 multipart abort failed', response);
  }
}

export async function listR2Prefix(prefix: string): Promise<R2Object[]> {
  const objects: R2Object[] = [];
  let token = '';
  do {
    const query = new URLSearchParams({ 'list-type': '2', prefix });
    if (token) query.set('continuation-token', token);
    const res = await signedFetch('GET', '', query);
    const text = await res.text();
    if (!res.ok) throw new Error(`R2 list failed (${res.status}): ${text.slice(0, 200)}`);
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
  const copyRes = await signedFetch('PUT', destKey, new URLSearchParams(), { 'x-amz-copy-source': `/${bucket()}/${encodeKey(sourceKey)}` });
  const copyText = await copyRes.text();
  if (!copyRes.ok) throw new Error(`R2 copy failed (${copyRes.status}): ${copyText.slice(0, 200)}`);
  const deleteRes = await signedFetch('DELETE', sourceKey);
  const deleteText = await deleteRes.text();
  if (!deleteRes.ok) throw new Error(`R2 delete failed (${deleteRes.status}): ${deleteText.slice(0, 200)}`);
  return destKey;
}

export async function verifyR2Object(key: string): Promise<{ exists: boolean; size: number | null; status: number }> {
  const res = await signedFetch('HEAD', key);
  return {
    exists: res.ok,
    size: res.ok ? Number(res.headers.get('content-length') ?? '0') : null,
    status: res.status,
  };
}