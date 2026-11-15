import React from 'react';
import { StyleSheet, TouchableOpacity, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Text } from './Text';
import { Colors, Spacing } from '../constants/theme';

interface Props {
  icon: React.ComponentProps<typeof MaterialCommunityIcons>['name'];
  label: string;
  onPress: () => void;
  testID?: string;
}

/** A navigation row: what it opens on the left, a chevron that says it opens something on the right. */
export function ListRow({ icon, label, onPress, testID }: Props) {
  return (
    <TouchableOpacity testID={testID} onPress={onPress} style={styles.row} accessibilityRole="button" activeOpacity={0.7}>
      <MaterialCommunityIcons name={icon} size={22} color={Colors.accent} />
      <View style={styles.label}><Text variant="body">{label}</Text></View>
      <MaterialCommunityIcons name="chevron-right" size={22} color={Colors.textSecondary} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md, minHeight: 48, paddingVertical: Spacing.sm },
  label: { flex: 1 },
});
