import { supabase } from '@/lib/supabase';
import LeadClient from './lead-client';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

export const dynamic = 'force-dynamic';

interface LeadPageProps {
  params: Promise<{ id: string }>;
}

export default async function LeadPage({ params }: LeadPageProps) {
  const { id } = await params;
  
  let lead = null;
  let messages = [];
  let dbError = null;

  try {
    // Fetch lead details
    const { data: leadData, error: leadError } = await supabase
      .from('leads')
      .select('*')
      .eq('id', id)
      .single();

    if (leadError) {
      dbError = leadError.message;
    } else {
      lead = leadData;

      // Fetch all messages for this lead
      const { data: msgData, error: msgError } = await supabase
        .from('messages')
        .select('*')
        .eq('lead_id', id)
        .order('created_at', { ascending: false });

      if (msgError) {
        console.error('Error fetching messages:', msgError);
      } else {
        messages = msgData || [];
      }
    }
  } catch (err: any) {
    dbError = err.message || 'Failed to load lead details';
  }

  if (dbError || !lead) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8 flex-1 flex flex-col justify-center items-center">
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 p-6 rounded-xl max-w-2xl text-center shadow-lg">
          <h2 className="text-xl font-bold mb-2">Lead Not Found</h2>
          <p className="text-sm text-slate-400 mb-4">
            Could not find details for lead ID: <code className="bg-slate-900 px-1 py-0.5 rounded text-rose-300 font-mono">{id}</code>.
          </p>
          <div className="text-xs font-mono bg-slate-950 p-3 rounded text-left border border-slate-800 text-rose-300 whitespace-pre-wrap mb-4">
            Error: {dbError || 'Record not found in the database.'}
          </div>
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-sm bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-2 px-4 rounded-lg transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return <LeadClient lead={lead} messages={messages} />;
}
