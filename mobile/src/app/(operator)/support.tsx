import React, { useEffect, useState, useCallback } from 'react';
import { View, StyleSheet, ScrollView, TextInput, Alert } from 'react-native';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Card } from '@/shared/components/Card';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import { operatorFetch } from '@/features/operator/lib/operatorApi';
import type { OperatorSuggestion, OperatorSupportResponse, OperatorSupportTicket, SupportReplyResponse } from '@/features/operator/types/contracts';
import { Colors, Spacing } from '@/shared/constants/theme';

function TicketCard({ ticket, onReplied }: { ticket: OperatorSupportTicket; onReplied: () => void }) {
  const [reply, setReply] = useState(ticket.operator_reply ?? '');
  const [sending, setSending] = useState(false);

  const send = async () => {
    if (!reply.trim()) return;
    setSending(true);
    try {
      await operatorFetch<SupportReplyResponse>(`/api/support/${ticket.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ reply: reply.trim() }),
      });
      onReplied();
    } catch (e: any) {
      Alert.alert('Failed to send reply', e.message);
    } finally {
      setSending(false);
    }
  };

  return (
    <Card bordered style={{ gap: Spacing.sm }}>
      <View style={styles.cardHead}>
        <Text variant="caption" color={Colors.textSecondary}>
          {new Date(ticket.created_at).toLocaleString()}
        </Text>
        <Text variant="caption" color={ticket.status === 'open' ? Colors.accent : Colors.success}>
          {ticket.status.toUpperCase()}
        </Text>
      </View>
      <Text variant="body">{ticket.message}</Text>
      <Spacer size={Spacing.xs} />
      <TextInput
        value={reply}
        onChangeText={setReply}
        placeholder="Write a reply…"
        placeholderTextColor={Colors.textSecondary}
        multiline
        style={styles.input}
      />
      <Button
        label={ticket.status === 'replied' ? 'Update Reply' : 'Send Reply'}
        onPress={send}
        loading={sending}
        variant="secondary"
      />
    </Card>
  );
}

export default function OperatorSupportScreen() {
  const [tickets, setTickets] = useState<OperatorSupportTicket[]>([]);
  const [suggestions, setSuggestions] = useState<OperatorSuggestion[]>([]);

  const load = useCallback(async () => {
    try {
      const data = await operatorFetch<OperatorSupportResponse>('/api/operator/support');
      setTickets(data.tickets ?? []);
      setSuggestions(data.suggestions ?? []);
    } catch {
      setTickets([]);
      setSuggestions([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <SafeArea>
      <View style={styles.container}>
        <OperatorNav />
        <ScrollView contentContainerStyle={{ gap: Spacing.md, paddingBottom: Spacing.xl }}>
          <Text variant="display">Support</Text>

          <Text variant="title">Tickets ({tickets.length})</Text>
          {tickets.length === 0 && (
            <Text variant="body" color={Colors.textSecondary}>No tickets.</Text>
          )}
          {tickets.map((t) => (
            <TicketCard key={t.id} ticket={t} onReplied={load} />
          ))}

          <Spacer size={Spacing.md} />
          <Text variant="title">Suggestions ({suggestions.length})</Text>
          {suggestions.length === 0 && (
            <Text variant="body" color={Colors.textSecondary}>No suggestions.</Text>
          )}
          {suggestions.map((s) => (
            <Card key={s.id} bordered style={{ gap: 4 }}>
              <Text variant="caption" color={Colors.textSecondary}>
                {new Date(s.created_at).toLocaleString()}
              </Text>
              <Text variant="body">{s.message}</Text>
            </Card>
          ))}
        </ScrollView>
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.lg },
  cardHead: { flexDirection: 'row', justifyContent: 'space-between' },
  input: {
    backgroundColor: Colors.background,
    color: Colors.textPrimary,
    borderRadius: 12,
    padding: Spacing.md,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    fontSize: 15,
    minHeight: 60,
    textAlignVertical: 'top',
  },
});
