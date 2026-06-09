import { useEffect } from 'react';
import * as ScreenCapture from 'expo-screen-capture';

export function useScreenCapture() {
  useEffect(() => {
    ScreenCapture.preventScreenCaptureAsync();
    const sub = ScreenCapture.addScreenshotListener(() => {});
    return () => {
      ScreenCapture.allowScreenCaptureAsync();
      sub.remove();
    };
  }, []);
}
