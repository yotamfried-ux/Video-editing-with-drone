import { NextRequest, NextResponse } from 'next/server';
import { Ratelimit } from '@upstash/ratelimit';
import { Redis } from '@upstash/redis';
import { supabaseAdmin } from '@/lib/supabase-admin';

/**
 * Centralized rate limiting for Vercel serverless functions.
 *
 * Production defaults to Supabase, which is already a required shared backend
 * for the API. Upstash remains an optional backend for explicit opt-in via
 * RATE_LIMIT_BACKEND=upstash. If that backend fails and Supabase is available,
 * enforcement falls back to the Supabase RPC rather than returning an opaque 500.
 *
 * Local development may omit all central backend configuration; in that case
 * limiting is disabled as before.
 */
const redis =
  process.env.UPSTASH_REDIS_REST_URL && process.env.UPSTASH_REDIS_REST_TOKEN
    ? Redis.fromEnv()
    : null;

const limiters = new Map<string, Ratelimit>();

function getUpstashLimiter(name: string, limit: number, windowSec: number): Ratelimit | null {
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

function hasSupabaseRateLimitBackend(): boolean {
  return Boolean(
    process.env.SUPABASE_URL?.trim()
      && process.env.SUPABASE_SERVICE_KEY?.trim(),
  );
}

function clientIp(req: NextRequest): string {
  const forwarded = req.headers.get('x-forwarded-for');
  if (forwarded) return forwarded.split(',')[0].trim();
  return req.headers.get('x-real-ip') ?? 'unknown';
}

async function enforceViaSupabase(
  key: string,
  limit: number,
  windowSec: number,
): Promise<boolean> {
  const { data, error } = await supabaseAdmin.rpc('consume_api_rate_limit', {
    p_key: key,
    p_limit: limit,
    p_window_seconds: windowSec,
  });

  if (error) {
    throw new Error(`Supabase rate-limit RPC failed: ${error.message}`);
  }

  const row = Array.isArray(data) ? data[0] : data;
  if (!row || typeof (row as { allowed?: unknown }).allowed !== 'boolean') {
    throw new Error('Supabase rate-limit RPC returned an invalid payload');
  }

  return (row as { allowed: boolean }).allowed;
}

async function enforceViaUpstash(
  name: string,
  identity: string,
  limit: number,
  windowSec: number,
): Promise<boolean> {
  const limiter = getUpstashLimiter(name, limit, windowSec);
  if (!limiter) {
    throw new Error('Upstash rate-limit backend is not configured');
  }
  const { success } = await limiter.limit(`${name}:${identity}`);
  return success;
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
  const identity = subject?.trim() || clientIp(req);
  const key = `${name}:${identity}`;
  const backend = (process.env.RATE_LIMIT_BACKEND ?? 'supabase').trim().toLowerCase();

  try {
    let allowed: boolean;

    if (backend === 'upstash') {
      try {
        allowed = await enforceViaUpstash(name, identity, limit, windowSec);
      } catch (upstashError) {
        if (!hasSupabaseRateLimitBackend()) throw upstashError;
        console.warn('Upstash rate limiting failed; falling back to Supabase.');
        allowed = await enforceViaSupabase(key, limit, windowSec);
      }
    } else if (hasSupabaseRateLimitBackend()) {
      allowed = await enforceViaSupabase(key, limit, windowSec);
    } else {
      // Preserve local-development behavior when no shared backend is configured.
      return null;
    }

    if (!allowed) {
      return NextResponse.json({ error: 'Too many requests' }, { status: 429 });
    }
    return null;
  } catch (error) {
    console.error(
      'Rate limit backend unavailable',
      error instanceof Error ? error.message : String(error),
    );
    return NextResponse.json(
      { error: 'Rate limit service unavailable' },
      { status: 503 },
    );
  }
}
