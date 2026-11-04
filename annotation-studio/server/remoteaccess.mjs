// Optional permanent address (e.g. https://studio.example.com) through a Cloudflare Tunnel to this computer.
// The Studio still listens on 127.0.0.1 only; the tunnel connects from this machine outwards. Requests that arrive
// under the public host are accepted ONLY with a valid Cloudflare Access login (signed JWT, RS256, checked against the
// team's published keys, audience and expiry). If the public host is configured but Access is not, the public host is
// refused (fail closed), so a tunnel without a login in front can never expose the Ground Truth data.
import { createPublicKey, verify } from 'node:crypto';

export function remoteConfig(env = process.env) {
  const host = (env.STUDIO_PUBLIC_HOST ?? '').trim().toLowerCase();
  const team = (env.STUDIO_ACCESS_TEAM ?? '').trim().toLowerCase().replace(/^https?:\/\//, '').replace(/\/.*$/, '');
  const aud = (env.STUDIO_ACCESS_AUD ?? '').trim();
  if (!host) return null;
  if (!/^[a-z0-9.-]+$/.test(host)) throw new Error('STUDIO_PUBLIC_HOST must be a bare host name, e.g. studio.example.com');
  return { host, team, aud, ready: !!(team && aud) };
}

const b64url = s => Buffer.from(s.replace(/-/g, '+').replace(/_/g, '/'), 'base64');
let keyCache = { team: null, at: 0, keys: new Map() };

async function keysFor(team, fetchImpl) {
  if (keyCache.team === team && Date.now() - keyCache.at < 3600_000 && keyCache.keys.size) return keyCache.keys;
  const team_host = team.includes('.') ? team : `${team}.cloudflareaccess.com`;
  const r = await fetchImpl(`https://${team_host}/cdn-cgi/access/certs`);
  if (!r.ok) throw new Error(`access certs ${r.status}`);
  const j = await r.json();
  const keys = new Map((j.keys ?? []).map(k => [k.kid, createPublicKey({ key: k, format: 'jwk' })]));
  keyCache = { team, at: Date.now(), keys };
  return keys;
}

/** Returns the authenticated e-mail, or throws. */
export async function verifyAccessJwt(token, cfg, { fetchImpl = fetch, now = Date.now() } = {}) {
  if (!token) throw new Error('missing Cloudflare Access login');
  const parts = token.split('.');
  if (parts.length !== 3) throw new Error('malformed token');
  const header = JSON.parse(b64url(parts[0]).toString('utf8'));
  const payload = JSON.parse(b64url(parts[1]).toString('utf8'));
  if (header.alg !== 'RS256') throw new Error('unexpected algorithm');
  let keys = await keysFor(cfg.team, fetchImpl);
  if (!keys.has(header.kid)) { keyCache.at = 0; keys = await keysFor(cfg.team, fetchImpl); }   // key rotation
  const key = keys.get(header.kid);
  if (!key) throw new Error('unknown signing key');
  if (!verify('RSA-SHA256', Buffer.from(`${parts[0]}.${parts[1]}`), key, b64url(parts[2]))) throw new Error('bad signature');
  const auds = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!auds.includes(cfg.aud)) throw new Error('wrong audience');
  const t = Math.floor(now / 1000);
  if (typeof payload.exp !== 'number' || payload.exp < t - 30) throw new Error('expired');
  if (typeof payload.nbf === 'number' && payload.nbf > t + 30) throw new Error('not yet valid');
  const team_host = cfg.team.includes('.') ? cfg.team : `${cfg.team}.cloudflareaccess.com`;
  if (payload.iss && payload.iss !== `https://${team_host}`) throw new Error('wrong issuer');
  return payload.email ?? payload.sub ?? 'unknown';
}

export const __resetKeyCache = () => { keyCache = { team: null, at: 0, keys: new Map() }; };
