import crypto from 'crypto';

export function getSignedStreamUrl(streamUid: string, ttlSeconds = 3600): string {
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  const payload = `${streamUid}.${exp}`;
  const sig = crypto
    .createHmac('sha256', process.env.CLOUDFLARE_STREAM_API_TOKEN!)
    .update(payload)
    .digest('hex');
  const customer = process.env.CLOUDFLARE_CUSTOMER_CODE!;
  return `https://customer-${customer}.cloudflarestream.com/${streamUid}/manifest/video.m3u8?token=${sig}&exp=${exp}`;
}
