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
  let limiter = limiters.get(key);
  if (!limiter) {
    limiter = new Ratelimit({
      redis,
      limiter: Ratelimit.slidingWindow(limit, `${windowSec} s`),
      prefix: `rl:${name}`,
    });
    limiters.set(key, limiter);
  }
  return limiter;
}

function clientIp(req: NextRequest): string {
  const forwarded = req.headers.get('x-forwarded-for');
  if (forwarded) return forwarded.split(',')[0].trim();
  return req.headers.get('x-real-ip') ?? 'unknown';
}

/**
 * Enforce a rate limit for the given route name. `subject` scopes high-volume,
 * authenticated operations such as multipart part URLs to one durable upload
 * rather than making unrelated files behind the same mobile IP consume one cap.
 */
export async function enforceRateLimit(
  req: NextRequest,
  name: string,
  limit: number,
  windowSec: number,
  subject?: string,
): Promise<NextResponse | null> {
  const limiter = getLimiter(name, limit, windowSec);
  if (!limiter) return null;
  const identity = subject?.trim() || clientIp(req);
  const { success } = await limiter.limit(`${name}:${identity}`);
  if (!success) {
    return NextResponse.json({ error: 'Too many requests' }, { status: 429 });
  }
  return null;
}
