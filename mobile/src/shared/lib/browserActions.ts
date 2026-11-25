import { Linking } from 'react-native';

export async function openCheckoutUrl(url: string): Promise<void> {
  await Linking.openURL(url);
}

export async function openDownloadUrl(url: string): Promise<void> {
  await Linking.openURL(url);
}

export async function openExternalUrl(url: string): Promise<void> {
  await Linking.openURL(url);
}

export async function shareWhatsAppMessage(encodedMsg: string): Promise<void> {
  const wa = `whatsapp://send?text=${encodedMsg}`;
  const canOpen = await Linking.canOpenURL(wa);
  await Linking.openURL(canOpen ? wa : `https://wa.me/?text=${encodedMsg}`);
}
