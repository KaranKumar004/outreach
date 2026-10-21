import { supabase } from '@/lib/supabase';
import DashboardClient from '../../dashboard-client';

export const dynamic = 'force-dynamic';

export default async function DashboardPage() {
  let leads = [];
  let profiles = [];
  let dbError = null;

  try {
    // Fetch leads
    const { data: leadsData, error: leadsError } = await supabase
      .from('leads')
      .select('*, messages(*)')
      .order('created_at', { ascending: false });

    // Fetch profiles
    const { data: profilesData, error: profilesError } = await supabase
      .from('profiles')
      .select('*')
      .order('name', { ascending: true });

    if (leadsError) {
      dbError = leadsError.message;
    } else if (profilesError) {
      dbError = profilesError.message;
    } else {
      leads = leadsData || [];
      profiles = profilesData || [];
    }
  } catch (err: any) {
    dbError = err.message || 'Failed to connect to Supabase';
  }

  if (dbError) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8 flex-1 flex flex-col justify-center items-center">
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 p-6 rounded-xl max-w-2xl text-center shadow-lg">
          <h2 className="text-xl font-bold mb-2">Database Connection Error</h2>
          <p className="text-sm text-slate-400 mb-4">
            Could not fetch data from Supabase. Make sure your database tables are created and environment variables are correctly configured in `.env.local`.
          </p>
          <div className="text-xs font-mono bg-slate-950 p-3 rounded text-left border border-slate-800 text-rose-300 whitespace-pre-wrap">
            Error: {dbError}
          </div>
          <p className="mt-4 text-xs text-slate-500">
            Ensure you run the SQL definitions from <code className="bg-slate-800 px-1 py-0.5 rounded">schema.sql</code> inside your Supabase project.
          </p>
        </div>
      </div>
    );
  }

  return <DashboardClient initialLeads={leads} initialProfiles={profiles} />;
}
