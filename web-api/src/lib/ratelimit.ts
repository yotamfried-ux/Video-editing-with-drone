import { NextRequest, NextResponse } from 'next/server';
import { Ratelimit } from '@upstash/ratelimit';
import { Redis } from '@upstash/redis';

/**
 * Upstash-backed rate limiting. Serverless functions don't share memory across
 * invocations, so an in-memory limiter is useless on Vercel — a central store
 * (Upstash Redis) is required.
 *
 * If UPSTASH_REDIS_REST_URL/TOKEN are unset (e.g. local dev), limiting is
 * disabled (fail-open) rather than erroring, so the API still runs.
 */
const redis =
  process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN
    ? Redis.fromEnv()
    : null;

const limiters = new Map<string, Ratelimit>();

function getLimiter(name: string, limit: number, windowSec: number): Ratelimit | null {
  if (!redis) return null;
  const key = `${name}:${limit}:${windowSec}`;
  let l = limiters.get(key);
  if (!l) {
    l = new Ratelimit({
      redis,
      limiter: Ratelimit.slidingWindow(limit, `${windowSec} s`),
      prefix: `rl:${name}`,
    });
    limiters.set(key, l);
  }
  return l;
}

function clientIp(req: NextRequest): string {
  const fwd = req.headers.get('x-forwarded-for');
  if (fwd) return fwd.split(',')[0].trim();
  return req.headers.get('x-real-ip') ?? 'unknown';
}

/**
 * Enforce a rate limit for the given route name. Returns a 429 NextResponse
 * when the caller is over the limit, or null when the request may proceed.
 *
 * Usage:
 *   const limited = await enforceRateLimit(req, 'checkout', 10, 60);
 *   if (limited) return limited;
 */
export async function enforceRateLimit(
  req: NextRequest,
  name: string,
  limit: number,
  windowSec: number,
): Promise<NextResponse | null> {
  const limiter = getLimiter(name, limit, windowSec);
  if (!limiter) return null; // limiting disabled (no Redis configured)

  const { success } = await limiter.limit(`${name}:${clientIp(req)}`);
  if (!success) {
    return NextResponse.json({ error: 'Too many requests' }, { status: 429 });
  }
  return null;
}
