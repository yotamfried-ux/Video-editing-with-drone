import { Resend } from 'resend';

const FROM = process.env.RESEND_FROM_EMAIL ?? 'onboarding@resend.dev';
const APP_URL = process.env.APP_DOMAIN
  ? `https://${process.env.APP_DOMAIN}`
  : 'https://video-editing-with-drone.vercel.app';

const resend = () => new Resend(process.env.RESEND_API_KEY);

export async function sendReelReadyEmail(to: string, reelId: string) {
  await resend().emails.send({
    from: `SportReel <${FROM}>`,
    to,
    subject: 'Your SportReel highlight is ready! 🎬',
    html: `
      <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
        <h2 style="color:#5B6EF5">Your highlight reel is ready</h2>
        <p>We finished editing your highlight reel and it's ready to watch.</p>
        <a href="${APP_URL}/reel/${reelId}"
           style="display:inline-block;padding:12px 24px;background:#5B6EF5;color:#fff;border-radius:8px;text-decoration:none;font-weight:600">
          Watch your reel
        </a>
        <p style="color:#888;font-size:12px;margin-top:24px">SportReel · Unsubscribe</p>
      </div>`,
  });
}

export async function sendPaymentConfirmEmail(to: string, reelId: string, amountIls: number) {
  await resend().emails.send({
    from: `SportReel <${FROM}>`,
    to,
    subject: 'Payment confirmed ✓',
    html: `
      <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
        <h2 style="color:#5B6EF5">Payment received</h2>
        <p>We received your payment of <strong>₪${Math.round(amountIls / 100)}</strong>.</p>
        <a href="${APP_URL}/reel/${reelId}"
           style="display:inline-block;padding:12px 24px;background:#5B6EF5;color:#fff;border-radius:8px;text-decoration:none;font-weight:600">
          Watch your reel
        </a>
        <p style="color:#888;font-size:12px;margin-top:24px">SportReel</p>
      </div>`,
  });
}

export async function sendOperatorNotifyEmail(reelId: string, sport: string) {
  const to = process.env.NOTIFY_EMAIL ?? process.env.OWNER_EMAIL;
  if (!to) return;
  await resend().emails.send({
    from: `SportReel <${FROM}>`,
    to,
    subject: `New reel ready for review — ${sport}`,
    html: `
      <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
        <h2 style="color:#5B6EF5">New reel to review</h2>
        <p>A new <strong>${sport}</strong> highlight reel is waiting for your approval.</p>
        <a href="${APP_URL}/operator/review"
           style="display:inline-block;padding:12px 24px;background:#5B6EF5;color:#fff;border-radius:8px;text-decoration:none;font-weight:600">
          Review in app
        </a>
      </div>`,
  });
}
