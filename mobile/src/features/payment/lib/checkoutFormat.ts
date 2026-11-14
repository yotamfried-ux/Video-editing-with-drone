// Pure helpers (no network, no native modules): unit-tested in checkoutFormat.test.ts.

/** A hosted payment page is only ever opened over https. */
export function isSafeCheckoutUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  return /^https:\/\/[^\s/?#]+/i.test(url);
}

export function formatIls(agorot: number): string {
  const shekels = agorot / 100;
  return `₪${Number.isInteger(shekels) ? shekels.toFixed(0) : shekels.toFixed(2)}`;
}
