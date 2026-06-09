import React, { useState } from 'react';
import {
  View,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  Alert,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeArea } from '@/shared/components/SafeArea';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Card } from '@/shared/components/Card';
import { Spacer } from '@/shared/components/Spacer';
import { useAuth } from '@/shared/hooks/useAuth';
import { useProfile } from '@/features/profile/hooks/useProfile';
import { supabase } from '@/shared/lib/supabase';
import { Colors, Spacing } from '@/shared/constants/theme';

export default function ProfileScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const { profile, updateName, deleteFaceData } = useProfile();
  const [name, setName] = useState('');
  const [taps, setTaps] = useState(0);

  const handleLogoTap = () => {
    const next = taps + 1;
    setTaps(next);
    if (next >= 5) {
      setTaps(0);
      router.push('/(operator)/pipeline');
    }
  };

  if (!user) {
    return (
      <SafeArea>
        <View style={styles.center}>
          <Text variant="headline">Sign in to view your profile</Text>
          <Spacer size={Spacing.lg} />
          <Button
            label="Sign In"
            onPress={() => router.push('/(auth)/login')}
          />
          <Button
            label="Create Account"
            onPress={() => router.push('/(auth)/register')}
            variant="ghost"
            style={{ marginTop: Spacing.sm }}
          />
        </View>
      </SafeArea>
    );
  }

  return (
    <SafeArea>
      <View style={styles.container}>
        <TouchableOpacity onPress={handleLogoTap} activeOpacity={1}>
          <Text variant="display" style={{ textAlign: 'center' }}>
            SR
          </Text>
        </TouchableOpacity>
        <Spacer size={Spacing.xl} />

        <Card bordered>
          <Text variant="caption" color={Colors.textSecondary}>
            Name
          </Text>
          <TextInput
            value={name || profile?.name || ''}
            onChangeText={setName}
            placeholder="Your name"
            placeholderTextColor={Colors.textSecondary}
            style={styles.input}
          />
          <Button
            label="Save Name"
            onPress={() => updateName(name || profile?.name || '')}
            variant="secondary"
          />
        </Card>

        <Spacer size={Spacing.md} />

        <Card bordered>
          <Text variant="title">Face Recognition</Text>
          <Spacer size={Spacing.sm} />
          <Text variant="body" color={Colors.textSecondary}>
            {profile?.photo_path
              ? "Face photo saved. We'll notify you when you appear in a new clip."
              : 'No face photo. Add one to get automatic highlight notifications.'}
          </Text>
          <Spacer size={Spacing.md} />
          {profile?.photo_path ? (
            <Button
              label="Remove Face Data"
              onPress={() =>
                Alert.alert(
                  'Remove Face Data',
                  'This will delete your face photo and disable automatic matching.',
                  [
                    { text: 'Cancel' },
                    {
                      text: 'Delete',
                      style: 'destructive',
                      onPress: deleteFaceData,
                    },
                  ]
                )
              }
              variant="danger"
            />
          ) : (
            <Button
              label="Add Face Photo"
              onPress={() => router.push('/(auth)/register')}
              variant="secondary"
            />
          )}
        </Card>

        <Spacer size={Spacing.md} />

        <Card bordered>
          <Text variant="title">Support</Text>
          <Spacer size={Spacing.sm} />
          <Button
            label="Contact Support"
            onPress={() => router.push('/support/new')}
            variant="secondary"
          />
          <Spacer size={Spacing.sm} />
          <Button
            label="Suggest a Clip Improvement"
            onPress={() => router.push('/support/suggest')}
            variant="ghost"
          />
        </Card>

        <Spacer size={Spacing.xl} />
        <Button
          label="Sign Out"
          onPress={() => supabase.auth.signOut()}
          variant="ghost"
        />
      </View>
    </SafeArea>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: Spacing.lg },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.xl,
    gap: Spacing.sm,
  },
  input: {
    color: Colors.textPrimary,
    fontSize: 15,
    paddingVertical: Spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: '#2D3F55',
    marginVertical: Spacing.sm,
  },
});
