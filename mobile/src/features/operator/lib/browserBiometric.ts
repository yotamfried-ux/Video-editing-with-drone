export async function isBrowserBiometricAvailable(): Promise<boolean> {
  return false;
}

export function isBrowserBiometricEnabled(): boolean {
  return false;
}

export async function verifyRegisteredBrowserBiometric(): Promise<boolean> {
  return true;
}

export async function enableBrowserBiometric(): Promise<boolean> {
  return false;
}

export function disableBrowserBiometric(): void {}
