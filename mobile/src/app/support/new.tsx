import React, { useState } from 'react';
import {
  View,
  StyleSheet,
  TextInput,
  KeyboardAvoidingView,
  Platform,
  Alert,
} from 'react-native';
import { useRouter } from 'expo-router';
import * as Haptics from 'expo-haptics';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { useAuth } from '@/shared/hooks/useAuth';
import { supabase } from '@/shared/lib/supabase';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function NewSupportTicketScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  const submit = async () => {
    if (!message.trim()) return;
    setSending(true);
    const { error } = await supabase.from('support_tickets').insert({
      user_id: user?.id,
      message: message.trim(),
    });
    setSending(false);
    if (error) {
      Alert.alert('Could not send', error.message);
      return;
    }
    await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    Alert.alert('Sent!', "We received your message and will reply soon.", [
      { text: 'OK', onPress: () => router.back() },
    ]);
  };

  return (
    <SafeArea>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.container}
      >
        <Text variant="display">Contact Support</Text>
        <Text variant="body" color={Colors.textSecondary}>
          Having an issue? Tell us what happened and we'll get back to you in the app.
        </Text>
        <Spacer size={Spacing.lg} />
        <TextInput
          value={message}
          onChangeText={setMessage}
          placeholder="Describe your issue…"
          placeholderTextColor={Colors.textSecondary}
          multiline
          style={styles.input}
        />
        <Spacer size={Spacing.lg} />
        <Button label="Send Message" onPress={submit} loading={sending} />
        <Spacer size={Spacing.sm} />
        <Button label="Cancel" onPress={() => router.back()} variant="ghost" />
      </KeyboardAvoidingView>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.xl, justifyContent: 'center' },
  input: {
    backgroundColor: Colors.card,
    color: Colors.textPrimary,
    borderRadius: 12,
    padding: Spacing.md,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    fontSize: 15,
    minHeight: 140,
    textAlignVertical: 'top',
  },
});
