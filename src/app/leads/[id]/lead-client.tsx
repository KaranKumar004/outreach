'use client';

import React, { useState, useTransition } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { 
  saveFinalTextAction, 
  sendPitchAction, 
  updateLeadStatusAction 
} from '../../actions';
import { Lead, Message, LeadStatus } from '@/types';
import { 
  ArrowLeft, 
  Building2, 
  User, 
  Mail, 
  Phone, 
  FileText, 
  Calendar, 
  Send, 
  Save, 
  Sparkles,
  CheckCircle,
  History,
  Clock,
  ChevronRight,
  AlertTriangle,
  Loader2
} from 'lucide-react';

interface LeadClientProps {
  lead: Lead;
  messages: Message[];
}

export default function LeadClient({ lead, messages }: LeadClientProps) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [isSaving, startSaving] = useTransition();
  
  // Get the latest message (most recently created)
  const latestMessage = messages.length > 0 
    ? [...messages].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0]
    : null;

  // The draft content is what is in final_text, or falls back to generated_text
  const [pitchText, setPitchText] = useState(
    latestMessage ? (latestMessage.final_text || latestMessage.generated_text) : ''
  );
  
  const [status, setStatus] = useState<LeadStatus>(lead.status);
  const [feedback, setFeedback] = useState<{ success: boolean; message: string } | null>(null);

  const handleSaveDraft = () => {
    if (!latestMessage) return;
    
    setFeedback(null);
    startSaving(async () => {
      const res = await saveFinalTextAction(latestMessage.id, pitchText);
      if (res.success) {
        setFeedback({ success: true, message: 'Draft saved successfully!' });
        router.refresh();
      } else {
        setFeedback({ success: false, message: res.error || 'Failed to save draft' });
      }
    });
  };

  const handleSendEmail = () => {
    if (!latestMessage) return;
    if (!pitchText.trim()) {
      alert('Cannot send an empty email pitch.');
      return;
    }

    if (!confirm(`Are you sure you want to send this personalized pitch to ${lead.email}?`)) {
      return;
    }

    setFeedback(null);
    startTransition(async () => {
      const res = await sendPitchAction(
        lead.id,
        latestMessage.id,
        lead.email || '',
        lead.business_name,
        pitchText
      );
      if (res.success) {
        setFeedback({ success: true, message: 'Email sent successfully!' });
        setStatus('sent');
        router.refresh();
      } else {
        setFeedback({ success: false, message: res.error || 'Failed to send email' });
      }
    });
  };

  const handleStatusChange = async (newStatus: LeadStatus) => {
    setFeedback(null);
    setStatus(newStatus);
    const res = await updateLeadStatusAction(lead.id, newStatus);
    if (res.success) {
      setFeedback({ success: true, message: `Lead status updated to ${newStatus.replace('_', ' ')}` });
      router.refresh();
    } else {
      setFeedback({ success: false, message: res.error || 'Failed to update status' });
      setStatus(lead.status); // revert
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 flex-1 flex flex-col">
      {/* Back to Dashboard */}
      <div className="mb-6 flex items-center justify-between">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Dashboard
        </Link>
        <span className="text-xs text-slate-500 font-mono">ID: {lead.id}</span>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-3 flex-1">
        {/* Left Column: Lead Information Card */}
        <div className="lg:col-span-1 space-y-6">
          <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
            <div>
              <div className="text-xs text-indigo-400 font-bold uppercase tracking-wider mb-1">
                {lead.business_type}
              </div>
              <h2 className="text-2xl font-bold text-white tracking-tight">
                {lead.business_name}
              </h2>
            </div>

            {/* Status Manager */}
            <div className="border-t border-b border-slate-800 py-4 space-y-2">
              <label className="text-xs font-semibold text-slate-400">Lead Status</label>
              <select
                value={status}
                onChange={(e) => handleStatusChange(e.target.value as LeadStatus)}
                className="w-full bg-slate-900 border border-slate-800 rounded-lg py-2 px-3 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              >
                <option value="draft">Draft</option>
                <option value="sent">Sent</option>
                <option value="replied">Replied</option>
                <option value="no_response">No Response</option>
                <option value="won">Won</option>
                <option value="lost">Lost</option>
              </select>
            </div>

            {/* Lead Metadata */}
            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <User className="h-4 w-4 text-slate-500 shrink-0 mt-0.5" />
                <div>
                  <div className="text-xs text-slate-500 font-medium">Contact Person</div>
                  <div className="text-sm text-slate-200">{lead.contact_name || '—'}</div>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <Mail className="h-4 w-4 text-slate-500 shrink-0 mt-0.5" />
                <div>
                  <div className="text-xs text-slate-500 font-medium">Email Address</div>
                  <div className="text-sm text-slate-200 break-all">{lead.email}</div>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <Phone className="h-4 w-4 text-slate-500 shrink-0 mt-0.5" />
                <div>
                  <div className="text-xs text-slate-500 font-medium">Phone Number</div>
                  <div className="text-sm text-slate-200">{lead.phone || '—'}</div>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <Calendar className="h-4 w-4 text-slate-500 shrink-0 mt-0.5" />
                <div>
                  <div className="text-xs text-slate-500 font-medium">Last Contacted</div>
                  <div suppressHydrationWarning className="text-sm text-slate-200">
                    {lead.last_contacted_at 
                      ? new Date(lead.last_contacted_at).toLocaleString() 
                      : 'Never'}
                  </div>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <Clock className="h-4 w-4 text-slate-500 shrink-0 mt-0.5" />
                <div>
                  <div className="text-xs text-slate-500 font-medium">Follow-Up Due</div>
                  <div suppressHydrationWarning className="text-sm text-slate-200">
                    {lead.follow_up_due_at 
                      ? new Date(lead.follow_up_due_at).toLocaleDateString() 
                      : 'Not Scheduled'}
                  </div>
                </div>
              </div>
            </div>

            {/* Context Notes */}
            {lead.context_notes && (
              <div className="border-t border-slate-800 pt-4 space-y-2">
                <div className="text-xs font-semibold text-slate-400 flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5" />
                  Context Notes
                </div>
                <div className="text-sm text-slate-300 bg-slate-900/60 p-3 rounded-lg border border-slate-800 whitespace-pre-wrap leading-relaxed">
                  {lead.context_notes}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Column: AI Pitch Draft Editor & History */}
        <div className="lg:col-span-2 space-y-6">
          {/* Pitch Editor Card */}
          <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col h-full min-h-[450px]">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-indigo-400" />
                <h3 className="text-lg font-semibold text-white">
                  {latestMessage?.message_type === 'follow_up' ? 'AI Follow-Up Pitch' : 'AI Cold Outreach Pitch'}
                </h3>
              </div>
              {latestMessage && (
                <span className="text-xs bg-slate-900 border border-slate-800 text-slate-400 py-1 px-2.5 rounded-full font-semibold">
                  Model: Llama 3.3 (Groq)
                </span>
              )}
            </div>

            {feedback && (
              <div className={`mb-4 p-4 rounded-xl flex items-start gap-3 border ${
                feedback.success 
                  ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' 
                  : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
              }`}>
                <CheckCircle className="h-5 w-5 shrink-0 mt-0.5" />
                <div className="text-sm font-medium">{feedback.message}</div>
              </div>
            )}

            {latestMessage ? (
              <div className="flex-1 flex flex-col space-y-4">
                <textarea
                  value={pitchText}
                  onChange={(e) => setPitchText(e.target.value)}
                  disabled={isPending || isSaving}
                  rows={8}
                  className="flex-1 w-full bg-slate-900 border border-slate-800 rounded-xl p-4 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 leading-relaxed font-mono disabled:opacity-50"
                  placeholder="Review or write your cold pitch here..."
                />
                
                <div className="flex justify-between items-center gap-4 pt-2">
                  <span className="text-xs text-slate-500">
                    Character Count: <strong className="text-slate-400">{pitchText.length}</strong> &bull; Word Count: <strong className="text-slate-400">{pitchText.split(/\s+/).filter(Boolean).length}</strong>
                  </span>
                  <div className="flex gap-3">
                    <button
                      onClick={handleSaveDraft}
                      disabled={isSaving || isPending}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-700 disabled:opacity-50"
                    >
                      {isSaving ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Saving...
                        </>
                      ) : (
                        <>
                          <Save className="h-4 w-4" />
                          Save Draft
                        </>
                      )}
                    </button>
                    <button
                      onClick={handleSendEmail}
                      disabled={isPending || isSaving}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:opacity-50 hover:shadow-lg hover:shadow-indigo-500/20"
                    >
                      {isPending ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Sending...
                        </>
                      ) : (
                        <>
                          <Send className="h-4 w-4" />
                          Send Email
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center text-center p-8 bg-slate-900/20 border border-dashed border-slate-800 rounded-xl">
                <AlertTriangle className="h-8 w-8 text-yellow-500 mb-3" />
                <h4 className="text-md font-semibold text-white">No AI draft found</h4>
                <p className="text-sm text-slate-400 max-w-sm mt-1">
                  Pitches are generated in batches from the dashboard. Go back and click "Generate Pitches" or generate manually for this lead.
                </p>
                <Link
                  href="/"
                  className="mt-4 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500 transition-colors"
                >
                  Go to Dashboard
                </Link>
              </div>
            )}
          </div>

          {/* Message History timeline */}
          <div className="bg-slate-950 border border-slate-800 rounded-2xl p-6 shadow-xl">
            <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <History className="h-5 w-5 text-indigo-400" />
              Communication History
            </h3>

            {messages.length === 0 ? (
              <div className="text-sm text-slate-500 py-4">No outreach messages recorded yet.</div>
            ) : (
              <div className="relative border-l border-slate-800 pl-6 ml-2 space-y-6">
                {[...messages]
                  .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
                  .map((msg) => (
                    <div key={msg.id} className="relative">
                      {/* Timeline dot */}
                      <span className={`absolute -left-[31px] top-1.5 flex h-4 w-4 items-center justify-center rounded-full ring-4 ring-slate-950 ${
                        msg.sent_at 
                          ? 'bg-emerald-500 shadow-md shadow-emerald-500/30' 
                          : 'bg-yellow-500 shadow-md shadow-yellow-500/30'
                      }`} />
                      
                      <div className="space-y-1.5">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-slate-200">
                            {msg.message_type === 'follow_up' ? 'Follow-Up Email' : 'Initial Outreach'}
                          </span>
                          <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded-full ${
                            msg.sent_at 
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' 
                              : 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'
                          }`}>
                            {msg.sent_at ? 'Sent' : 'Draft'}
                          </span>
                          <span suppressHydrationWarning className="text-xs text-slate-500 font-mono ml-auto">
                            {new Date(msg.created_at).toLocaleDateString()}
                          </span>
                        </div>
                        <div className="text-xs text-slate-400 whitespace-pre-wrap bg-slate-900/60 p-3 rounded-lg border border-slate-800 leading-relaxed max-h-48 overflow-y-auto font-mono">
                          {msg.final_text || msg.generated_text}
                        </div>
                        {msg.sent_at && (
                          <div suppressHydrationWarning className="text-[11px] text-slate-500">
                            Sent at: {new Date(msg.sent_at).toLocaleString()}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
