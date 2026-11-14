import { formatSeconds, previewExplanation, previewLabel } from './previewInfo';

describe('preview info', () => {
  it('says how much of the clip the preview shows', () => {
    expect(previewLabel(10, 25)).toBe('Preview · 10s of 25s');
    expect(previewLabel(12, 76.3)).toBe('Preview · 12s of 1m 16s');
  });

  it('never claims a length it does not know, or a preview as long as the clip', () => {
    expect(previewLabel(null, null)).toBe('Preview');
    expect(previewLabel(10, null)).toBe('Preview');
    expect(previewLabel(10, 10)).toBe('Preview');
  });

  it('explains what buying gives', () => {
    expect(previewExplanation(57.8)).toContain('the full 58s clip');
    expect(previewExplanation(null)).toContain('the full clip');
    expect(previewExplanation(null)).toContain('without the watermark');
    expect(formatSeconds(120)).toBe('2m');
  });
});
