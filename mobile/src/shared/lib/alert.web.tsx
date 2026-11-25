import React, { useEffect, useState } from 'react';
import { Modal, StyleSheet, TouchableOpacity, View } from 'react-native';
import type { AlertButton } from 'react-native';
import { Colors, Radius, Spacing } from '@/shared/constants/theme';
import { Text } from '@/shared/components/Text';

export type DialogButton = AlertButton;

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
  const resolvedButtons: DialogButton[] =
    buttons && buttons.length > 0 ? buttons : [{ text: 'OK' }];
  queue = [...queue, { title, message, buttons: resolvedButtons }];
  emit();
}

export function ConfirmDialogHost(): React.ReactElement | null {
  const [items, setItems] = useState<QueuedDialog[]>(queue);

  useEffect(() => {
    const listener: Listener = (next) => setItems(next);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  const active = items[0];
  if (!active) return null;

  const dismissAndRun = (btn: DialogButton) => {
    queue = queue.slice(1);
    emit();
    btn.onPress?.();
  };

  return (
    <Modal transparent visible animationType="fade" onRequestClose={() => dismissAndRun(active.buttons[0])}>
      <View style={styles.backdrop}>
        <View style={styles.dialog} accessibilityRole="alert">
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
                <TouchableOpacity
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
                </TouchableOpacity>
              );
            })}
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.65)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: Spacing.lg,
  },
  dialog: {
    width: '100%',
    maxWidth: 420,
    backgroundColor: Colors.card,
    borderRadius: Radius.lg,
    padding: Spacing.lg,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
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
    paddingVertical: Spacing.sm,
    paddingHorizontal: Spacing.md,
    borderRadius: Radius.md,
    backgroundColor: Colors.background,
  },
  destructiveButton: {
    borderWidth: 1,
    borderColor: Colors.danger,
  },
  cancelButton: {
    backgroundColor: 'transparent',
  },
});
