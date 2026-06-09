import React, { useState } from 'react';
import { View, StyleSheet, TouchableOpacity, Image } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Colors, Spacing, Radius } from '@/shared/constants/theme';

interface Props {
  onUpload: (uri: string) => void;
  onSkip: () => void;
  loading: boolean;
}

export function FaceUploadStep({ onUpload, onSkip, loading }: Props) {
  const [photoUri, setPhotoUri] = useState<string | null>(null);
  const [consented, setConsented] = useState(false);

  const pickFromCamera = async () => {
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== 'granted') return;
    const r = await ImagePicker.launchCameraAsync({
      quality: 0.85,
      allowsEditing: true,
      aspect: [1, 1],
    });
    if (!r.canceled) setPhotoUri(r.assets[0].uri);
  };

  const pickFromLibrary = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({
      quality: 0.85,
      allowsEditing: true,
      aspect: [1, 1],
    });
    if (!r.canceled) setPhotoUri(r.assets[0].uri);
  };

  return (
    <View style={styles.container}>
      <Text variant="headline" style={{ textAlign: 'center' }}>
        Get notified when you're in a clip
      </Text>
      <Text variant="body" color={Colors.textSecondary} style={styles.subtitle}>
        Optionally add a face photo so we can automatically match your
        highlights. You can always do this later from your profile.
      </Text>

      {photoUri ? (
        <Image source={{ uri: photoUri }} style={styles.preview} />
      ) : (
        <View style={styles.photoButtons}>
          <Button
            label="📷  Take Photo"
            onPress={pickFromCamera}
            variant="secondary"
            style={styles.halfBtn}
          />
          <Button
            label="🖼  From Library"
            onPress={pickFromLibrary}
            variant="secondary"
            style={styles.halfBtn}
          />
        </View>
      )}

      {photoUri && (
        <>
          <TouchableOpacity
            style={styles.consent}
            onPress={() => setConsented(!consented)}
          >
            <View style={[styles.checkbox, consented && styles.checked]} />
            <Text
              variant="caption"
              color={Colors.textSecondary}
              style={styles.consentText}
            >
              I consent to SportReel processing my facial biometric data to
              identify me in sports footage. This is optional and I can delete
              it at any time from my Profile.
            </Text>
          </TouchableOpacity>
          <Button
            label="Save & Continue"
            onPress={() => onUpload(photoUri)}
            disabled={!consented}
            loading={loading}
          />
        </>
      )}

      <Button
        label="Skip for now"
        onPress={onSkip}
        variant="ghost"
        style={{ marginTop: Spacing.sm }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: Spacing.xl,
    justifyContent: 'center',
    gap: Spacing.md,
  },
  subtitle: { textAlign: 'center', marginVertical: Spacing.sm },
  preview: {
    width: 160,
    height: 160,
    borderRadius: 80,
    alignSelf: 'center',
  },
  photoButtons: { flexDirection: 'row', gap: Spacing.sm },
  halfBtn: { flex: 1 },
  consent: {
    flexDirection: 'row',
    gap: Spacing.sm,
    alignItems: 'flex-start',
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: Colors.textSecondary,
    marginTop: 1,
  },
  checked: {
    backgroundColor: Colors.accent,
    borderColor: Colors.accent,
  },
  consentText: { flex: 1 },
});
