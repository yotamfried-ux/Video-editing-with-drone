import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';
import nativeModule, {
  type SportReelSourceReaderNativeModule,
} from '../../../../modules/sportreel-source-reader/src/SportReelSourceReaderModule';
import { API_BASE_URL } from '@/shared/lib/publicEnv';
import { createBackgroundUploadClient } from './backgroundUploadClient';
import { operatorFetch } from './operatorApi';
import { getOperatorSecret } from './operatorSecret';

const RESERVATION_KEY = 'sportreel:background-upload-reservations:v1';

export function isBackgroundUploadAvailable(): boolean {
  return Platform.OS === 'android'
    && !!nativeModule
    && typeof (nativeModule as Partial<SportReelSourceReaderNativeModule>).enqueueBackgroundUpload === 'function';
}

let defaultClient: ReturnType<typeof createBackgroundUploadClient> | null = null;

export function getBackgroundUploadClient() {
  if (!nativeModule) {
    throw new Error('Background uploads require a new native SportReel Android build.');
  }
  defaultClient ??= createBackgroundUploadClient({
    native: nativeModule,
    getOperatorSecret,
    apiBaseUrl: API_BASE_URL,
    reserveBatchSlots: async (batchId, count) => {
      await operatorFetch('/api/operator/upload/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_id: batchId, additional_file_count: count, source_kind: 'android_external' }),
      });
    },
    loadReservations: async () => {
      try {
        const raw = await AsyncStorage.getItem(RESERVATION_KEY);
        return raw ? (JSON.parse(raw) as Record<string, string[]>) : {};
      } catch {
        return {};
      }
    },
    saveReservations: (next) => AsyncStorage.setItem(RESERVATION_KEY, JSON.stringify(next)),
  });
  return defaultClient;
}
