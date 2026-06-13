import { useState, useEffect } from 'react';
import { apiFetch } from '@/shared/lib/api';

export interface ReelItem {
  id: string;
  token: string;
  sport: string;
  recording_date: string;
  stream_uid: string;
  status: string;
  expires_at: string;
}

export interface Session {
  recording_date: string;
  sport: string;
  reels: ReelItem[];
}

// A date+sport group can span a page boundary — merge its reels into the
// existing session instead of appending a duplicate key (FlatList keys).
function mergeSessions(prev: Session[], next: Session[]): Session[] {
  const merged = prev.map((s) => ({ ...s, reels: [...s.reels] }));
  for (const session of next) {
    const existing = merged.find(
      (s) => s.recording_date === session.recording_date && s.sport === session.sport
    );
    if (existing) {
      const seen = new Set(existing.reels.map((r) => r.id));
      existing.reels.push(...session.reels.filter((r) => !seen.has(r.id)));
    } else {
      merged.push(session);
    }
  }
  return merged;
}

export function useSessions(sport?: string) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);

  const load = async (p = 1) => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ page: String(p), limit: '20' });
      if (sport) qs.set('sport', sport);
      const data = await apiFetch<{ sessions: Session[]; hasMore?: boolean }>(
        `/api/sessions?${qs}`
      );
      if (p === 1) setSessions(data.sessions);
      else setSessions((prev) => mergeSessions(prev, data.sessions));
      setHasMore(data.hasMore ?? data.sessions.length === 20);
      setPage(p);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(1);
  }, [sport]);

  return {
    sessions,
    loading,
    error,
    loadMore: () => load(page + 1),
    hasMore,
    refresh: () => load(1),
  };
}
