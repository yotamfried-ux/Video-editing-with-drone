import { createHash, createHmac } from 'crypto';
import { basename } from 'path';

import {
  MULTIPART_PROTOCOL_VERSION,
  chooseMultipartPartSize,
  expectedMultipartPartCount,
  normalizeCompletedParts,
} from './multipart-policy.mjs';
import type { MultipartPartInput, NormalizedMultipartPart } from './multipart-policy.mjs';

export {
  DEFAULT_PART_SIZE_BYTES,
  MAX_MULTIPART_PARTS,
  MIN_PART_SIZE_BYTES,
  MULTIPART_PROTOCOL_VERSION,
  chooseMultipartPartSize,
  expectedMultipartPartCount,
  expectedPartSize,
  normalizeCompletedParts,
} from './multipart-policy.mjs';
export type { MultipartPartInput, NormalizedMultipartPart } from './multipart-policy.mjs';

const REGION = 'auto';
const SERVICE = 's3';
const DEFAULT_BUCKET = 'sportreel';
const EXPIRES = 3600;
const PART_URL_EXPIRES = 15 * 60;

type R2Method = 'GET' | 'PUT' | 'POST' | 'DELETE' | 'HEAD';

export type R2Object = { key: string; name: string; size: number | null; created_at: string };
export type R2MultipartUpload = {
  uploadId: string;
  key: string;
  protocolVersion: typeof MULTIPART_PROTOCOL_VERSION;
};
export type R2MultipartPart = { PartNumber: number; ETag: string; sizeBytes: number };

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
const sha256Hex = (value: string | Buffer) => createHash('sha256').update(value).digest('hex');
const encode = (value: string) => encodeURIComponent(value).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
const encodeKey = (key: string) => key.split('/').map(encode).join('/');
const safeFilename = (filename: string) => basename(filename).replace(/[\\/]+/g, '_').trim() || `footage_${Date.now()}.mp4`;
export const safeBatchId = (batchId?: string | null) => (batchId ?? '').replace(/[^A-Za-z0-9_-]/g, '_').replace(/^_+|_+$/g, '').slice(0, 80);
export const newBatchId = (now = new Date()) => `batch_${now.toISOString().replace(/[:.]/g, '-').slice(0, 19)}_${Math.random().toString(36).slice(2, 8)}`;
const objectPath = (key = '') => (key ? `/${bucket()}/${encodeKey(key)}` : `/${bucket()}`);

export const r2Basename = (key: string) => basename(key.replace(/\/+$/, ''));

export function newR2RawObjectKey(filename: string, requestedBatchId?: string | null): { key: string; filename: string; batch_id: string } {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const batchId = safeBatchId(requestedBatchId) || newBatchId();
  const storageName = `${stamp}_${safeFilename(filename)}`;
  return { key: `raw/${batchId}/${storageName}`, filename: storageName, batch_id: batchId };
}

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
  return [...params.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${encode(k)}=${encode(v)}`).join('&');
}

function presign(method: R2Method, key: string, baseQuery = new URLSearchParams(), expires = EXPIRES): string {
  const host = new URL(endpoint()).host;
  const { dateStamp, timestamp } = amzDate();
  const scope = `${dateStamp}/${REGION}/${SERVICE}/aws4_request`;
  const params = new URLSearchParams(baseQuery);
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

export function createR2UploadUrl(filename: string, requestedBatchId?: string | null): { uploadUrl: string; key: string; filename: string; batch_id: string } {
  const object = newR2RawObjectKey(filename, requestedBatchId);
  return { uploadUrl: presign('PUT', object.key), ...object };
}

async function signedFetch(
  method: R2Method,
  key: string,
  query = new URLSearchParams(),
  extraHeaders: Record<string, string> = {},
  body?: string,
) {
  const host = new URL(endpoint()).host;
  const { dateStamp, timestamp } = amzDate();
  const scope = `${dateStamp}/${REGION}/${SERVICE}/aws4_request`;
  const payloadHash = sha256Hex(body ?? '');
  const headers: Record<string, string> = {
    host,
    'x-amz-content-sha256': payloadHash,
    'x-amz-date': timestamp,
    ...Object.fromEntries(Object.entries(extraHeaders).map(([k, v]) => [k.toLowerCase(), v])),
  };
  const signedHeaders = Object.keys(headers).sort().join(';');
  const canonicalHeaders = Object.keys(headers).sort().map((k) => `${k}:${headers[k].trim()}\n`).join('');
  const canonical = [method, objectPath(key), canonicalQuery(query), canonicalHeaders, signedHeaders, payloadHash].join('\n');
  const stringToSign = ['AWS4-HMAC-SHA256', timestamp, scope, sha256Hex(canonical)].join('\n');
  const signature = createHmac('sha256', signingKey(dateStamp)).update(stringToSign).digest('hex');
  const authorization = `AWS4-HMAC-SHA256 Credential=${accessKey()}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;
  const url = `${endpoint()}${objectPath(key)}${query.toString() ? `?${query.toString()}` : ''}`;
  const outbound = { ...headers, Authorization: authorization };
  delete (outbound as Record<string, string>).host;
  return fetch(url, { method, headers: outbound, ...(body === undefined ? {} : { body }) });
}

