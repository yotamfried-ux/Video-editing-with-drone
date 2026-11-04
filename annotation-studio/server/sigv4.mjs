// AWS Signature Version 4 (header auth) — dependency-free, used for S3-compatible storage (Cloudflare R2).
import { createHash, createHmac } from 'node:crypto';

const hmac = (key, data) => createHmac('sha256', key).update(data).digest();
export const sha256hex = data => createHash('sha256').update(data).digest('hex');
const enc = s => encodeURIComponent(s).replace(/[!'()*]/g, c => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
const encPath = p => p.split('/').map(enc).join('/');

export function amzDateNow(d = new Date()) { return d.toISOString().replace(/[:-]|\.\d{3}/g, ''); }

/** Returns the headers to send (including Authorization). Exact AWS algorithm; verified against the published AWS example. */
export function signRequest({ method, url, headers = {}, payloadHash, region, service = 's3', accessKeyId, secretAccessKey, amzDate = amzDateNow() }) {
  const u = new URL(url);
  const date = amzDate.slice(0, 8);
  const all = { ...headers, host: u.host, 'x-amz-date': amzDate };
  if (payloadHash != null && service === 's3') all['x-amz-content-sha256'] = payloadHash;
  const names = Object.keys(all).map(k => k.toLowerCase()).sort();
  const lower = Object.fromEntries(Object.entries(all).map(([k, v]) => [k.toLowerCase(), String(v).trim().replace(/\s+/g, ' ')]));
  const query = [...u.searchParams.entries()].map(([k, v]) => [enc(k), enc(v)]).sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : 1)
    .map(([k, v]) => `${k}=${v}`).join('&');
  const canonical = [method, encPath(decodeURIComponent(u.pathname)), query, names.map(n => `${n}:${lower[n]}\n`).join(''), names.join(';'), payloadHash ?? sha256hex('')].join('\n');
  const scope = `${date}/${region}/${service}/aws4_request`;
  const toSign = ['AWS4-HMAC-SHA256', amzDate, scope, sha256hex(canonical)].join('\n');
  const key = hmac(hmac(hmac(hmac(`AWS4${secretAccessKey}`, date), region), service), 'aws4_request');
  const signature = createHmac('sha256', key).update(toSign).digest('hex');
  return { ...all, authorization: `AWS4-HMAC-SHA256 Credential=${accessKeyId}/${scope}, SignedHeaders=${names.join(';')}, Signature=${signature}`, _canonical: canonical };
}

/**
 * Pre-signed GET URL (query-string auth, UNSIGNED-PAYLOAD, signed header: host). Lets the browser read one object for a
 * limited time without the credentials ever leaving the server; read-only by construction (the method is part of the
 * signature). Verified against the AWS published presigned-URL example.
 */
export function presignUrl({ method = 'GET', url, region, service = 's3', accessKeyId, secretAccessKey, expires = 3600, amzDate = amzDateNow() }) {
  const u = new URL(url);
  const date = amzDate.slice(0, 8);
  const scope = `${date}/${region}/${service}/aws4_request`;
  const params = [...u.searchParams.entries(),
    ['X-Amz-Algorithm', 'AWS4-HMAC-SHA256'], ['X-Amz-Credential', `${accessKeyId}/${scope}`], ['X-Amz-Date', amzDate],
    ['X-Amz-Expires', String(expires)], ['X-Amz-SignedHeaders', 'host']];
  const query = params.map(([k, v]) => [enc(k), enc(v)]).sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : 1).map(([k, v]) => `${k}=${v}`).join('&');
  const canonical = [method, encPath(decodeURIComponent(u.pathname)), query, `host:${u.host}\n`, 'host', 'UNSIGNED-PAYLOAD'].join('\n');
  const toSign = ['AWS4-HMAC-SHA256', amzDate, scope, sha256hex(canonical)].join('\n');
  const key = hmac(hmac(hmac(hmac(`AWS4${secretAccessKey}`, date), region), service), 'aws4_request');
  const signature = createHmac('sha256', key).update(toSign).digest('hex');
  return `${u.origin}${encPath(decodeURIComponent(u.pathname))}?${query}&X-Amz-Signature=${signature}`;
}
