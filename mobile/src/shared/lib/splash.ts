import * as SplashScreen from 'expo-splash-screen';

export function initSplashScreen(): void {
  void SplashScreen.preventAutoHideAsync();
}

export function hideSplashScreen(): void {
  void SplashScreen.hideAsync();
}
