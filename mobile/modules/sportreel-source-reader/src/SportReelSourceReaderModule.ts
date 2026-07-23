import { requireNativeModule } from 'expo-modules-core';

export type SourceInspection = {
  uri: string;
  displayName: string | null;
  sizeBytes: number;
  seekable: boolean;
  maxRangeBytes: number;
};

type SportReelSourceReaderNativeModule = {
  inspectSource(uri: string): Promise<SourceInspection>;
  readRange(uri: string, offset: number, length: number): Promise<Uint8Array>;
};

export default requireNativeModule<SportReelSourceReaderNativeModule>('SportReelSourceReader');
