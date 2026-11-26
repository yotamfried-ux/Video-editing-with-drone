jest.mock('../operator/lib/operatorSecret', () => require('../operator/lib/operatorSecret.web'));
jest.mock('../operator/lib/browserBiometric', () => require('../operator/lib/browserBiometric.web'));

import {
  clearOperatorSecret,
  getOperatorSecret,
  setOperatorSecret,
} from '../operator/lib/operatorSecret.web';
import { useOperatorUnlock } from '../operator/hooks/useOperatorUnlock.web';
import {
  browserSourceKeyForFile,
  getSportReelSourceReader,
  registerBrowserSourceFile,
} from '../../../modules/sportreel-source-reader/src/SportReelSourceReaderModule.web';

describe('WEB-04 session-memory operatorSecret.web', () => {
  afterEach(async () => {
    await clearOperatorSecret();
    useOperatorUnlock.getState().lock();
  });

  it('keeps operator secret strictly in memory and never touches storage globals', async () => {
    expect(await getOperatorSecret()).toBeNull();
    await setOperatorSecret('  op-secret-123  ');
    expect(await getOperatorSecret()).toBe('op-secret-123');
    await clearOperatorSecret();
    expect(await getOperatorSecret()).toBeNull();
  });

  it('unlocks operator state and preserves encrypted vault across lock()', async () => {
    await setOperatorSecret('op-secret-123');
    const ok = await useOperatorUnlock.getState().unlock();
    expect(ok).toBe(true);
    expect(useOperatorUnlock.getState().unlocked).toBe(true);
    useOperatorUnlock.getState().lock();
    expect(useOperatorUnlock.getState().unlocked).toBe(false);
    expect(await getOperatorSecret()).toBe('op-secret-123');
  });
});

describe('WEB-05 browser chunked File.slice source reader', () => {
  it('inspects and slices registered browser File objects accurately', async () => {
    const bytes = new Uint8Array([10, 20, 30, 40, 50, 60, 70, 80]);
    const fakeFile = {
      name: 'DJI_0001.MP4',
      size: bytes.byteLength,
      lastModified: 1700000000000,
      slice(start: number, end: number) {
        const sub = bytes.slice(start, end);
        return {
          async arrayBuffer() {
            return sub.buffer.slice(sub.byteOffset, sub.byteOffset + sub.byteLength);
          },
        };
      },
    } as unknown as File;

    const uri = registerBrowserSourceFile(fakeFile);
    expect(uri).toBe(browserSourceKeyForFile(fakeFile));

    const reader = getSportReelSourceReader();
    const info = await reader.inspectSource(uri);
    expect(info.sizeBytes).toBe(8);
    expect(info.seekable).toBe(true);

    const chunk = await reader.readRange(uri, 2, 4);
    expect(Array.from(chunk)).toEqual([30, 40, 50, 60]);
  });
});
