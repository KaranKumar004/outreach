'use client';

import React, { useState, useEffect, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { importLeadsAction, getProfilesAction } from '../../actions';
import { Profile } from '@/types';
import { 
  ArrowLeft, 
  Upload, 
  FileSpreadsheet, 
  Loader2, 
  CheckCircle2, 
  AlertCircle,
  HelpCircle
} from 'lucide-react';

export default function ImportLeadsPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<string>('');
  const [isLoadingProfiles, setIsLoadingProfiles] = useState(true);
  const [isPending, startTransition] = useTransition();
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  useEffect(() => {
    async function loadProfiles() {
      const res = await getProfilesAction();
      if (res.success && res.data) {
        setProfiles(res.data);
        // Try to get profileId from URL query client-side to avoid SSR suspense warnings
        const urlParams = new URLSearchParams(window.location.search);
        const urlProfileId = urlParams.get('profileId');
        if (urlProfileId && res.data.some(p => p.id === urlProfileId)) {
          setSelectedProfileId(urlProfileId);
        } else {
          const defaultProfile = res.data.find(p => p.name === 'Karan');
          setSelectedProfileId(defaultProfile?.id || res.data[0]?.id || '');
        }
      }
      setIsLoadingProfiles(false);
    }
    loadProfiles();
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0];
      if (selectedFile.type !== 'text/csv' && !selectedFile.name.endsWith('.csv')) {
        setResult({
          success: false,
          message: 'Please select a valid CSV file.',
        });
        setFile(null);
        return;
      }
      setFile(selectedFile);
      setResult(null);
    }
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!file) {
      setResult({ success: false, message: 'Please select a file to upload.' });
      return;
    }

    const formData = new FormData();
    formData.append('file', file);
    if (selectedProfileId) {
      formData.append('profileId', selectedProfileId);
    }

    setResult(null);
    startTransition(async () => {
      const res = await importLeadsAction(formData);
      if (res.success) {
        setResult({
          success: true,
          message: `Successfully imported ${res.count} leads! Redirecting to dashboard...`,
        });
        setFile(null);
        // Delay redirect to show success message
        setTimeout(() => {
          router.push('/dashboard');
          router.refresh();
        }, 2000);
      } else {
        setResult({
          success: false,
          message: res.error || 'Failed to import CSV.',
        });
      }
    });
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6 lg:px-8 flex-1 flex flex-col justify-center">
      {/* Back link */}
      <div className="mb-6">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Dashboard
        </Link>
      </div>

      <div className="bg-slate-950 border border-slate-800 rounded-2xl p-8 shadow-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-600/10 text-indigo-400 border border-indigo-500/20">
            <FileSpreadsheet className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Import Leads via CSV</h1>
            <p className="text-sm text-slate-400 mt-1">
              Upload your lead spreadsheet to initialize personalized campaigns.
            </p>
          </div>
        </div>

        {/* Info panel on template structure */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-8 text-sm">
          <div className="flex items-center gap-2 text-indigo-400 font-semibold mb-3">
            <HelpCircle className="h-4 w-4" />
            CSV File Specifications
          </div>
          <p className="text-slate-300 leading-relaxed">
            Your CSV file must include headers in the first row. The following fields are supported:
          </p>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-xs text-left border-collapse border border-slate-800">
              <thead>
                <tr className="bg-slate-950 text-slate-400 font-semibold border-b border-slate-800">
                  <th className="px-3 py-2 border-r border-slate-800">Column Name</th>
                  <th className="px-3 py-2 border-r border-slate-800">Required</th>
                  <th className="px-3 py-2">Description</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 text-slate-300">
                <tr>
                  <td className="px-3 py-2 font-mono text-indigo-300 border-r border-slate-800">business_name</td>
                  <td className="px-3 py-2 text-emerald-400 font-bold border-r border-slate-800">Yes</td>
                  <td className="px-3 py-2">The name of the company or establishment (e.g. Dreams Realty)</td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-mono text-indigo-300 border-r border-slate-800">email</td>
                  <td className="px-3 py-2 text-slate-500 border-r border-slate-800">No</td>
                  <td className="px-3 py-2">Primary contact email address (optional if phone is provided)</td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-mono text-indigo-300 border-r border-slate-800">business_type</td>
                  <td className="px-3 py-2 text-emerald-400 font-bold border-r border-slate-800">Yes</td>
                  <td className="px-3 py-2">Category (e.g. "real estate", "salon", "restaurant")</td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-mono text-slate-400 border-r border-slate-800">contact_name</td>
                  <td className="px-3 py-2 text-slate-500 border-r border-slate-800">No</td>
                  <td className="px-3 py-2">Name of the business owner or manager</td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-mono text-slate-400 border-r border-slate-800">phone</td>
                  <td className="px-3 py-2 text-slate-500 border-r border-slate-800">No</td>
                  <td className="px-3 py-2">Phone number (for future WhatsApp outbound)</td>
                </tr>
                <tr>
                  <td className="px-3 py-2 font-mono text-slate-400 border-r border-slate-800">context_notes</td>
                  <td className="px-3 py-2 text-slate-500 border-r border-slate-800">No</td>
                  <td className="px-3 py-2">Scraped details, observed challenges, or specific notes</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Upload form */}
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Target Profile Selector */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 mb-2">
            <label className="block text-sm font-semibold text-indigo-400 mb-2">
              Target Profile / Workspace
            </label>
            {isLoadingProfiles ? (
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Loading profiles...
              </div>
            ) : (
              <select
                value={selectedProfileId}
                onChange={(e) => setSelectedProfileId(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs font-semibold text-white focus:outline-none focus:border-indigo-500"
              >
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.sender_name} &bull; {p.sender_email})
                  </option>
                ))}
              </select>
            )}
            <p className="text-[11px] text-slate-500 mt-2">
              Leads imported from this CSV will be associated with the selected profile and will only be visible in its dashboard view.
            </p>
          </div>

          <div className="flex flex-col items-center justify-center border-2 border-dashed border-slate-800 hover:border-indigo-500/50 rounded-xl p-8 bg-slate-900/30 transition-all relative">
            <input
              type="file"
              accept=".csv"
              onChange={handleFileChange}
              disabled={isPending}
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
            />
            <Upload className="h-10 w-10 text-slate-500 mb-3" />
            {file ? (
              <div className="text-center">
                <p className="text-sm font-semibold text-white">{file.name}</p>
                <p className="text-xs text-slate-500 mt-1">{(file.size / 1024).toFixed(2)} KB</p>
              </div>
            ) : (
              <div className="text-center">
                <p className="text-sm font-semibold text-slate-300">Click to upload or drag & drop</p>
                <p className="text-xs text-slate-500 mt-1">Only CSV files are supported</p>
              </div>
            )}
          </div>

          {result && (
            <div className={`p-4 rounded-xl flex items-start gap-3 border ${
              result.success 
                ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' 
                : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
            }`}>
              {result.success ? (
                <CheckCircle2 className="h-5 w-5 shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="h-5 w-5 shrink-0 mt-0.5" />
              )}
              <div className="text-sm font-medium">{result.message}</div>
            </div>
          )}

          <button
            type="submit"
            disabled={!file || isPending}
            className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
          >
            {isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Importing...
              </>
            ) : (
              <>
                <Upload className="h-4 w-4" />
                Start Import
              </>
            )}
          </button>
        </form>
      </div>
      <footer className="mt-12 py-6 text-center text-xs text-slate-500 border-t border-slate-800 bg-slate-950/20 rounded-xl">
        Lead Finder &copy; {new Date().getFullYear()} &bull; Built with Next.js, Supabase, and Groq
      </footer>
    </div>
  );
}
