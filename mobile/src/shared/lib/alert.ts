import React from 'react';
import { Alert, type AlertButton } from 'react-native';

export type DialogButton = AlertButton;

export function showAlert(title: string, message?: string, buttons?: DialogButton[]): void {
  Alert.alert(title, message, buttons);
}

export function ConfirmDialogHost(): React.ReactElement | null {
  return null;
}
