import React from 'react';
import { StyleSheet, View } from 'react-native';
import { WebView, WebViewNavigation } from 'react-native-webview';
import { Colors } from '@/shared/constants/theme';

interface Props {
  paymentUrl: string;
  onSuccess: () => void;
  onCancel: () => void;
}

export function BitWebView({ paymentUrl, onSuccess, onCancel }: Props) {
  const handleNavChange = (nav: WebViewNavigation) => {
    if (nav.url.startsWith('sportreel://success')) {
      onSuccess();
    } else if (
      nav.url.includes('error=1') ||
      (nav.url.startsWith('sportreel://checkout') && nav.url.includes('error'))
    ) {
      onCancel();
    }
  };

  return (
    <View style={styles.container}>
      <WebView
        source={{ uri: paymentUrl }}
        onNavigationStateChange={handleNavChange}
        style={styles.webview}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  webview: { flex: 1 },
});
