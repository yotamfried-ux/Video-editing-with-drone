import React, { useState } from 'react';
import {
  View,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { hapticSuccess } from '@/shared/lib/haptics';
import { showAlert } from '@/shared/lib/alert';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Spacer } from '@/shared/components/Spacer';
import { FormField } from '@/shared/components/FormField';
import { useAuth } from '@/shared/hooks/useAuth';
import { supabase } from '@/shared/lib/supabase';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function SuggestScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  const submit = async () => {
    if (!message.trim()) return;
    setSending(true);
    const { error } = await supabase.from('suggestions').insert({
      user_id: user?.id,
      message: message.trim(),
    });
    setSending(false);
    if (error) {
      showAlert('Could not send', error.message);
      return;
    }
    await hapticSuccess();
    showAlert('Thank you!', 'Your suggestion helps us make better clips.', [
      { text: 'OK', onPress: () => router.back() },
    ]);
  };

  return (
    <SafeArea>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.container}
      >
        <Text variant="display">Suggest an Improvement</Text>
        <Text variant="body" color={Colors.textSecondary}>
          Tell us how we can make your highlight clips even better.
        </Text>
        <Spacer size={Spacing.lg} />
        <FormField
          testID="suggestion-message-input"
          label="Your idea"
          value={message}
          onChangeText={setMessage}
          autoCapitalize="sentences"
          multiline
          maxLength={2000}
          hint={`${message.length} / 2000`}
        />
        <Spacer size={Spacing.lg} />
        <Button testID="suggestion-send" label="Send Suggestion" onPress={submit} loading={sending} disabled={!message.trim()} icon="send" />
        <Spacer size={Spacing.sm} />
        <Button testID="suggestion-cancel" label="Cancel" onPress={() => router.back()} variant="ghost" />
      </KeyboardAvoidingView>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.xl, justifyContent: 'center' },
});
