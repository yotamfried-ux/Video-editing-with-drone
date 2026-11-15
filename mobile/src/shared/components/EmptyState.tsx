import React from 'react';
import { StyleSheet, View } from 'react-native';
import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Text } from './Text';
import { Button } from './Button';
import { Colors, Spacing } from '../constants/theme';

interface Props {
  icon: React.ComponentProps<typeof MaterialCommunityIcons>['name'];
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: () => void;
  testID?: string;
  actionTestID?: string;
}

/** Says why the screen is empty and, where there is one, the next step. */
export function EmptyState({ icon, title, body, actionLabel, onAction, testID, actionTestID }: Props) {
  return (
    <View style={styles.root}>
      <View style={styles.iconWrap}>
        <MaterialCommunityIcons name={icon} size={36} color={Colors.accent} />
      </View>
      <Text testID={testID} variant="headline" style={styles.center}>{title}</Text>
      <Text variant="body" color={Colors.textSecondary} style={styles.center}>{body}</Text>
      {actionLabel && onAction ? (
        <Button testID={actionTestID} label={actionLabel} onPress={onAction} variant="secondary" style={styles.action} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { alignItems: 'center', justifyContent: 'center', padding: Spacing.xl, paddingTop: Spacing.xxl, gap: Spacing.sm },
  iconWrap: {
    width: 72, height: 72, borderRadius: 36, alignItems: 'center', justifyContent: 'center',
    backgroundColor: Colors.card, marginBottom: Spacing.sm,
  },
  center: { textAlign: 'center' },
  action: { marginTop: Spacing.md, alignSelf: 'stretch' },
});
