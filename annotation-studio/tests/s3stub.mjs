// Minimal in-memory S3 server for tests: verifies SigV4 + payload/checksum headers, supports ranges, multipart,
// ListObjectsV2 pagination, and fault injection. Records every request so tests can assert what was (never) called.
import http from 'node:http';
import { createHash, randomUUID } from 'node:crypto';
import { signRequest, sha256hex } from '../server/sigv4.mjs';

export async function startS3Stub({ accessKeyId = 'AKIATESTKEY', secretAccessKey = 'test-secret-do-not-use', bucket = 'gt-archive', region = 'auto' } = {}) {
  const objects = new Map(), uploads = new Map(), log = [];
  const faults = { failPuts: 0, corruptNextPut: false, outage: false };
  const server = http.createServer(async (req, res) => {
    const chunks = []; for await (const c of req) chunks.push(c);
    let body = Buffer.concat(chunks);
    const url = new URL(req.url, `http://${req.headers.host}`);
    const entry = { method: req.method, path: url.pathname, query: url.search };
    log.push(entry);
    const send = (status, text = '', headers = {}) => { res.writeHead(status, headers); res.end(text); };
    if (faults.outage) return send(503, 'down');
    // ---- SigV4 verification (recompute from what arrived) ----
    const auth = /Credential=([^/]+)\/[^,]+, SignedHeaders=([^,]+), Signature=([0-9a-f]+)/.exec(req.headers.authorization ?? '');
    if (!auth || auth[1] !== accessKeyId) return send(403, 'InvalidAccessKeyId');
    const signedNames = auth[2].split(';').filter(n => n !== 'host' && n !== 'x-amz-date' && n !== 'x-amz-content-sha256');
    const hdrs = Object.fromEntries(signedNames.map(n => [n, req.headers[n]]));
    const expect = signRequest({ method: req.method, url: `http://${req.headers.host}${req.url}`, headers: hdrs, payloadHash: req.headers['x-amz-content-sha256'],
      region, accessKeyId, secretAccessKey, amzDate: req.headers['x-amz-date'] });
    if (!expect.authorization.endsWith(auth[3])) return send(403, 'SignatureDoesNotMatch');
    const m = new RegExp(`^/${bucket}/?(.*)$`).exec(decodeURIComponent(url.pathname));
    if (!m) return send(404, 'NoSuchBucket');
    const key = m[1], q = url.searchParams;
    const isPut = req.method === 'PUT';
    if (isPut && faults.failPuts > 0) { faults.failPuts--; return send(500, 'InternalError'); }
    if (isPut && faults.corruptNextPut) { faults.corruptNextPut = false; body = Buffer.from(body); body[0] ^= 0xff; }
    if (isPut || (req.method === 'POST' && q.has('uploadId'))) {
      const declared = req.headers['x-amz-content-sha256'];
      if (declared && declared !== 'UNSIGNED-PAYLOAD' && declared !== sha256hex(body)) return send(400, '<Error><Code>XAmzContentSHA256Mismatch</Code></Error>');
      const ck = req.headers['x-amz-checksum-sha256'];
      if (ck && ck !== createHash('sha256').update(body).digest('base64')) return send(400, '<Error><Code>BadDigest</Code></Error>');
    }
    if (req.method === 'POST' && q.has('uploads')) { const id = randomUUID(); uploads.set(id, { key, parts: new Map() }); return send(200, `<InitiateMultipartUploadResult><UploadId>${id}</UploadId></InitiateMultipartUploadResult>`); }
    if (isPut && q.has('uploadId')) {
      const u = uploads.get(q.get('uploadId')); if (!u) return send(404, 'NoSuchUpload');
      u.parts.set(Number(q.get('partNumber')), body); return send(200, '', { etag: `"${sha256hex(body).slice(0, 32)}"` });
    }
    if (req.method === 'POST' && q.has('uploadId')) {
      const u = uploads.get(q.get('uploadId')); if (!u) return send(404, 'NoSuchUpload');
      const nums = [...String(body).matchAll(/<PartNumber>(\d+)<\/PartNumber>/g)].map(x => Number(x[1]));
      objects.set(key, { data: Buffer.concat(nums.map(n => u.parts.get(n))) }); uploads.delete(q.get('uploadId')); return send(200, '<CompleteMultipartUploadResult/>');
    }
    if (req.method === 'DELETE' && q.has('uploadId')) { uploads.delete(q.get('uploadId')); return send(204); }
    if (req.method === 'DELETE') { entry.objectDelete = true; objects.delete(key); return send(204); }
    if (isPut) { objects.set(key, { data: body }); return send(200, '', { etag: `"${sha256hex(body).slice(0, 32)}"` }); }
    if (req.method === 'GET' && key === '' && q.has('uploads')) {
      return send(200, `<ListMultipartUploadsResult>${[...uploads].map(([id, u]) => `<Upload><Key>${u.key}</Key><UploadId>${id}</UploadId></Upload>`).join('')}</ListMultipartUploadsResult>`);
    }
    if (req.method === 'GET' && key === '' && q.get('list-type') === '2') {
      const prefix = q.get('prefix') ?? '', all = [...objects].filter(([k]) => k.startsWith(prefix)).sort(([a], [b]) => a < b ? -1 : 1);
      const start = Number(q.get('continuation-token') ?? 0), page = all.slice(start, start + 2), more = start + 2 < all.length;
      return send(200, `<ListBucketResult>${page.map(([k, o]) => `<Contents><Key>${k}</Key><Size>${o.data.length}</Size></Contents>`).join('')}${more ? `<NextContinuationToken>${start + 2}</NextContinuationToken>` : ''}</ListBucketResult>`);
    }
    if (req.method === 'GET' || req.method === 'HEAD') {
      const o = objects.get(key); if (!o) return send(404, 'NoSuchKey');
      const r = /bytes=(\d+)-(\d*)/.exec(req.headers.range ?? '');
      if (r && req.method === 'GET') { const a = Number(r[1]), b = r[2] === '' ? o.data.length - 1 : Number(r[2]); return send(206, o.data.subarray(a, b + 1), { 'content-range': `bytes ${a}-${b}/${o.data.length}` }); }
      res.writeHead(200, { 'content-length': o.data.length }); return res.end(req.method === 'GET' ? o.data : undefined);
    }
    return send(400, 'unsupported');
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  return { url: `http://127.0.0.1:${server.address().port}`, bucket, accessKeyId, secretAccessKey, objects, uploads, log, faults,
    close: () => { server.closeAllConnections(); server.close(); } };
}