const decodeXml = (value: string) => value.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
const xmlTag = (xml: string, tag: string) => decodeXml(xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`))?.[1] ?? '');
const escapeXml = (value: string) => value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

export async function createR2MultipartUpload(key: string, mimeType: string): Promise<R2MultipartUpload> {
  const query = new URLSearchParams({ uploads: '' });
  const res = await signedFetch('POST', key, query, { 'content-type': mimeType || 'application/octet-stream' });
  const text = await res.text();
  if (!res.ok) throw new Error(`R2 multipart create failed (${res.status}): ${text.slice(0, 300)}`);
  const uploadId = xmlTag(text, 'UploadId');
  if (!uploadId) throw new Error('R2 multipart create response is missing UploadId');
  return { uploadId, key, protocolVersion: MULTIPART_PROTOCOL_VERSION };
}

export function createR2MultipartPartUrl(key: string, uploadId: string, partNumber: number, expires = PART_URL_EXPIRES): string {
  if (!uploadId.trim()) throw new Error('uploadId required');
  if (!Number.isSafeInteger(partNumber) || partNumber < 1 || partNumber > 10_000) throw new Error('partNumber must be between 1 and 10000');
  const query = new URLSearchParams({ partNumber: String(partNumber), uploadId });
  return presign('PUT', key, query, expires);
}

export async function listR2MultipartParts(key: string, uploadId: string): Promise<R2MultipartPart[]> {
  const parts: R2MultipartPart[] = [];
  let partNumberMarker = '';
  do {
    const query = new URLSearchParams({ uploadId });
    if (partNumberMarker) query.set('part-number-marker', partNumberMarker);
    const res = await signedFetch('GET', key, query);
    const text = await res.text();
    if (!res.ok) throw new Error(`R2 multipart list-parts failed (${res.status}): ${text.slice(0, 300)}`);
    for (const match of text.matchAll(/<Part>([\s\S]*?)<\/Part>/g)) {
      const PartNumber = Number(xmlTag(match[1], 'PartNumber'));
      const ETag = xmlTag(match[1], 'ETag');
      const sizeBytes = Number(xmlTag(match[1], 'Size'));
      if (PartNumber > 0 && ETag && Number.isSafeInteger(sizeBytes) && sizeBytes >= 0) {
        parts.push({ PartNumber, ETag, sizeBytes });
      }
    }
    const truncated = xmlTag(text, 'IsTruncated') === 'true';
    partNumberMarker = truncated ? xmlTag(text, 'NextPartNumberMarker') : '';
  } while (partNumberMarker);
  parts.sort((a, b) => a.PartNumber - b.PartNumber);
  return parts;
}

export async function completeR2MultipartUpload(
  key: string,
  uploadId: string,
  parts: MultipartPartInput[],
  sourceSizeBytes: number,
  partSizeBytes: number,
): Promise<{ etag: string | null; parts: NormalizedMultipartPart[] }> {
  const normalized = normalizeCompletedParts(parts, sourceSizeBytes, partSizeBytes);
  const xml = `<CompleteMultipartUpload>${normalized.map((part) => `<Part><PartNumber>${part.PartNumber}</PartNumber><ETag>${escapeXml(part.ETag)}</ETag></Part>`).join('')}</CompleteMultipartUpload>`;
  const query = new URLSearchParams({ uploadId });
  const res = await signedFetch('POST', key, query, { 'content-type': 'application/xml' }, xml);
  const text = await res.text();
  if (!res.ok || /<Error(?:>|\s)/.test(text)) {
    throw new Error(`R2 multipart complete failed (${res.status}): ${text.slice(0, 500)}`);
  }
  return { etag: xmlTag(text, 'ETag') || null, parts: normalized };
}

export async function abortR2MultipartUpload(key: string, uploadId: string): Promise<void> {
  const query = new URLSearchParams({ uploadId });
  const res = await signedFetch('DELETE', key, query);
  const text = await res.text();
  if (!res.ok && res.status !== 404) throw new Error(`R2 multipart abort failed (${res.status}): ${text.slice(0, 300)}`);
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
