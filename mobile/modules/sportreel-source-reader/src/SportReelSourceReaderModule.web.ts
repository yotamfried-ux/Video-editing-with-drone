import type {
  BackgroundUploadJob,
  EnqueueBackgroundUploadRequest,
  SourceInspection,
  SportReelSourceReaderNativeModule,
} from './SportReelSourceReaderModule';

const MAX_BROWSER_RANGE_BYTES = 256 * 1024 * 1024;
const browserFiles = new Map<string, File>();

export function browserSourceKeyForFile(file: File): string {
  return `web-file://${encodeURIComponent(file.name)}?size=${file.size}&mtime=${file.lastModified}`;
}

export function registerBrowserSourceFile(file: File): string {
  const uri = browserSourceKeyForFile(file);
  browserFiles.set(uri, file);
  return uri;
}

export function getRegisteredBrowserFile(uri: string): File | undefined {
  return browserFiles.get(uri);
}

const webSourceReader: SportReelSourceReaderNativeModule = {
  async enqueueBackgroundUpload(_request: EnqueueBackgroundUploadRequest): Promise<BackgroundUploadJob> {
    throw new Error('Background OS WorkManager uploads are Android-only; browser uploads run in the active tab.');
  },
  async persistTreePermission(_treeUri: string): Promise<boolean> {
    return false;
  },
  async listBackgroundUploads(): Promise<BackgroundUploadJob[]> {
    return [];
  },
  async getBackgroundUpload(_localId: string): Promise<BackgroundUploadJob | null> {
    return null;
  },
  async resumeEligibleBackgroundUploads(_operatorSecret: string | null): Promise<string[]> {
    return [];
  },
  async retryBackgroundUpload(_localId: string, _operatorSecret: string | null): Promise<BackgroundUploadJob | null> {
    return null;
  },
  async forgetVerifiedBackgroundUploads(_batchId: string): Promise<number> {
    return 0;
  },
  async inspectSource(uri: string): Promise<SourceInspection> {
    const file = browserFiles.get(uri);
    if (!file) {
      throw new Error(
        'Browser file handle is no longer in tab memory (for example after a page refresh). Re-select the same video file to resume from the last verified R2 part.'
      );
    }
    return {
      uri,
      displayName: file.name,
      sizeBytes: file.size,
      seekable: true,
      maxRangeBytes: MAX_BROWSER_RANGE_BYTES,
    };
  },
  async readRange(uri: string, offset: number, length: number): Promise<Uint8Array> {
    const file = browserFiles.get(uri);
    if (!file) {
      throw new Error('Browser file handle missing; re-select the same video file to continue.');
    }
    const slice = file.slice(offset, offset + length);
    const buffer = await slice.arrayBuffer();
    return new Uint8Array(buffer);
  },
};

export function getSportReelSourceReader(): SportReelSourceReaderNativeModule {
  return webSourceReader;
}

export default null;
