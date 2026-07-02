// Minimal Google Drive client for the operator approval flow. Uses the same
// service account as the pipeline (GOOGLE_SERVICE_ACCOUNT_JSON env var holds
// the JSON *contents*). Implemented with plain fetch + node crypto so we don't
// pull the heavy googleapis SDK into the serverless bundle.
import { createSign } from 'crypto';

function b64url(input: Buffer | string): string {
  return Buffer.from(input)
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

let cachedToken: { token: string; expiresAt: number } | null = null;

async function getAccessToken(): Promise<string> {
  if (cachedToken && Date.now() < cachedToken.expiresAt - 60_000) {
    return cachedToken.token;
  }

  const raw = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  if (!raw) throw new Error('GOOGLE_SERVICE_ACCOUNT_JSON not configured');
  const sa = JSON.parse(raw);

  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const claims = b64url(
    JSON.stringify({
      iss: sa.client_email,
      scope: 'https://www.googleapis.com/auth/drive',
      aud: 'https://oauth2.googleapis.com/token',
      iat: now,
      exp: now + 3600,
    })
  );
  const signer = createSign('RSA-SHA256');
  signer.update(`${header}.${claims}`);
  const signature = b64url(signer.sign(sa.private_key));

  const res = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      assertion: `${header}.${claims}.${signature}`,
    }),
  });
  if (!res.ok) {
    throw new Error(`Google token exchange failed (${res.status}): ${(await res.text()).slice(0, 200)}`);
  }
  const data = await res.json();
  cachedToken = { token: data.access_token, expiresAt: Date.now() + data.expires_in * 1000 };
  return cachedToken.token;
}

export interface DriveFile {
  id: string;
  name: string;
  createdTime: string;
  size?: string;
  webViewLink?: string;
  thumbnailLink?: string;
}

export async function getFile(fileId: string): Promise<DriveFile> {
  const token = await getAccessToken();
  const params = new URLSearchParams({
    fields: 'id,name,createdTime,size,webViewLink,thumbnailLink',
    supportsAllDrives: 'true',
  });
  const res = await fetch(`https://www.googleapis.com/drive/v3/files/${fileId}?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`Drive file lookup failed (${res.status}): ${(await res.text()).slice(0, 200)}`);
  }
  return res.json() as Promise<DriveFile>;
}

export async function listFolder(folderId: string): Promise<DriveFile[]> {
  const token = await getAccessToken();
  const params = new URLSearchParams({
    q: `'${folderId}' in parents and trashed = false`,
    fields: 'files(id,name,createdTime,size,webViewLink,thumbnailLink)',
    orderBy: 'createdTime desc',
    pageSize: '100',
    supportsAllDrives: 'true',
    includeItemsFromAllDrives: 'true',
  });
  const res = await fetch(`https://www.googleapis.com/drive/v3/files?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`Drive list failed (${res.status}): ${(await res.text()).slice(0, 200)}`);
  }
  const data = await res.json();
  return data.files ?? [];
}

export async function moveFile(fileId: string, fromFolderId: string, toFolderId: string): Promise<void> {
  const token = await getAccessToken();
  const params = new URLSearchParams({
    addParents: toFolderId,
    removeParents: fromFolderId,
    supportsAllDrives: 'true',
  });
  const res = await fetch(`https://www.googleapis.com/drive/v3/files/${fileId}?${params}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: '{}',
  });
  if (!res.ok) {
    throw new Error(`Drive move failed (${res.status}): ${(await res.text()).slice(0, 200)}`);
  }
}

// Creates a resumable upload session in the given Drive folder and returns the
// upload URL. The caller (mobile app) uploads the file bytes directly to that
// URL — the file never passes through Vercel, so there's no body-size limit.
export async function createUploadSession(
  filename: string,
  folderId: string,
  mimeType = 'video/mp4',
): Promise<string> {
  const token = await getAccessToken();
  const res = await fetch(
    'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true',
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'X-Upload-Content-Type': mimeType,
      },
      body: JSON.stringify({ name: filename, parents: [folderId] }),
    }
  );
  if (!res.ok) {
    throw new Error(`Drive upload init failed (${res.status}): ${(await res.text()).slice(0, 200)}`);
  }
  const uploadUrl = res.headers.get('location');
  if (!uploadUrl) throw new Error('Drive returned no upload URL');
  return uploadUrl;
}
