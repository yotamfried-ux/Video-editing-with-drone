import React, { useCallback, useEffect, useState } from 'react';
import { Alert, ScrollView, StyleSheet, View } from 'react-native';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import { Colors, Spacing } from '@/shared/constants/theme';

interface Athlete {
  id: string;
  label: string;
  reel_count: number;
  recording_dates: string[];
  follower_count: number;
}

interface Suggestion {
  a: string;
  b: string;
  similarity: number;
}

/**
 * Athletes on Discover. Reels of one athlete in one session are linked by the pipeline. Whether an athlete
 * of another day is the same person is the operator's call: the system only suggests, by description.
 */
export default function OperatorAthletesScreen() {
  const [athletes, setAthletes] = useState<Athlete[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [merging, setMerging] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await operatorFetch<{ athletes: Athlete[]; suggestions: Suggestion[] }>('/api/operator/athletes');
      setAthletes(data.athletes);
      setSuggestions(data.suggestions);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load athletes');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const byId = new Map(athletes.map((athlete) => [athlete.id, athlete]));

  const confirmMerge = (from: Athlete, into: Athlete) => {
    Alert.alert(
      'Same athlete?',
      `Merge\n"${from.label}" (${from.recording_dates.join(', ')})\ninto\n"${into.label}" (${into.recording_dates.join(', ')})?\n\nFollowers of either will be told about the other's clips. This cannot be undone.`,
      [
        { text: 'Not the same', style: 'cancel' },
        {
          text: 'Same athlete — merge',
          style: 'destructive',
          onPress: async () => {
            setMerging(`${from.id}:${into.id}`);
            try {
              const result = await operatorFetch<{ reels_moved: number; notified: number }>(
                '/api/operator/athletes/merge',
                { method: 'POST', body: JSON.stringify({ from: from.id, into: into.id }) },
              );
              Alert.alert('Merged', `${result.reels_moved} clip(s) moved, ${result.notified} follower notification(s) sent.`);
              await load();
            } catch (e) {
              Alert.alert('Merge failed', e instanceof Error ? e.message : 'Please try again.');
            } finally {
              setMerging(null);
            }
          },
        },
      ],
    );
  };

  return (
    <SafeArea>
      <ScrollView contentContainerStyle={styles.content}>
        <OperatorNav />
        <Text variant="display">Athletes</Text>
        <Text variant="caption" color={Colors.textSecondary}>
          Clips of one athlete in one session are linked automatically. Across sessions, confirm a suggestion
          only when you recognise the same person.
        </Text>
        <Spacer size={Spacing.md} />
        {error && <Text testID="athletes-error" variant="caption" color={Colors.danger}>{error}</Text>}
        {loading && <Text variant="caption" color={Colors.textSecondary}>Loading…</Text>}

        <Text variant="title">Possible same athlete ({suggestions.length})</Text>
        {!loading && suggestions.length === 0 && (
          <Text variant="caption" color={Colors.textSecondary}>No suggestions.</Text>
        )}
        {suggestions.map((suggestion) => {
          const a = byId.get(suggestion.a);
          const b = byId.get(suggestion.b);
          if (!a || !b) return null;
          const key = `${a.id}:${b.id}`;
          return (
            <Card key={key} bordered style={styles.card}>
              <Text variant="caption" color={Colors.accent}>{Math.round(suggestion.similarity * 100)}% similar description</Text>
              <Text variant="body">{a.label}</Text>
              <Text variant="caption" color={Colors.textSecondary}>{a.recording_dates.join(', ')} · {a.reel_count} clip(s)</Text>
              <Text variant="body">{b.label}</Text>
              <Text variant="caption" color={Colors.textSecondary}>{b.recording_dates.join(', ')} · {b.reel_count} clip(s)</Text>
              <Button
                testID={`athletes-merge-${key}`}
                label="Review and merge"
                variant="secondary"
                loading={merging === key}
                onPress={() => confirmMerge(a, b)}
              />
            </Card>
          );
        })}

        <Spacer size={Spacing.lg} />
        <Text variant="title">All athletes ({athletes.length})</Text>
        {athletes.map((athlete) => (
          <Card key={athlete.id} bordered style={styles.card}>
            <Text variant="body">{athlete.label || 'No description'}</Text>
            <Text variant="caption" color={Colors.textSecondary}>
              {athlete.reel_count} clip(s) · {athlete.recording_dates.join(', ') || 'no clips'} · {athlete.follower_count} follower(s)
            </Text>
          </Card>
        ))}
        <Spacer size={Spacing.lg} />
        <Button testID="athletes-refresh" label="Refresh" variant="ghost" onPress={load} />
      </ScrollView>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  content: { padding: Spacing.lg, paddingBottom: Spacing.xxl, gap: Spacing.sm },
  card: { gap: Spacing.xs },
});
