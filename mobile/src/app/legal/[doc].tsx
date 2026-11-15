import React from 'react';
import { ScrollView, StyleSheet } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { PRIVACY_POLICY } from '@/shared/legal/privacyPolicy';
import { TERMS_OF_SERVICE } from '@/shared/legal/terms';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function LegalScreen() {
  const { doc } = useLocalSearchParams<{ doc: string }>();
  const router = useRouter();
  const text = doc === 'terms' ? TERMS_OF_SERVICE : PRIVACY_POLICY;

  return (
    <SafeArea>
      <Button
        testID="legal-back"
        label="← Back"
        onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))}
        variant="ghost"
        style={styles.back}
      />
      <ScrollView contentContainerStyle={styles.content}>
        <Text testID={`legal-${doc === 'terms' ? 'terms' : 'privacy'}`} variant="body" color={Colors.textSecondary}>
          {text}
        </Text>
      </ScrollView>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  back: { alignSelf: 'flex-start', marginLeft: Spacing.md },
  content: { padding: Spacing.lg, paddingBottom: Spacing.xxl },
});
