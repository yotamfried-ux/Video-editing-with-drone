import { requireOptionalNativeModule } from 'expo-modules-core';

export type SourceInspection = {
  uri: string;
  displayName: string | null;
  sizeBytes: number;
  seekable: boolean;
  maxRangeBytes: number;
};

export type SportReelSourceReaderNativeModule = {
  inspectSource(uri: string): Promise<SourceInspection>;
  readRange(uri: string, offset: number, length: number): Promise<Uint8Array>;
};

const nativeModule = requireOptionalNativeModule<SportReelSourceReaderNativeModule>(
  'SportReelSourceReader'
);

export function getSportReelSourceReader(): SportReelSourceReaderNativeModule {
  if (!nativeModule) {
    throw new Error(
      'Large SD / USB upload requires a new native SportReel Android build. Install the matching EAS build before uploading drone footage.'
    );
  }
  return nativeModule;
}

export default nativeModule;
