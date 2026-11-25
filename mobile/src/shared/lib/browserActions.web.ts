export async function openCheckoutUrl(url: string): Promise<void> {
  if (typeof window !== 'undefined') {
    // Same-tab navigation avoids mobile/Safari popup blockers after async checkout session creation.
    window.location.assign(url);
  }
}

export async function openDownloadUrl(url: string): Promise<void> {
  if (typeof window !== 'undefined') {
    const opened = window.open(url, '_blank', 'noopener,noreferrer');
    if (!opened) {
      window.location.assign(url);
    }
  }
}

export async function openExternalUrl(url: string): Promise<void> {
  if (typeof window !== 'undefined') {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}

export async function shareWhatsAppMessage(encodedMsg: string): Promise<void> {
  if (typeof window !== 'undefined') {
    window.open(`https://wa.me/?text=${encodedMsg}`, '_blank', 'noopener,noreferrer');
  }
}
