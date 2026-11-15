/**
 * What the Discover player tells the customer about the clip they are watching.
 * Discover only ever streams a short watermarked preview; the full clip is the purchase.
 */
export function formatSeconds(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  if (whole < 60) return `${whole}s`;
  const rest = whole % 60;
  return rest ? `${Math.floor(whole / 60)}m ${rest}s` : `${Math.floor(whole / 60)}m`;
}

export function previewLabel(previewSeconds?: number | null, fullSeconds?: number | null): string {
  if (previewSeconds && fullSeconds && fullSeconds > previewSeconds) {
    return `Preview · ${formatSeconds(previewSeconds)} of ${formatSeconds(fullSeconds)}`;
  }
  return 'Preview';
}

export function previewExplanation(fullSeconds?: number | null): string {
  const length = fullSeconds ? `the full ${formatSeconds(fullSeconds)} clip` : 'the full clip';
  return `This is a short, watermarked preview. Buy to get ${length} in full quality, without the watermark.`;
}
