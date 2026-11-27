import React, { useEffect, useState } from 'react';
import { Alert, Platform, Pressable, StyleSheet, View } from 'react-native';
import { Text } from '@/shared/components/Text';
import { Colors, Spacing } from '@/shared/constants/theme';

export interface DialogButton {
  text?: string;
  style?: 'default' | 'cancel' | 'destructive';
  onPress?: () => void;
}

interface QueuedDialog {
  title: string;
  message?: string;
  buttons: DialogButton[];
}

type Listener = (queue: QueuedDialog[]) => void;

let queue: QueuedDialog[] = [];
const listeners = new Set<Listener>();

function emit(): void {
  const snapshot = [...queue];
  listeners.forEach((l) => l(snapshot));
}

export function showAlert(title: string, message?: string, buttons?: DialogButton[]): void {
  if (Platform.OS !== 'web') {
    Alert.alert(title, message, buttons);
    return;
  }
  const resolvedButtons: DialogButton[] =
    buttons && buttons.length > 0 ? buttons : [{ text: 'OK' }];
  queue = [...queue, { title, message, buttons: resolvedButtons }];
  emit();
}

export function ConfirmDialogHost(): React.ReactElement | null {
  const [items, setItems] = useState<QueuedDialog[]>(queue);

  useEffect(() => {
    if (Platform.OS !== 'web') return;
    const listener: Listener = (next) => setItems(next);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  if (Platform.OS !== 'web') return null;

  const active = items[0];
  if (!active) return null;

  const dismissAndRun = (btn: DialogButton) => {
    queue = queue.slice(1);
    emit();
    btn.onPress?.();
  };

  return (
    <View style={styles.backdrop} accessibilityRole="alert" testID="confirm-dialog-host">
      <View style={styles.dialog}>
        <Text variant="title">{active.title}</Text>
        {active.message ? (
          <Text variant="body" color={Colors.textSecondary} style={styles.message}>
            {active.message}
          </Text>
        ) : null}
        <View style={styles.actions}>
          {active.buttons.map((btn, idx) => {
            const destructive = btn.style === 'destructive';
            const cancel = btn.style === 'cancel';
            return (
              <Pressable
                key={`${btn.text ?? 'btn'}-${idx}`}
                style={[
                  styles.button,
                  destructive && styles.destructiveButton,
                  cancel && styles.cancelButton,
                ]}
                onPress={() => dismissAndRun(btn)}
              >
                <Text
                  variant="body"
                  color={destructive ? Colors.danger : cancel ? Colors.textSecondary : Colors.accent}
                >
                  {btn.text ?? 'OK'}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    position: 'fixed' as unknown as 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    zIndex: 99999,
    backgroundColor: 'rgba(0,0,0,0.72)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.lg,
  },
  dialog: {
    width: '100%',
    maxWidth: 420,
    backgroundColor: Colors.card,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    borderRadius: 12,
    padding: Spacing.lg,
    gap: Spacing.sm,
  },
  message: {
    marginTop: Spacing.xs,
  },
  actions: {
    marginTop: Spacing.md,
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
    gap: Spacing.sm,
  },
  button: {
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: Colors.accent,
  },
  destructiveButton: {
    borderColor: Colors.danger,
  },
  cancelButton: {
    borderColor: Colors.cardBorder,
  },
});
