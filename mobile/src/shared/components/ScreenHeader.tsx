import React from 'react';
import { StyleSheet, TouchableOpacity, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Text } from './Text';
import { Colors, Spacing } from '../constants/theme';

interface Props {
  title?: string;
  onBack: () => void;
  backTestID?: string;
}

/** Back button (44pt, named for screen readers) and the screen's title, in the same place on every screen. */
export function ScreenHeader({ title, onBack, backTestID }: Props) {
  return (
    <View style={styles.row}>
      <TouchableOpacity
        testID={backTestID}
        onPress={onBack}
        style={styles.back}
        accessibilityRole="button"
        accessibilityLabel="Back"
        hitSlop={8}
      >
        <MaterialCommunityIcons name="arrow-left" size={24} color={Colors.textPrimary} />
      </TouchableOpacity>
      {title ? <Text variant="headline" numberOfLines={1} style={styles.title}>{title}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, paddingHorizontal: Spacing.md, paddingVertical: Spacing.sm },
  back: {
    width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center',
    backgroundColor: Colors.card,
  },
  title: { flex: 1 },
});
