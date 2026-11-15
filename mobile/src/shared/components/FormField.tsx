import React, { useState } from 'react';
import { View } from 'react-native';
import { HelperText, TextInput } from 'react-native-paper';
import { Colors } from '../constants/theme';

interface Props {
  label: string;
  value: string;
  onChangeText: (text: string) => void;
  testID?: string;
  /** Shown under the field. An error replaces the hint. */
  hint?: string;
  error?: string | null;
  secure?: boolean;
  keyboardType?: 'default' | 'email-address';
  autoCapitalize?: 'none' | 'words' | 'sentences';
  autoComplete?: 'email' | 'password' | 'new-password' | 'name' | 'off';
  returnKeyType?: 'next' | 'done' | 'go';
  onSubmitEditing?: () => void;
}

/**
 * A labelled text field. The label stays visible while typing (a placeholder alone disappears and is
 * not a label), the error sits next to the field it is about, and a password can be shown.
 */
export function FormField({
  label, value, onChangeText, testID, hint, error, secure, keyboardType, autoCapitalize,
  autoComplete, returnKeyType, onSubmitEditing,
}: Props) {
  const [hidden, setHidden] = useState(Boolean(secure));
  const message = error || hint;
  return (
    <View>
      <TextInput
        testID={testID}
        mode="outlined"
        label={label}
        value={value}
        onChangeText={onChangeText}
        error={Boolean(error)}
        secureTextEntry={hidden}
        keyboardType={keyboardType}
        autoCapitalize={autoCapitalize ?? 'none'}
        autoComplete={autoComplete}
        autoCorrect={false}
        returnKeyType={returnKeyType}
        onSubmitEditing={onSubmitEditing}
        accessibilityLabel={label}
        style={{ backgroundColor: Colors.card }}
        right={secure ? (
          <TextInput.Icon
            icon={hidden ? 'eye-outline' : 'eye-off-outline'}
            onPress={() => setHidden((h) => !h)}
            accessibilityLabel={hidden ? 'Show password' : 'Hide password'}
            forceTextInputFocus={false}
          />
        ) : undefined}
      />
      {message ? (
        <HelperText type={error ? 'error' : 'info'} visible testID={testID ? `${testID}-message` : undefined}>
          {message}
        </HelperText>
      ) : null}
    </View>
  );
}
