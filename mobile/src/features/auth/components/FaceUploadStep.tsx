import React, { useState } from 'react';
import { View, StyleSheet, TouchableOpacity, Image } from 'react-native';
import * as ImagePicker from 'expo-image-picker';
import { Text } from '@/shared/components/Text';
import { Button } from '@/shared/components/Button';
import { Colors, Spacing } from '@/shared/constants/theme';

// Minimum face photo size for reliable embedding.
const MIN_DIMENSION_PX = 400;

interface Props {
  onUpload: (uri: string) => void;
  onSkip: () => void;
  loading: boolean;
}

export function FaceUploadStep({ onUpload, onSkip, loading }: Props) {
  const [photoUri, setPhotoUri] = useState<string | null>(null);
  const [consented, setConsented] = useState(false);
  const [qualityError, setQualityError] = useState<string | null>(null);

  const validateAndSet = (asset: ImagePicker.ImagePickerAsset) => {
    setQualityError(null);
    if (asset.width < MIN_DIMENSION_PX || asset.height < MIN_DIMENSION_PX) {
      setQualityError(
        `Photo is too small (${asset.width}×${asset.height}px). Use a clearer, higher-resolution image — minimum ${MIN_DIMENSION_PX}×${MIN_DIMENSION_PX}px.`
      );
      return;
    }
    setPhotoUri(asset.uri);
  };

  const pickFromCamera = async () => {
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== 'granted') return;
    const r = await ImagePicker.launchCameraAsync({
      quality: 0.9,
      allowsEditing: true,
      aspect: [1, 1],
    });
    if (!r.canceled) validateAndSet(r.assets[0]);
  };

  const pickFromLibrary = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({
      quality: 0.9,
      allowsEditing: true,
      aspect: [1, 1],
    });
    if (!r.canceled) validateAndSet(r.assets[0]);
  };

  const retake = () => {
    setPhotoUri(null);
    setConsented(false);
    setQualityError(null);
  };

  return (
    <View style={styles.container}>
      <Text variant="headline" style={{ textAlign: 'center' }}>
        Get notified when you're in a clip
      </Text>
      <Text variant="body" color={Colors.textSecondary} style={styles.subtitle}>
        Add a face photo so we can automatically match your highlights.
        You can always do this later from your profile.
      </Text>

      <View style={styles.tips}>
        <Text variant="caption" color={Colors.textSecondary}>For best results:</Text>
        <Text variant="caption" color={Colors.textSecondary}>• Frontal photo, face clearly visible</Text>
        <Text variant="caption" color={Colors.textSecondary}>• Good lighting, no heavy shadows</Text>
        <Text variant="caption" color={Colors.textSecondary}>• No sunglasses or hats</Text>
      </View>

      <View style={styles.discoverNote}>
        <Text variant="caption" color={Colors.textSecondary} style={styles.discoverNoteText}>
          Keep in mind: face recognition improves your chances of being found automatically,
          but it isn't perfect. Clips featuring you may appear in{' '}
          <Text variant="caption" color={Colors.accent}>Discover</Text>
          {' '}without a direct notification — check there regularly so you never miss a highlight.
        </Text>
      </View>

      {qualityError && (
        <Text variant="caption" color={Colors.danger} style={{ textAlign: 'center' }}>
          {qualityError}
        </Text>
      )}

      {photoUri ? (
        <>
          <Image source={{ uri: photoUri }} style={styles.preview} />
          <TouchableOpacity onPress={retake} style={styles.retakeBtn}>
            <Text variant="caption" color={Colors.accent}>Retake</Text>
          </TouchableOpacity>
        </>
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
  tips: {
    backgroundColor: '#1E293B',
    borderRadius: 10,
    padding: Spacing.md,
    gap: 4,
  },
  discoverNote: {
    borderLeftWidth: 2,
    borderLeftColor: Colors.accent,
    paddingLeft: Spacing.sm,
    opacity: 0.8,
  },
  discoverNoteText: { lineHeight: 18 },
  preview: {
    width: 160,
    height: 160,
    borderRadius: 80,
    alignSelf: 'center',
  },
  retakeBtn: {
    alignSelf: 'center',
    padding: Spacing.sm,
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
