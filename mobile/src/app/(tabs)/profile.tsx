import React, { useState } from 'react';
import {
  Alert,
  ScrollView,
  View,
  StyleSheet,
  TouchableOpacity,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Card } from '@/shared/components/Card';
import { Spacer } from '@/shared/components/Spacer';
import { FormField } from '@/shared/components/FormField';
import { ListRow } from '@/shared/components/ListRow';
import { EmptyState } from '@/shared/components/EmptyState';
import { useAuth } from '@/shared/hooks/useAuth';
import { useProfile } from '@/features/profile/hooks/useProfile';
import { supabase } from '@/shared/lib/supabase';
import { getOperatorSecret } from '@/features/operator/lib/operatorSecret';
import { useOperatorUnlock } from '@/features/operator/hooks/useOperatorUnlock';
import { deleteAccount } from '@/features/account/deleteAccount';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function ProfileScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const { profile, updateName } = useProfile();
  const [name, setName] = useState<string | null>(null);
  const [taps, setTaps] = useState(0);
  const [deleting, setDeleting] = useState(false);

  const confirmDeleteAccount = () => {
    Alert.alert(
      'Delete account?',
      'Your account, profile and notification settings will be permanently deleted. This cannot be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            setDeleting(true);
            try {
              await deleteAccount();
              router.replace('/(auth)/login');
            } catch (e) {
              Alert.alert('Could not delete account', e instanceof Error ? e.message : 'Please try again.');
            } finally {
              setDeleting(false);
            }
          },
        },
      ],
    );
  };

  const handleLogoTap = async () => {
    const next = taps + 1;
    setTaps(next);
    if (next >= 5) {
      setTaps(0);
      const ok = await useOperatorUnlock.getState().unlock();
      if (!ok) return;
      const secret = await getOperatorSecret();
      router.push(secret ? '/(operator)/pipeline' : '/(operator)/settings');
    }
  };

  const savedName = profile?.name ?? '';
  const currentName = name ?? savedName;
  const initials = (savedName.trim().split(/\s+/).map((w) => w[0]).slice(0, 2).join('') || 'SR').toUpperCase();

  if (!user) {
    return (
      <SafeArea>
        <View style={styles.center}>
          <EmptyState
            icon="account-circle-outline"
            title="Sign in to view your profile"
            body="Your purchases and the athletes you follow are kept with your account."
          />
          <Button label="Sign In" onPress={() => router.push('/(auth)/login')} style={styles.stretch} />
          <Button
            label="Create Account"
            onPress={() => router.push('/(auth)/register')}
            variant="ghost"
            style={styles.stretch}
          />
        </View>
      </SafeArea>
    );
  }

  return (
    <SafeArea>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <TouchableOpacity testID="profile-operator-entry" onPress={handleLogoTap} activeOpacity={1} style={styles.avatarWrap}>
          <View style={styles.avatar}>
            <Text variant="display" color={Colors.background}>{initials}</Text>
          </View>
        </TouchableOpacity>
        <Text variant="headline" style={styles.centerText}>{savedName || 'Your profile'}</Text>
        {user.email ? (
          <Text variant="caption" color={Colors.textSecondary} style={styles.centerText}>{user.email}</Text>
        ) : null}
        <Spacer size={Spacing.lg} />

        <Card bordered>
          <FormField
            testID="profile-name-input"
            label="Name"
            value={currentName}
            onChangeText={setName}
            autoCapitalize="words"
            autoComplete="name"
          />
          <Spacer size={Spacing.sm} />
          <Button
            testID="profile-save-name"
            label="Save Name"
            onPress={() => updateName(currentName)}
            variant="secondary"
            disabled={!currentName.trim() || currentName === savedName}
          />
        </Card>

        <Spacer size={Spacing.md} />
        <Card bordered>
          <Text variant="title">Support</Text>
          <Spacer size={Spacing.xs} />
          <ListRow testID="profile-contact-support" icon="message-text-outline" label="Contact Support" onPress={() => router.push('/support/new')} />
          <ListRow testID="profile-suggest" icon="lightbulb-on-outline" label="Suggest a Clip Improvement" onPress={() => router.push('/support/suggest')} />
        </Card>

        <Spacer size={Spacing.md} />
        <Card bordered>
          <Text variant="title">Legal</Text>
          <Spacer size={Spacing.xs} />
          <ListRow testID="profile-terms" icon="file-document-outline" label="Terms of Service" onPress={() => router.push('/legal/terms')} />
          <ListRow testID="profile-privacy" icon="shield-lock-outline" label="Privacy Policy" onPress={() => router.push('/legal/privacy')} />
        </Card>

        <Spacer size={Spacing.xl} />
        <Button testID="profile-sign-out" label="Sign Out" icon="logout" onPress={() => supabase.auth.signOut()} variant="secondary" />
        <Spacer size={Spacing.sm} />
        <Button
          testID="profile-delete-account"
          label="Delete Account"
          onPress={confirmDeleteAccount}
          loading={deleting}
          variant="dangerText"
        />
        <Text variant="caption" color={Colors.textSecondary} style={styles.centerText}>
          Deleting removes your account, profile and notification settings for good.
        </Text>
      </ScrollView>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { padding: Spacing.lg, paddingBottom: Spacing.xxl },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.xl,
    gap: Spacing.sm,
  },
  stretch: { alignSelf: 'stretch' },
  centerText: { textAlign: 'center' },
  avatarWrap: { alignSelf: 'center', marginBottom: Spacing.sm },
  avatar: {
    width: 88, height: 88, borderRadius: 44, alignItems: 'center', justifyContent: 'center',
    backgroundColor: Colors.accent,
  },
});
