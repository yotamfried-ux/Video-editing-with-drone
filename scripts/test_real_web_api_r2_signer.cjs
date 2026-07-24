#!/usr/bin/env node
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const MIB = 1024 * 1024;

function required(name) {
  const value = String(process.env[name] || '').trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function deterministicPart(partNumber, size) {
  const seed = crypto.createHash('sha256').update(`sportreel-web-api-r2-part-${partNumber}`).digest();
  const output = Buffer.allocUnsafe(size);
  for (let offset = 0; offset < size; offset += seed.length) {
    seed.copy(output, offset, 0, Math.min(seed.length, size - offset));
  }
  return output;
}

function writeEvidence(evidencePath, evidence) {
  fs.mkdirSync(path.dirname(evidencePath), { recursive: true });
  fs.writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
}

async function main() {
  const modulePath = required('R2_STORAGE_MODULE');
  const evidencePath = required('R2_WEB_API_EVIDENCE_PATH');
  const r2 = require(modulePath);
  const runId = String(process.env.GITHUB_RUN_ID || 'local').replace(/[^A-Za-z0-9_-]/g, '_');
  const key = `raw/integration_web_api_probe/${runId}_${crypto.randomUUID()}.bin`;
  const parts = [deterministicPart(1, 5 * MIB), deterministicPart(2, 1 * MIB)];
  const expectedSize = parts.reduce((sum, part) => sum + part.byteLength, 0);
  const expectedHash = crypto.createHash('sha256').update(Buffer.concat(parts)).digest('hex');
  const evidence = {
    protocol: 'sportreel_web_api_r2_signer_probe_v1',
    key,
    expected_size_bytes: expectedSize,
    expected_sha256: expectedHash,
    parts: [],
    probe_succeeded: false,
    abort_cleanup: 'not_required',
    object_cleanup: 'pending',
  };
  writeEvidence(evidencePath, evidence);

  let uploadId = null;
  let primaryError = null;
  try {
    uploadId = await r2.createR2MultipartUpload(key, 'application/octet-stream');
    evidence.upload_id_prefix = uploadId.slice(0, 12);

    const completed = [];
    for (let index = 0; index < parts.length; index += 1) {
      const partNumber = index + 1;
      const uploadUrl = r2.createR2MultipartPartUploadUrl(key, uploadId, partNumber, 900);
      const response = await fetch(uploadUrl, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: parts[index],
      });
      if (!response.ok) {
        throw new Error(`Web API signed part ${partNumber} failed with HTTP ${response.status}`);
      }
      const etag = String(response.headers.get('etag') || '').trim();
      if (!etag) throw new Error(`Web API signed part ${partNumber} returned no ETag`);
      completed.push({ partNumber, etag });
      evidence.parts.push({ part_number: partNumber, size_bytes: parts[index].byteLength, etag_present: true });
    }

    await r2.completeR2MultipartUpload(key, uploadId, completed);
    uploadId = null;

    const head = await r2.verifyR2Object(key);
    if (!head.exists || head.status < 200 || head.status >= 300 || head.size !== expectedSize) {
      throw new Error(`Web API signed HEAD mismatch: ${JSON.stringify(head)}`);
    }

    const getResponse = await fetch(r2.createR2SignedGetUrl(key));
    if (!getResponse.ok) throw new Error(`Web API signed GET failed with HTTP ${getResponse.status}`);
    const downloaded = Buffer.from(await getResponse.arrayBuffer());
    const actualHash = crypto.createHash('sha256').update(downloaded).digest('hex');
    if (downloaded.byteLength !== expectedSize || actualHash !== expectedHash) {
      throw new Error('Web API signed GET bytes do not match the uploaded source');
    }

    evidence.head_size_bytes = head.size;
    evidence.download_size_bytes = downloaded.byteLength;
    evidence.download_sha256 = actualHash;
    evidence.probe_succeeded = true;
    console.log(`PASS: Web API R2 signer create/part/complete/HEAD/GET for ${key}`);
  } catch (error) {
    primaryError = error;
    evidence.error = error instanceof Error ? error.message : String(error);
  } finally {
    if (uploadId) {
      try {
        await r2.abortR2MultipartUpload(key, uploadId);
        evidence.abort_cleanup = 'confirmed';
      } catch (abortError) {
        evidence.abort_cleanup = 'failed';
        evidence.abort_error = abortError instanceof Error ? abortError.message : String(abortError);
        if (!primaryError) primaryError = abortError;
      }
    }
    writeEvidence(evidencePath, evidence);
  }

  if (primaryError) throw primaryError;
  if (!evidence.probe_succeeded) throw new Error('Web API R2 signer probe did not reach verified completion');
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
