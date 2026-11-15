/**
 * Cross-session athlete suggestions are suggestions: similar descriptions on different recording dates.
 * Run: npx -y tsx --test scripts/athletes.test.ts   (from web-api/)
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { descriptionSimilarity, suggestMerges, type AthleteSummary } from '../src/lib/athletes';

const athlete = (id: string, label: string, dates: string[]): AthleteSummary => ({
  id, label, recording_dates: dates, reel_count: dates.length, follower_count: 0,
});

test('similar descriptions score high, different ones low, empty ones zero', () => {
  const a = 'Man with long hair and a beard in a black sleeveless top on a white longboard';
  assert.ok(descriptionSimilarity(a, 'Surfer with long hair and beard, black sleeveless wetsuit, white longboard') >= 0.5);
  assert.ok(descriptionSimilarity(a, 'Woman in a red hooded rash guard on a tan longboard') < 0.3);
  assert.equal(descriptionSimilarity(a, ''), 0);
  assert.equal(descriptionSimilarity('surfer', 'man'), 0);
});

test('only pairs from different sessions are suggested, strongest first', () => {
  const list = [
    athlete('a', 'Man with long hair and a beard in a black sleeveless top on a white longboard', ['2026-07-20']),
    athlete('b', 'Man with long hair and beard, black sleeveless top, white longboard', ['2026-07-24']),
    athlete('c', 'Man with long hair and a beard in a black sleeveless top on a white longboard', ['2026-07-20']),
    athlete('d', 'Woman in a red hooded rash guard on a tan longboard', ['2026-07-24']),
  ];
  const pairs = suggestMerges(list).map((s) => `${s.a}+${s.b}`);
  assert.ok(pairs.includes('a+b') && pairs.includes('b+c'));
  assert.ok(!pairs.includes('a+c'), 'two athletes of one session were already judged different people');
  assert.ok(!pairs.some((p) => p.includes('d')));
  const scores = suggestMerges(list).map((s) => s.similarity);
  assert.deepEqual(scores, [...scores].sort((x, y) => y - x));
});
