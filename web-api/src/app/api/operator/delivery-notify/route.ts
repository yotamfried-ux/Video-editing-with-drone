import { NextRequest, NextResponse } from 'next/server';
import { requireOperator } from '@/lib/operator-auth';
import { enforceRateLimit } from '@/lib/ratelimit';
import { sendDeliverySummaryEmail } from '@/lib/email';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Body = {
  recipients?: unknown;
  clips_links?: unknown;
  sport_type?: unknown;
  video_name?: unknown;
};

function validHttpsUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === 'https:';
  } catch {
    return false;
  }
}

export async function POST(req: NextRequest) {
  if (!requireOperator(req)) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const limited = await enforceRateLimit(req, 'delivery-notify', 20, 60);
  if (limited) return limited;

  let body: Body;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const recipients = Array.isArray(body.recipients)
    ? body.recipients.filter((item): item is string => typeof item === 'string').map((item) => item.trim())
    : [];
  const clipsLinks = Array.isArray(body.clips_links)
    ? body.clips_links.filter((item): item is string => typeof item === 'string').map((item) => item.trim())
    : [];
  const sportType = typeof body.sport_type === 'string' ? body.sport_type.trim().slice(0, 64) : 'sport';
  const videoName = typeof body.video_name === 'string' ? body.video_name.trim().slice(0, 200) : 'highlight reel';

  if (
    recipients.length < 1 || recipients.length > 10 ||
    recipients.some((email) => !EMAIL_RE.test(email)) ||
    clipsLinks.length < 1 || clipsLinks.length > 10 ||
    clipsLinks.some((link) => !validHttpsUrl(link))
  ) {
    return NextResponse.json({ error: 'Invalid notification payload' }, { status: 400 });
  }

  try {
    const messageId = await sendDeliverySummaryEmail(recipients, clipsLinks, sportType, videoName);
    return NextResponse.json({ ok: true, message_id: messageId });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Notification send failed' },
      { status: 502 },
    );
  }
}
