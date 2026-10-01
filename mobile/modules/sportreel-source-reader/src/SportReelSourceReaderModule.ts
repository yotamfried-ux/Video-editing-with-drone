import { requireOptionalNativeModule } from 'expo-modules-core';

export type SourceInspection = {
  uri: string;
  displayName: string | null;
  sizeBytes: number;
  seekable: boolean;
  maxRangeBytes: number;
};

export type BackgroundUploadState =
  | 'queued' | 'uploading' | 'retry_wait' | 'completing' | 'verified' | 'failed';

export type BackgroundUploadJob = {
  localId: string;
  batchId: string;
  sourceUri: string;
  filename: string;
  status: BackgroundUploadState;
  attempt: number;
  lastError: string | null;
  uploadId: string | null;
  storageKey: string | null;
  sourceSizeBytes: number;
  completedPartCount: number;
  expectedPartCount: number | null;
  progress: number;
  updatedAt: string;
  persistedUriPermission?: boolean;
};

export type EnqueueBackgroundUploadRequest = {
  batchId: string;
  sourceUri: string;
  filename: string;
  mimeType: string;
  apiBaseUrl: string;
  operatorSecret: string;
};

export type SportReelSourceReaderNativeModule = {
  enqueueBackgroundUpload(request: EnqueueBackgroundUploadRequest): Promise<BackgroundUploadJob>;
  listBackgroundUploads(): Promise<BackgroundUploadJob[]>;
  getBackgroundUpload(localId: string): Promise<BackgroundUploadJob | null>;
  resumeEligibleBackgroundUploads(operatorSecret: string | null): Promise<string[]>;
  retryBackgroundUpload(localId: string, operatorSecret: string | null): Promise<BackgroundUploadJob | null>;
  forgetVerifiedBackgroundUploads(batchId: string): Promise<number>;
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
