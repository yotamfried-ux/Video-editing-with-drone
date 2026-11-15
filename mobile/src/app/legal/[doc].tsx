import React from 'react';
import { ScrollView, StyleSheet } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { ScreenHeader } from '@/shared/components/ScreenHeader';
import { PRIVACY_POLICY } from '@/shared/legal/privacyPolicy';
import { TERMS_OF_SERVICE } from '@/shared/legal/terms';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function LegalScreen() {
  const { doc } = useLocalSearchParams<{ doc: string }>();
  const router = useRouter();
  const text = doc === 'terms' ? TERMS_OF_SERVICE : PRIVACY_POLICY;

  return (
    <SafeArea>
      <ScreenHeader
        backTestID="legal-back"
        title={doc === 'terms' ? 'Terms of Service' : 'Privacy Policy'}
        onBack={() => (router.canGoBack() ? router.back() : router.replace('/'))}
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
  content: { padding: Spacing.lg, paddingTop: Spacing.sm, paddingBottom: Spacing.xxl },
});
