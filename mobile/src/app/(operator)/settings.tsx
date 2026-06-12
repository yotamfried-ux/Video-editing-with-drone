import React, { useEffect, useState } from 'react';
import { View, TextInput, StyleSheet, ScrollView, Alert } from 'react-native';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Card } from '@/shared/components/Card';
import { Spacer } from '@/shared/components/Spacer';
import { OperatorNav } from '@/features/operator/components/OperatorNav';
import {
  getOperatorSecret,
  setOperatorSecret,
  clearOperatorSecret,
} from '@/features/operator/lib/operatorSecret';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function OperatorSettingsScreen() {
  const [secretSet, setSecretSet] = useState<boolean | null>(null);
  const [input, setInput] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getOperatorSecret().then((s) => setSecretSet(!!s));
  }, []);

  const save = async () => {
    if (!input.trim()) return;
    setSaving(true);
    await setOperatorSecret(input.trim());
    setInput('');
    setSecretSet(true);
    setSaving(false);
  };

  const remove = () => {
    Alert.alert(
      'Remove operator secret',
      'You will need to enter it again to use the operator features.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: async () => {
            await clearOperatorSecret();
            setSecretSet(false);
          },
        },
      ]
    );
  };

  return (
    <SafeArea>
      <View style={styles.container}>
        <OperatorNav />
        <ScrollView contentContainerStyle={{ gap: Spacing.md, paddingBottom: Spacing.xl }}>
          <Text variant="display">Settings</Text>

          <Card bordered style={{ gap: Spacing.md }}>
            <Text variant="title">Operator Secret</Text>
            <Text variant="caption" color={Colors.textSecondary}>
              The secret authorizes privileged actions (pricing, pipeline, reels).
              It is stored only in this device's encrypted keychain — never in the app binary.
            </Text>

            {secretSet === true ? (
              <>
                <View style={styles.status}>
                  <View style={styles.dot} />
                  <Text variant="body" color={Colors.success}>Secret is configured on this device</Text>
                </View>
                <Spacer size={Spacing.sm} />
                <Text variant="caption" color={Colors.textSecondary}>
                  To change the secret, remove it and enter the new value.
                </Text>
                <Button label="Remove secret from this device" onPress={remove} variant="danger" />
              </>
            ) : secretSet === false ? (
              <>
                <View style={styles.status}>
                  <View style={[styles.dot, { backgroundColor: Colors.danger }]} />
                  <Text variant="body" color={Colors.danger}>No secret — operator actions are disabled</Text>
                </View>
                <TextInput
                  value={input}
                  onChangeText={setInput}
                  placeholder="Paste the operator secret here"
                  placeholderTextColor={Colors.textSecondary}
                  secureTextEntry
                  autoCapitalize="none"
                  autoCorrect={false}
                  style={styles.input}
                />
                <Button label="Save secret" onPress={save} loading={saving} />
              </>
            ) : null}
          </Card>

          <Card bordered style={{ gap: Spacing.sm }}>
            <Text variant="title">Where to find the secret</Text>
            <Text variant="caption" color={Colors.textSecondary}>
              {'Vercel Dashboard → video-editing-with-drone → Settings → Environment Variables → OPERATOR_SECRET'}
            </Text>
          </Card>
        </ScrollView>
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.lg },
  status: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: Colors.success },
  input: {
    backgroundColor: Colors.background,
    color: Colors.textPrimary,
    borderRadius: 12,
    padding: Spacing.md,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    fontSize: 15,
  },
});
