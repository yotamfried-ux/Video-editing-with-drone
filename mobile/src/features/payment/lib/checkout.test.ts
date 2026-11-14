import { formatIls, isSafeCheckoutUrl } from './checkout';

describe('checkout helpers', () => {
  it('opens only https payment pages', () => {
    expect(isSafeCheckoutUrl('https://checkout.stripe.com/c/pay/cs_test_1')).toBe(true);
    expect(isSafeCheckoutUrl('https://pay.example.co.il/p/123')).toBe(true);
    for (const bad of [null, undefined, '', 'http://pay.example.com', 'javascript:alert(1)', 'sportreel://x', 'https://', ' https://a.b']) {
      expect(isSafeCheckoutUrl(bad as string)).toBe(false);
    }
  });

  it('shows agorot as shekels without dropping a fraction', () => {
    expect(formatIls(4900)).toBe('₪49');
    expect(formatIls(4990)).toBe('₪49.90');
    expect(formatIls(100)).toBe('₪1');
  });
});
