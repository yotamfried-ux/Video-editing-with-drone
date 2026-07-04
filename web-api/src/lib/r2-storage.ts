import { createHash, createHmac } from 'crypto';
import { basename } from 'path';

const REGION = 'auto';
const SERVICE = 's3';
const DEFAULT_BUCKET = 'sportreel';
const EXPIRES = 3600;

export type R2Object = { key: string; name: string; size: number | null; created_at: string };

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

function canonicalQuery(params: URLSearchParams): string {
  return [...params.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${encode(k)}=${encode(v)}`).join('&');
}

function presign(method: 'GET' | 'PUT', key: string, expires = EXPIRES): string {
  const host = new URL(endpoint()).host;
  const { dateStamp, timestamp } = amzDate();
  const scope = `${dateStamp}/${REGION}/${SERVICE}/aws4_request`;
  const params = new URLSearchParams({
    'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
    'X-Amz-Credential': `${accessKey()}/${scope}`,
    'X-Amz-Date': timestamp,
    'X-Amz-Expires': String(expires),
    'X-Amz-SignedHeaders': 'host',
  });
  const canonical = [method, objectPath(key), canonicalQuery(params), `host:${host}\n`, 'host', 'UNSIGNED-PAYLOAD'].join('\n');
  const stringToSign = ['AWS4-HMAC-SHA256', timestamp, scope, sha256Hex(canonical)].join('\n');
  params.set('X-Amz-Signature', createHmac('sha256', signingKey(dateStamp)).update(stringToSign).digest('hex'));
  return `${endpoint()}${objectPath(key)}?${canonicalQuery(params)}`;
}

export function createR2SignedGetUrl(key: string): string {
  return presign('GET', key);
}

export function createR2UploadUrl(filename: string): { uploadUrl: string; key: string; filename: string } {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const storageName = `${stamp}_${safeFilename(filename)}`;
  const key = `raw/${storageName}`;
  return { uploadUrl: presign('PUT', key), key, filename: storageName };
}

async function signedFetch(method: string, key: string, query = new URLSearchParams(), extraHeaders: Record<string, string> = {}) {
  const host = new URL(endpoint()).host;
  const { dateStamp, timestamp } = amzDate();
  const scope = `${dateStamp}/${REGION}/${SERVICE}/aws4_request`;
  const headers: Record<string, string> = {
    host,
    'x-amz-content-sha256': 'UNSIGNED-PAYLOAD',
    'x-amz-date': timestamp,
    ...Object.fromEntries(Object.entries(extraHeaders).map(([k, v]) => [k.toLowerCase(), v])),
  };
  const signedHeaders = Object.keys(headers).sort().join(';');
  const canonicalHeaders = Object.keys(headers).sort().map((k) => `${k}:${headers[k].trim()}\n`).join('');
  const canonical = [method, objectPath(key), canonicalQuery(query), canonicalHeaders, signedHeaders, 'UNSIGNED-PAYLOAD'].join('\n');
  const stringToSign = ['AWS4-HMAC-SHA256', timestamp, scope, sha256Hex(canonical)].join('\n');
  const signature = createHmac('sha256', signingKey(dateStamp)).update(stringToSign).digest('hex');
  const authorization = `AWS4-HMAC-SHA256 Credential=${accessKey()}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;
  const url = `${endpoint()}${objectPath(key)}${query.toString() ? `?${query.toString()}` : ''}`;
  const outbound = { ...headers, Authorization: authorization };
  delete (outbound as Record<string, string>).host;
  return fetch(url, { method, headers: outbound });
}

const decodeXml = (value: string) => value.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
const xmlTag = (xml: string, tag: string) => decodeXml(xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`))?.[1] ?? '');

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
