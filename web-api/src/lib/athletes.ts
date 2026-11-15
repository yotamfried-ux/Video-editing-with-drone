import { supabaseAdmin } from '@/lib/supabase-admin';

/**
 * Persistent athletes (non-biometric). The pipeline links reels of one athlete inside one session. Across
 * sessions clothing and boards change, so the system only SUGGESTS that two athletes are the same person
 * from their text descriptions; an operator confirms, and only then are they merged.
 */

const STOP_WORDS = new Set([
  'a', 'an', 'the', 'in', 'on', 'of', 'and', 'with', 'at', 'to', 'or', 'is', 'seen', 'wearing',
  'surfer', 'man', 'woman', 'athlete', 'person', 'player', 'rider',
]);

function tokens(description: string): Set<string> {
  return new Set(
    description
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter((word) => word.length > 2 && !STOP_WORDS.has(word)),
  );
}

/** Jaccard similarity of two athlete descriptions, 0..1. Suggestion strength only, never a decision. */
export function descriptionSimilarity(a: string, b: string): number {
  const left = tokens(a);
  const right = tokens(b);
  if (!left.size || !right.size) return 0;
  let shared = 0;
  for (const word of left) if (right.has(word)) shared += 1;
  return shared / (left.size + right.size - shared);
}

export interface AthleteSummary {
  id: string;
  label: string;
  reel_count: number;
  recording_dates: string[];
  follower_count: number;
}

export interface MergeSuggestion {
  a: string;
  b: string;
  similarity: number;
}

export const SUGGESTION_MIN_SIMILARITY = 0.5;

/**
 * Pairs worth an operator's look: similar descriptions and no shared recording date (reels of one session
 * that were not linked by the pipeline were judged different people there).
 */
export function suggestMerges(athletes: AthleteSummary[]): MergeSuggestion[] {
  const out: MergeSuggestion[] = [];
  for (let i = 0; i < athletes.length; i += 1) {
    for (let j = i + 1; j < athletes.length; j += 1) {
      const a = athletes[i];
      const b = athletes[j];
      if (a.recording_dates.some((date) => b.recording_dates.includes(date))) continue;
      const similarity = descriptionSimilarity(a.label, b.label);
      if (similarity >= SUGGESTION_MIN_SIMILARITY) {
        out.push({ a: a.id, b: b.id, similarity: Math.round(similarity * 100) / 100 });
      }
    }
  }
  return out.sort((x, y) => y.similarity - x.similarity).slice(0, 50);
}

/**
 * Tell every follower of `athleteId` about `reelId`, once. The insert into athlete_follow_notifications is the
 * claim: a pair that was already notified conflicts and is skipped. Push failures are swallowed.
 */
export async function notifyFollowers(athleteId: string, reelId: string): Promise<number> {
  const { data: follows } = await supabaseAdmin
    .from('athlete_follows')
    .select('id,user_id')
    .eq('athlete_id', athleteId);
  if (!follows?.length) return 0;
  const { data: reel } = await supabaseAdmin.from('reels').select('token').eq('id', reelId).maybeSingle();
  let notified = 0;
  for (const follow of follows) {
    const { error } = await supabaseAdmin
      .from('athlete_follow_notifications')
      .insert({ follow_id: follow.id, reel_id: reelId });
    if (error) continue;
    notified += 1;
    const { data: pushTokens } = await supabaseAdmin
      .from('push_tokens')
      .select('token')
      .eq('user_id', follow.user_id);
    const messages = (pushTokens ?? [])
      .filter((row) => row.token)
      .map((row) => ({
        to: row.token,
        title: 'New clip of an athlete you follow',
        body: 'A new SportReel clip is ready to preview.',
        data: { screen: 'reel', token: reel?.token ?? null },
      }));
    if (messages.length) {
      await fetch('https://exp.host/--/api/v2/push/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(messages),
      }).catch(() => {});
    }
  }
  return notified;
}
