import React from 'react';
import { StyleSheet, View } from 'react-native';
import { WebView, WebViewNavigation } from 'react-native-webview';
import { Colors } from '@/shared/constants/theme';

interface Props {
  reelId: string;
  paymentUrl: string;
  onSuccess: () => void;
  onCancel: () => void;
}

export function BitWebView({ reelId, paymentUrl, onSuccess, onCancel }: Props) {
  const handleNavChange = (nav: WebViewNavigation) => {
    // Match the exact success redirect for THIS reel. onSuccess only navigates
    // to the success screen — the actual download stays gated server-side on a
    // verified payment, so a spoofed redirect cannot unlock a free download.
    const successUrl = `sportreel://success/${reelId}`;
    if (nav.url === successUrl || nav.url.startsWith(`${successUrl}?`)) {
      onSuccess();
    } else if (
      nav.url.includes('error=1') ||
      (nav.url.startsWith(`sportreel://checkout/${reelId}`) && nav.url.includes('error'))
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
