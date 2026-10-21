import { NextResponse } from 'next/server';
import { triggerFollowUpsAction } from '@/app/actions';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  try {
    // Optional authorization: Only verify if CRON_SECRET is configured
    const cronSecret = process.env.CRON_SECRET;
    if (cronSecret) {
      const authHeader = request.headers.get('authorization');
      if (authHeader !== `Bearer ${cronSecret}`) {
        return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
      }
    }

    const res = await triggerFollowUpsAction();

    if (!res.success) {
      return NextResponse.json({ error: res.error || 'Follow-up logic failed' }, { status: 500 });
    }

    return NextResponse.json({
      success: true,
      processed: res.count ?? 0,
      message: `Successfully processed ${res.count ?? 0} follow-up drafts.`,
    });
  } catch (error: any) {
    console.error('Cron: Unhandled error in follow-up cron:', error);
    return NextResponse.json({ error: error.message || 'Internal server error' }, { status: 500 });
  }
}
