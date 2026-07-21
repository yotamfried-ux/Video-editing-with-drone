import AsyncStorage from '@react-native-async-storage/async-storage';

const MULTIPART_RECORD_PREFIX = 'sportreel.multipart-upload.v1:';

/**
 * Forget only the remote multipart session. The staged source file and active
 * batch marker remain available so the next retry can create a fresh R2
 * uploadId without forcing the operator to select the footage again.
 */
export async function forgetMultipartUploadSession(clientUploadId: string): Promise<void> {
  await AsyncStorage.removeItem(`${MULTIPART_RECORD_PREFIX}${clientUploadId}`);
}
