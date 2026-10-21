'use client';

import React, { useState, useEffect, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { 
  generatePitchesAction, 
  deleteLeadAction, 
  triggerFollowUpsAction,
  runLeadFinderAction,
  runLeadFinderBuildingsAction,
  saveFinalTextAction,
  sendPitchAction,
  updateLeadStatusAction,
  generateSinglePitchAction,
  sendAllDraftsAction,
  markLeadBouncedAction
} from './actions';
import { Lead, LeadStatus, Message, Profile } from '@/types';
import { 
  Plus, 
  Sparkles, 
  Trash2, 
  Search, 
  Mail, 
  Phone, 
  ExternalLink,
  Loader2,
  CheckCircle,
  FileSpreadsheet,
  Clock,
  Building2,
  User,
  Calendar,
  Save,
  Send,
  History,
  AlertTriangle,
  ChevronRight,
  Filter,
  Play,
  RefreshCw
} from 'lucide-react';

interface DashboardClientProps {
  initialLeads: (Lead & { messages: Message[] })[];
  initialProfiles: Profile[];
}

const STATUS_OPTIONS: { value: 'all' | LeadStatus; label: string; color: string; badge: string }[] = [
  { value: 'all', label: 'All Leads', color: 'bg-slate-700 text-slate-200', badge: 'bg-slate-800 text-slate-400' },
  { value: 'draft', label: 'Draft', color: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30', badge: 'bg-yellow-500/10 text-yellow-500' },
  { value: 'sent', label: 'Sent', color: 'bg-blue-500/20 text-blue-400 border border-blue-500/30', badge: 'bg-blue-500/10 text-blue-500' },
  { value: 'replied', label: 'Replied', color: 'bg-green-500/20 text-green-400 border border-green-500/30', badge: 'bg-green-500/10 text-green-500' },
  { value: 'no_response', label: 'No Response', color: 'bg-purple-500/20 text-purple-400 border border-purple-500/30', badge: 'bg-purple-500/10 text-purple-500' },
  { value: 'won', label: 'Won', color: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30', badge: 'bg-emerald-500/10 text-emerald-500' },
  { value: 'lost', label: 'Lost', color: 'bg-rose-500/20 text-rose-400 border border-rose-500/30', badge: 'bg-rose-500/10 text-rose-500' },
];

const BENGALURU_LOCALITIES: Record<string, string[]> = {
  "Central (0–5km)": [
    "Viveknagar", "Wilson Garden", "Adugodi", "Richmond Town", "Shanti Nagar", 
    "Langford Town", "Lalbagh", "Cooke Town", "Frazer Town", "Cox Town", 
    "Domlur", "Austin Town", "MG Road", "Brigade Road", "Vasanth Nagar", "Ulsoor"
  ],
  "South (5–25km)": [
    "Koramangala", "Jayanagar", "Basavanagudi", "BTM Layout", "HSR Layout", 
    "JP Nagar", "Banashankari", "Uttarahalli", "Bannerghatta Road", "Hulimavu", 
    "Bommanahalli", "Begur", "Electronic City", "Singasandra", "Madiwala"
  ],
  "East (5–28km)": [
    "Indiranagar", "Old Airport Road", "CV Raman Nagar", "Marathahalli", "Bellandur", 
    "Sarjapur Road", "Brookefield", "Kundalahalli", "Mahadevapura", "Whitefield", 
    "ITPL", "Hoodi", "Varthur", "KR Puram", "Ramamurthy Nagar", "Banaswadi"
  ],
  "North (5–28km)": [
    "Hebbal", "RT Nagar", "Sanjaynagar", "Sadashivanagar", "Malleshwaram", 
    "Yeshwanthpur", "Jalahalli", "Peenya", "Vidyaranyapura", "Yelahanka", 
    "Jakkur", "Thanisandra", "Hennur", "Kalyan Nagar"
  ],
  "West (5–22km)": [
    "Rajajinagar", "Vijayanagar", "Basaveshwaranagar", "Nagarbhavi", "Kengeri", 
    "RR Nagar", "Mysore Road", "Chandra Layout", "Nayandahalli"
  ]
};

export default function DashboardClient({ initialLeads, initialProfiles }: DashboardClientProps) {
  const router = useRouter();
  const [leads, setLeads] = useState(initialLeads);
  const [profiles, setProfiles] = useState(initialProfiles);
  
  // Default active profile to "Karan" if found, otherwise the first profile, or fallback to empty
  const [activeProfileId, setActiveProfileId] = useState<string>(() => {
    const karan = initialProfiles.find(p => p.name === 'Karan');
    return karan?.id || initialProfiles[0]?.id || '';
  });

  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null);
  const [selectedStatus, setSelectedStatus] = useState<'all' | LeadStatus>('all');
  const [contactFilter, setContactFilter] = useState<'all' | 'email' | 'phone'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [editorTab, setEditorTab] = useState<'edit' | 'preview'>('edit');
  
  // Scraper inputs state
  const [showScraper, setShowScraper] = useState(false);
  const [scraperMode, setScraperMode] = useState<'standard' | 'commercial'>('standard');
  const [scraperType, setScraperType] = useState('salon');
  const [scraperAreas, setScraperAreas] = useState('Whitefield');
  const [scraperRadius, setScraperRadius] = useState(1.5);

  // Reset selected lead, status filter, and editor tab when profile changes
  useEffect(() => {
    setSelectedLeadId(null);
    setSelectedStatus('all');
    setContactFilter('all');
    setEditorTab('edit');
  }, [activeProfileId]);

  // Reset editor tab when selected lead changes
  useEffect(() => {
    setEditorTab('edit');
  }, [selectedLeadId]);

  // Sync props to state when they change from page.tsx (like after router.refresh() from import)
  useEffect(() => {
    setLeads(initialLeads);
  }, [initialLeads]);

  useEffect(() => {
    setProfiles(initialProfiles);
  }, [initialProfiles]);

  // Adjust default scraper categories when mode changes
  useEffect(() => {
    if (scraperMode === 'standard') {
      setScraperType('salon');
    } else {
      setScraperType('office');
    }
  }, [scraperMode]);

  // Transitions & states
  const [isGenerating, startGenerating] = useTransition();
  const [isFollowingUp, startFollowingUp] = useTransition();
  const [isScraping, startScraping] = useTransition();
  const [isSaving, startSaving] = useTransition();
  const [isSending, startSending] = useTransition();
  const [isGeneratingPitch, setIsGeneratingPitch] = useState(false);
  const [isSendingAll, setIsSendingAll] = useState(false);
  const [sendProgress, setSendProgress] = useState<{
    current: number;
    total: number;
    businessName: string;
    failedCount: number;
  } | null>(null);

  // Feedback states
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [detailFeedback, setDetailFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Selected lead computation
  const selectedLead = leads.find(l => l.id === selectedLeadId);
  const latestMessage = selectedLead?.messages?.length
    ? [...selectedLead.messages].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0]
    : null;

  // Pitch text edit state
  const [pitchText, setPitchText] = useState('');

  // Reset editable text when selected lead changes
  useEffect(() => {
    if (latestMessage) {
      setPitchText(latestMessage.final_text || latestMessage.generated_text);
    } else {
      setPitchText('');
    }
    setDetailFeedback(null);
  }, [selectedLeadId, latestMessage?.id]);

  // Clear notification after 5s
  useEffect(() => {
    if (notification) {
      const timer = setTimeout(() => setNotification(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [notification]);

  // Filter leads (supporting nullable emails and phone-only leads)
  const filteredLeads = leads.filter(lead => {
    const matchesProfile = lead.profile_id === activeProfileId;
    const matchesStatus = selectedStatus === 'all' || lead.status === selectedStatus;
    const matchesContactFilter = contactFilter === 'all' || lead.contact_method === contactFilter;
    
    // Allow phone-only leads or leads with valid email
    const hasValidContact = lead.contact_method === 'phone' || (lead.email && lead.email.trim() !== '');
    
    const searchLower = searchQuery.toLowerCase();
    const matchesSearch = 
      lead.business_name.toLowerCase().includes(searchLower) ||
      (lead.contact_name?.toLowerCase() || '').includes(searchLower) ||
      (lead.email || '').toLowerCase().includes(searchLower) ||
      lead.business_type.toLowerCase().includes(searchLower);
    
    return matchesProfile && matchesStatus && matchesSearch && hasValidContact && matchesContactFilter;
  });

  // Helper to group sent leads by date
  const getSentGroups = () => {
    const groups: { date: string; leadsList: typeof filteredLeads }[] = [];
    filteredLeads.forEach(lead => {
      let dateKey = 'Unknown Date';
      if (lead.last_contacted_at) {
        dateKey = new Date(lead.last_contacted_at).toLocaleDateString(undefined, {
          weekday: 'short',
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        });
      } else {
        dateKey = new Date(lead.created_at).toLocaleDateString(undefined, {
          weekday: 'short',
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        });
      }
      
      const existingGroup = groups.find(g => g.date === dateKey);
      if (existingGroup) {
        existingGroup.leadsList.push(lead);
      } else {
        groups.push({ date: dateKey, leadsList: [lead] });
      }
    });
    
    // Sort groups by date descending
    groups.sort((a, b) => {
      const dateA = a.leadsList[0]?.last_contacted_at || a.leadsList[0]?.created_at || '';
      const dateB = b.leadsList[0]?.last_contacted_at || b.leadsList[0]?.created_at || '';
      return new Date(dateB).getTime() - new Date(dateA).getTime();
    });
    
    return groups;
  };

  // Helper to get HTML preview for active lead and pitch text
  const getPreviewHtml = () => {
    if (!selectedLead) return '';
    const activeProfile = profiles.find(p => p.id === activeProfileId);
    if (!activeProfile) return '';
    
    const isSKM = activeProfile.name === 'SKM Dev Team';
    if (isSKM && activeProfile.email_template) {
      let html = activeProfile.email_template;
      // Target paragraph placeholders to replace with edited pitch text
      const defaultParagraph = "Buildings always need work eventually &mdash; a renovation, an interior upgrade, structural repairs, or scaffolding for maintenance. When that time comes for {{company_name}}, I''d like SKM Enterprises to be the name you already know.";
      const defaultParagraphPlain = "Buildings always need work eventually &mdash; a renovation, an interior upgrade, structural repairs, or scaffolding for maintenance. When that time comes for {{company_name}}, I'd like SKM Enterprises to be the name you already know.";
      
      // Inject edited pitch text
      html = html.replace(defaultParagraph, pitchText);
      html = html.replace(defaultParagraphPlain, pitchText);
      
      // Substitute variables
      const contactName = selectedLead.contact_name || 'Owner / Manager';
      html = html.replace(/\{\{company_name\}\}/g, selectedLead.business_name);
      html = html.replace(/\{\{first_name\}\}/g, contactName);
      
      return html;
    } else {
      // For Karan (plain text), format in simple email layout
      const contactName = selectedLead.contact_name || 'Owner / Manager';
      const textWithVars = pitchText
        .replace(/\{company_name\}/g, selectedLead.business_name)
        .replace(/\{first_name\}/g, contactName);
      
      return `
        <!DOCTYPE html>
        <html>
          <body style="font-family: sans-serif; padding: 20px; color: #1e293b; background: #f8fafc; margin: 0;">
            <div style="background: white; border: 1px solid #e2e8f0; padding: 24px; border-radius: 12px; max-width: 600px; margin: 0 auto; white-space: pre-wrap; line-height: 1.6; font-size: 14px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
${textWithVars}
            </div>
          </body>
        </html>
      `;
    }
  };

  // Action handlers
  const handleGeneratePitches = () => {
    setNotification(null);
    startGenerating(async () => {
      const res = await generatePitchesAction(activeProfileId);
      if (res.success) {
        setNotification({
          type: 'success',
          message: res.count !== undefined && res.count > 0 
            ? `Successfully generated ${res.count} personalized pitches!`
            : 'No new pitches needed (all draft leads already have pitches).'
        });
        router.refresh();
      } else {
        setNotification({ type: 'error', message: res.error || 'Failed to generate pitches.' });
      }
    });
  };

  const handleRePitchLead = async () => {
    if (!selectedLeadId) return;
    setDetailFeedback(null);
    setIsGeneratingPitch(true);
    try {
      const res = await generateSinglePitchAction(selectedLeadId, activeProfileId);
      if (res.success) {
        setDetailFeedback({ type: 'success', message: res.message || 'Pitch regenerated successfully!' });
        // Delay refresh slightly to let user see success message
        setTimeout(() => router.refresh(), 1000);
      } else {
        setDetailFeedback({ type: 'error', message: res.error || 'Failed to generate pitch.' });
      }
    } catch (err: any) {
      setDetailFeedback({ type: 'error', message: err.message || 'Failed to generate pitch.' });
    } finally {
      setIsGeneratingPitch(false);
    }
  };

  const handleSendAllDrafts = async () => {
    const draftsToSend = leads.filter(l => 
      l.profile_id === activeProfileId && 
      l.status === 'draft' && 
      l.contact_method === 'email' && 
      l.email && 
      l.email.trim() !== '' &&
      l.messages?.some(m => m.message_type === 'initial' && !m.sent_at)
    );

    if (draftsToSend.length === 0) {
      alert("No unsent draft emails found for this profile. Please generate pitches first.");
      return;
    }

    if (!confirm(`Are you sure you want to automatically send emails to all ${draftsToSend.length} reviewed drafts?`)) {
      return;
    }

    setNotification(null);
    setIsSendingAll(true);
    setSendProgress({
      current: 1,
      total: draftsToSend.length,
      businessName: draftsToSend[0].business_name,
      failedCount: 0
    });

    let successCount = 0;
    let failedCount = 0;

    for (let i = 0; i < draftsToSend.length; i++) {
      const lead = draftsToSend[i];
      const draftMsg = lead.messages.find(m => m.message_type === 'initial' && !m.sent_at);
      if (!draftMsg) continue;

      const pitchContent = draftMsg.final_text || draftMsg.generated_text;

      // Update progress state
      setSendProgress({
        current: i + 1,
        total: draftsToSend.length,
        businessName: lead.business_name,
        failedCount: failedCount
      });

      try {
        const res = await sendPitchAction(
          lead.id,
          draftMsg.id,
          lead.email || '',
          lead.business_name,
          pitchContent
        );

        if (res.success) {
          successCount++;
          // Update local state to show 'sent' immediately
          const nowStr = new Date().toISOString();
          setLeads(prevLeads => prevLeads.map(l => {
            if (l.id === lead.id) {
              const updatedMessages = l.messages.map(m => {
                if (m.id === draftMsg.id) {
                  return { ...m, final_text: pitchContent, sent_at: nowStr };
                }
                return m;
              });
              return { ...l, status: 'sent', last_contacted_at: nowStr, messages: updatedMessages };
            }
            return l;
          }));
        } else {
          failedCount++;
          console.error(`Failed to send email to ${lead.business_name}:`, res.error);
        }
      } catch (error) {
        failedCount++;
        console.error(`Error sending email to ${lead.business_name}:`, error);
      }

      // Add a short delay between sends for visual flow and SMTP safety
      if (i < draftsToSend.length - 1) {
        await new Promise(resolve => setTimeout(resolve, 800));
      }
    }

    setIsSendingAll(false);
    setSendProgress(null);

    if (failedCount === 0) {
      setNotification({
        type: 'success',
        message: `Successfully sent all ${successCount} outreach emails automatically!`
      });
    } else {
      setNotification({
        type: 'error',
        message: `Finished bulk send: ${successCount} succeeded, ${failedCount} failed. Check logs for details.`
      });
    }
  };

  const handleMarkBounced = async () => {
    if (!selectedLead) return;
    if (!confirm(`Are you sure you want to mark this email bounce for ${selectedLead.business_name}? This will set status to lost and update sent_log.`)) {
      return;
    }
    
    setDetailFeedback(null);
    try {
      const res = await markLeadBouncedAction(selectedLead.id);
      if (res.success) {
        setDetailFeedback({ type: 'success', message: 'Lead successfully marked as bounced.' });
        // Update local state
        setLeads(prevLeads => prevLeads.map(l => {
          if (l.id === selectedLead.id) {
            const bounceNote = l.context_notes 
              ? `[BOUNCED] ${l.context_notes}`
              : '[BOUNCED] Email bounced.';
            return { ...l, status: 'lost', context_notes: bounceNote };
          }
          return l;
        }));
      } else {
        setDetailFeedback({ type: 'error', message: res.error || 'Failed to mark bounce.' });
      }
    } catch (err: any) {
      setDetailFeedback({ type: 'error', message: err.message || 'Failed to mark bounce.' });
    }
  };

  const handleRunFollowUps = () => {
    setNotification(null);
    startFollowingUp(async () => {
      const res = await triggerFollowUpsAction();
      if (res.success) {
        setNotification({
          type: 'success',
          message: res.count !== undefined && res.count > 0 
            ? `Successfully created ${res.count} follow-up drafts!`
            : 'No new follow-ups are due right now.'
        });
        setTimeout(() => router.refresh(), 1000);
      } else {
        setNotification({ type: 'error', message: res.error || 'Failed to run follow-ups.' });
      }
    });
  };

  const handleRunScraper = (e: React.FormEvent) => {
    e.preventDefault();
    setNotification(null);
    startScraping(async () => {
      let res;
      const radiusMeters = Math.round(scraperRadius * 1000);
      if (scraperMode === 'standard') {
        res = await runLeadFinderAction(scraperType, scraperAreas, radiusMeters, activeProfileId);
      } else {
        res = await runLeadFinderBuildingsAction(scraperType, scraperAreas, radiusMeters, activeProfileId);
      }
      
      if (res.success) {
        setNotification({
          type: 'success',
          message: res.message || `Scraper run successful! Loaded new leads.`
        });
        setShowScraper(false);
        // Refresh leads from server
        router.refresh();
      } else {
        setNotification({ type: 'error', message: res.error || 'Scraper run failed.' });
      }
    });
  };

  const handleDeleteLead = async (leadId: string) => {
    if (confirm('Are you sure you want to delete this lead?')) {
      const res = await deleteLeadAction(leadId);
      if (res.success) {
        setLeads(leads.filter(l => l.id !== leadId));
        if (selectedLeadId === leadId) setSelectedLeadId(null);
      } else {
        alert(res.error || 'Failed to delete lead');
      }
    }
  };

  // Detail panel action handlers
  const handleSaveDraft = () => {
    if (!latestMessage) return;
    setDetailFeedback(null);
    startSaving(async () => {
      const res = await saveFinalTextAction(latestMessage.id, pitchText);
      if (res.success) {
        setDetailFeedback({ type: 'success', message: 'Draft saved successfully!' });
        
        // Update local state to prevent page reload
        setLeads(prevLeads => prevLeads.map(l => {
          if (l.id === selectedLeadId) {
            const updatedMessages = l.messages.map(m => {
              if (m.id === latestMessage.id) {
                return { ...m, final_text: pitchText };
              }
              return m;
            });
            return { ...l, messages: updatedMessages };
          }
          return l;
        }));
      } else {
        setDetailFeedback({ type: 'error', message: res.error || 'Failed to save draft' });
      }
    });
  };

  const handleSendEmail = () => {
    if (!selectedLead || !latestMessage) return;
    if (!selectedLead.email) {
      alert('Cannot send email: this lead has no email address.');
      return;
    }
    if (!pitchText.trim()) {
      alert('Cannot send an empty email pitch.');
      return;
    }

    if (!confirm(`Are you sure you want to send this personalized pitch to ${selectedLead.email}?`)) {
      return;
    }

    setDetailFeedback(null);
    startSending(async () => {
      const res = await sendPitchAction(
        selectedLead.id,
        latestMessage.id,
        selectedLead.email || '',
        selectedLead.business_name,
        pitchText
      );
      if (res.success) {
        setDetailFeedback({ type: 'success', message: 'Email sent successfully!' });
        
        // Update local state
        setLeads(prevLeads => prevLeads.map(l => {
          if (l.id === selectedLeadId) {
            const updatedMessages = l.messages.map(m => {
              if (m.id === latestMessage.id) {
                return { ...m, final_text: pitchText, sent_at: new Date().toISOString() };
              }
              return m;
            });
            return { ...l, status: 'sent', last_contacted_at: new Date().toISOString(), messages: updatedMessages };
          }
          return l;
        }));
      } else {
        setDetailFeedback({ type: 'error', message: res.error || 'Failed to send email' });
      }
    });
  };

  const handleStatusChange = async (newStatus: LeadStatus) => {
    if (!selectedLead) return;
    setDetailFeedback(null);
    const res = await updateLeadStatusAction(selectedLead.id, newStatus);
    if (res.success) {
      setDetailFeedback({ type: 'success', message: `Lead status updated to ${newStatus.replace('_', ' ')}` });
      
      // Update local state
      setLeads(prevLeads => prevLeads.map(l => {
        if (l.id === selectedLeadId) {
          return { ...l, status: newStatus };
        }
        return l;
      }));
    } else {
      setDetailFeedback({ type: 'error', message: res.error || 'Failed to update status' });
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 flex-1 flex flex-col h-[calc(100vh-4rem)] overflow-hidden">
      {/* Global Notifications bar */}
      {notification && (
        <div className={`mb-4 p-4 rounded-xl flex items-start gap-3 border animate-fade-in shrink-0 ${
          notification.type === 'success' 
            ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' 
            : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
        }`}>
          <CheckCircle className="h-5 w-5 shrink-0 mt-0.5" />
          <div className="text-sm font-medium">{notification.message}</div>
        </div>
      )}

      {/* Main Split Grid */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-0">
        
        {/* LEFT COLUMN: Lead List Sidebar (4 cols on lg) */}
        <div className="lg:col-span-4 flex flex-col min-h-0 bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          
          {/* Sidebar Header controls */}
          <div className="p-4 border-b border-slate-800 bg-slate-950 space-y-3 shrink-0">
            {/* Profile Selector */}
            <div className="bg-slate-900 border border-slate-800 p-2.5 rounded-xl flex flex-col gap-1.5 shadow-md">
              <label className="text-[9px] font-bold text-indigo-400 uppercase tracking-widest flex items-center gap-1.5">
                <User className="h-3 w-3" />
                Active Profile / Workspace
              </label>
              <select
                value={activeProfileId}
                onChange={(e) => setActiveProfileId(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-1.5 text-xs font-semibold text-white focus:outline-none focus:border-indigo-500 cursor-pointer"
              >
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.sender_name})
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-white flex items-center gap-1.5">
                <Filter className="h-4 w-4 text-indigo-400" />
                Leads Finder & List
              </h2>
              <div className="flex gap-1.5">
                <a
                  href={`/import?profileId=${activeProfileId}`}
                  className="inline-flex items-center gap-1 bg-slate-900 hover:bg-slate-800 border border-slate-800 text-[10px] font-bold text-slate-300 hover:text-white px-2 py-1 rounded-lg transition-colors"
                >
                  <FileSpreadsheet className="h-3 w-3 text-indigo-400" />
                  Import CSV
                </a>
                <button
                  onClick={() => setShowScraper(!showScraper)}
                  className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-bold border transition-colors ${
                    showScraper 
                      ? 'bg-indigo-600 border-indigo-500 text-white' 
                      : 'bg-slate-900 border-slate-800 text-slate-300 hover:text-white'
                  }`}
                >
                  🔎 Finder
                </button>
              </div>
            </div>

            {/* Collapsible Scraper Form */}
            {showScraper && (
              <form onSubmit={handleRunScraper} className="bg-slate-900/60 border border-slate-800 rounded-xl p-3 space-y-3 animate-slide-down">
                <div className="text-[10px] font-bold text-indigo-400 uppercase tracking-wider">
                  OSM Map Scraper Parameters
                </div>
                
                {/* Scraper Mode Toggle */}
                <div className="space-y-1">
                  <label className="text-[9px] font-semibold text-slate-400 uppercase">Scraper Variant</label>
                  <div className="grid grid-cols-2 gap-1 bg-slate-950 p-0.5 rounded-lg border border-slate-800">
                    <button
                      type="button"
                      onClick={() => setScraperMode('standard')}
                      className={`py-1 text-[10px] font-semibold rounded transition-colors ${
                        scraperMode === 'standard'
                          ? 'bg-indigo-600 text-white'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      Standard (B2C)
                    </button>
                    <button
                      type="button"
                      onClick={() => setScraperMode('commercial')}
                      className={`py-1 text-[10px] font-semibold rounded transition-colors ${
                        scraperMode === 'commercial'
                          ? 'bg-indigo-600 text-white'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      Commercial (B2B)
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <label className="text-[9px] font-semibold text-slate-400 uppercase">Type / Category</label>
                    <select
                      value={scraperType}
                      onChange={(e) => setScraperType(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg p-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                    >
                      {scraperMode === 'standard' ? (
                        <>
                          <option value="salon">Salon</option>
                          <option value="gym">Gym</option>
                          <option value="restaurant">Restaurant</option>
                          <option value="real estate">Real Estate</option>
                          <option value="clinic">Clinic</option>
                          <option value="boutique">Boutique</option>
                        </>
                      ) : (
                        <>
                          <option value="office">Office (Company)</option>
                          <option value="warehouse">Warehouse</option>
                          <option value="factory">Factory / Workshop</option>
                          <option value="retail_store">Retail / Mall</option>
                          <option value="coworking_space">Coworking Space</option>
                          <option value="school">School / College</option>
                          <option value="hospital">Hospital</option>
                          <option value="hotel">Hotel</option>
                          <option value="it_park">IT Park</option>
                          <option value="logistics_company">Logistics Co</option>
                        </>
                      )}
                    </select>
                  </div>
                  <div className="space-y-1">
                    <label className="text-[9px] font-semibold text-slate-400 uppercase">Radius (km)</label>
                    <input
                      type="number"
                      step="0.1"
                      min="0.1"
                      max="10"
                      value={scraperRadius}
                      onChange={(e) => setScraperRadius(Number(e.target.value))}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg p-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                </div>
                 <div className="space-y-1">
                  <label className="text-[9px] font-semibold text-slate-400 uppercase">Areas (comma-separated)</label>
                  <input
                    type="text"
                    value={scraperAreas}
                    onChange={(e) => setScraperAreas(e.target.value)}
                    placeholder="e.g. Whitefield, Indiranagar"
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-1.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
                {/* Neighborhood Dropdown Helper */}
                <div className="space-y-1">
                  <label className="text-[9px] font-semibold text-slate-400 uppercase block">📍 Quick-Add Neighborhood</label>
                  <select
                    onChange={(e) => {
                      const selected = e.target.value;
                      if (!selected) return;
                      const trimmed = scraperAreas.trim();
                      if (!trimmed) {
                        setScraperAreas(selected);
                      } else {
                        const parts = trimmed.split(',').map(p => p.trim()).filter(Boolean);
                        if (!parts.includes(selected)) {
                          parts.push(selected);
                        }
                        setScraperAreas(parts.join(', '));
                      }
                      e.target.value = ""; // reset selection
                    }}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg p-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  >
                    <option value="">-- Choose neighborhood --</option>
                    {Object.entries(BENGALURU_LOCALITIES).map(([zone, localities]) => (
                      <optgroup key={zone} label={zone} className="bg-slate-950 text-indigo-400 font-bold text-xs">
                        {localities.map((loc) => (
                          <option key={loc} value={loc} className="bg-slate-950 text-slate-300 font-semibold text-xs">
                            {loc}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </div>
                <button
                  type="submit"
                  disabled={isScraping}
                  className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                >
                  {isScraping ? (
                    <>
                      <Loader2 className="h-3 w-3 animate-spin" />
                      Searching Map...
                    </>
                  ) : (
                    <>
                      <Play className="h-3 w-3 fill-current" />
                      Find & Import Leads
                    </>
                  )}
                </button>
              </form>
            )}

            {/* Quick Actions (Generate, Followup, & Send All) */}
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={handleGeneratePitches}
                  disabled={isGenerating || isFollowingUp || isScraping || isSendingAll}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-2.5 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50 transition-colors"
                >
                  {isGenerating ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Sparkles className="h-3 w-3" />
                  )}
                  Gen Pitches
                </button>
                <button
                  onClick={handleRunFollowUps}
                  disabled={isFollowingUp || isGenerating || isScraping || isSendingAll}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-2 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50 transition-colors"
                >
                  {isFollowingUp ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Clock className="h-3 w-3 text-indigo-400" />
                  )}
                  Follow-ups
                </button>
              </div>

              {leads.filter(l => l.profile_id === activeProfileId && l.status === 'draft' && l.contact_method === 'email' && l.email && l.messages?.some(m => m.message_type === 'initial' && !m.sent_at)).length > 0 && (
                <button
                  onClick={handleSendAllDrafts}
                  disabled={isSendingAll || isGenerating || isFollowingUp || isScraping}
                  className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-2.5 py-2 text-xs font-bold text-white shadow-md hover:bg-emerald-500 disabled:opacity-50 transition-all border border-emerald-500/20 hover:scale-[1.01]"
                >
                  {isSendingAll ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Sending outreach emails...
                    </>
                  ) : (
                    <>
                      <Send className="h-3.5 w-3.5" />
                      Send All Reviewed Pitches ({leads.filter(l => l.profile_id === activeProfileId && l.status === 'draft' && l.contact_method === 'email' && l.email && l.messages?.some(m => m.message_type === 'initial' && !m.sent_at)).length})
                    </>
                  )}
                </button>
              )}
            </div>

            {/* Search and Filters */}
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-500" />
              <input
                type="text"
                placeholder="Search leads, type, email..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 bg-slate-900 border border-slate-800 rounded-lg text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
              />
            </div>

            {/* Contact Method Toggles */}
            <div className="grid grid-cols-3 gap-1 p-0.5 bg-slate-900 border border-slate-800 rounded-lg shrink-0">
              <button
                onClick={() => setContactFilter('all')}
                className={`py-1 text-[10px] font-bold rounded-md transition-all ${
                  contactFilter === 'all'
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                All Leads
              </button>
              <button
                onClick={() => setContactFilter('email')}
                className={`py-1 text-[10px] font-bold rounded-md transition-all flex items-center justify-center gap-1 ${
                  contactFilter === 'email'
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Mail className="h-3 w-3 shrink-0" />
                Only Email
              </button>
              <button
                onClick={() => setContactFilter('phone')}
                className={`py-1 text-[10px] font-bold rounded-md transition-all flex items-center justify-center gap-1 ${
                  contactFilter === 'phone'
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Phone className="h-3 w-3 shrink-0" />
                Only Phone
              </button>
            </div>

            {/* Scrollable horizontal status bar */}
            <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
              {STATUS_OPTIONS.map((opt) => {
                const count = opt.value === 'all' 
                  ? leads.filter(l => l.profile_id === activeProfileId && (l.contact_method === 'phone' || (l.email && l.email.trim() !== '')) && (contactFilter === 'all' || l.contact_method === contactFilter)).length 
                  : leads.filter(l => l.profile_id === activeProfileId && l.status === opt.value && (l.contact_method === 'phone' || (l.email && l.email.trim() !== '')) && (contactFilter === 'all' || l.contact_method === contactFilter)).length;
                return (
                  <button
                    key={opt.value}
                    onClick={() => setSelectedStatus(opt.value)}
                    className={`shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-semibold transition-all border ${
                      selectedStatus === opt.value
                        ? 'bg-indigo-600 border-indigo-500 text-white shadow-md'
                        : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-white'
                    }`}
                  >
                    {opt.label}
                    <span className={`px-1 rounded-full text-[9px] ${
                      selectedStatus === opt.value ? 'bg-indigo-500 text-white' : 'bg-slate-950 text-slate-500'
                    }`}>
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Sidebar Leads List Container */}
          <div className="flex-1 overflow-y-auto divide-y divide-slate-800 bg-slate-950/40">
            {filteredLeads.length === 0 ? (
              <div className="p-8 text-center text-slate-500 text-xs">
                No matching leads found.
              </div>
            ) : selectedStatus === 'sent' ? (
              // Grouped Sent Leads list (batch-wise by sent date)
              getSentGroups().map((group) => (
                <div key={group.date} className="flex flex-col">
                  {/* Group Date Header */}
                  <div className="bg-slate-900/80 backdrop-blur border-y border-slate-800/80 px-3 py-1.5 text-[9px] font-bold text-indigo-400 uppercase tracking-widest sticky top-0 z-10 flex items-center justify-between">
                    <span>{group.date}</span>
                    <span className="bg-slate-950 text-slate-400 px-1.5 py-0.5 rounded text-[8px] border border-slate-800">
                      {group.leadsList.length} {group.leadsList.length === 1 ? 'lead' : 'leads'}
                    </span>
                  </div>
                  
                  <div className="divide-y divide-slate-800/60">
                    {group.leadsList.map((lead) => {
                      const hasPitch = lead.messages && lead.messages.length > 0;
                      const leadStatusOption = STATUS_OPTIONS.find(s => s.value === lead.status);
                      const isSelected = selectedLeadId === lead.id;
                      const sentTime = lead.last_contacted_at 
                        ? new Date(lead.last_contacted_at).toLocaleTimeString(undefined, {
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : '';
                      
                      return (
                        <div
                          key={lead.id}
                          onClick={() => setSelectedLeadId(lead.id)}
                          className={`p-3 text-left cursor-pointer transition-all flex items-start justify-between gap-3 ${
                            isSelected 
                              ? 'bg-slate-900 border-l-4 border-indigo-500 pl-2' 
                              : 'hover:bg-slate-900/40 pl-3'
                          }`}
                        >
                          <div className="min-w-0 flex-1">
                            <div className="font-semibold text-xs text-white truncate">{lead.business_name}</div>
                            <div className="text-[10px] text-slate-500 mt-0.5 flex items-center gap-1.5">
                              <span className="capitalize">{lead.business_type}</span>
                              <span>&bull;</span>
                              <span className="truncate">{lead.email}</span>
                            </div>
                            
                            <div className="mt-2 flex items-center justify-between gap-2">
                              <div className="flex items-center gap-1.5">
                                <span className={`inline-flex items-center rounded-full px-2 py-0.2 text-[9px] font-bold ${leadStatusOption?.badge || 'bg-slate-800 text-slate-400'}`}>
                                  {lead.status.replace('_', ' ')}
                                </span>
                                {hasPitch && (
                                  <span className="inline-flex items-center gap-0.5 text-[9px] text-indigo-400 font-semibold">
                                    <Sparkles className="h-2.5 w-2.5" /> Pitch
                                  </span>
                                )}
                              </div>
                              {sentTime && (
                                <span className="text-[9px] text-slate-500 font-medium font-mono shrink-0">
                                  Sent at {sentTime}
                                </span>
                              )}
                            </div>
                          </div>

                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteLead(lead.id);
                            }}
                            className="text-slate-600 hover:text-rose-400 transition-colors p-1 hover:bg-rose-500/10 rounded"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))
            ) : (
              // Flat list for other lead categories
              filteredLeads.map((lead) => {
                const hasPitch = lead.messages && lead.messages.length > 0;
                const leadStatusOption = STATUS_OPTIONS.find(s => s.value === lead.status);
                const isSelected = selectedLeadId === lead.id;
                
                return (
                  <div
                    key={lead.id}
                    onClick={() => setSelectedLeadId(lead.id)}
                    className={`p-3 text-left cursor-pointer transition-all flex items-start justify-between gap-3 ${
                      isSelected 
                        ? 'bg-slate-900 border-l-4 border-indigo-500 pl-2' 
                        : 'hover:bg-slate-900/40 pl-3'
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold text-xs text-white truncate">{lead.business_name}</div>
                      <div className="text-[10px] text-slate-500 mt-0.5 flex items-center gap-1.5">
                        <span className="capitalize">{lead.business_type}</span>
                        <span>&bull;</span>
                        <span className="truncate">{lead.contact_method === 'phone' ? `📞 ${lead.phone || 'Phone Only'}` : `✉️ ${lead.email}`}</span>
                      </div>
                      
                      <div className="mt-2 flex items-center gap-2">
                        <span className={`inline-flex items-center rounded-full px-2 py-0.2 text-[9px] font-bold ${leadStatusOption?.badge || 'bg-slate-800 text-slate-400'}`}>
                          {lead.status.replace('_', ' ')}
                        </span>
                        {hasPitch && (
                          <span className="inline-flex items-center gap-0.5 text-[9px] text-indigo-400 font-semibold">
                            <Sparkles className="h-2.5 w-2.5" /> Pitch
                          </span>
                        )}
                      </div>
                    </div>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteLead(lead.id);
                      }}
                      className="text-slate-600 hover:text-rose-400 transition-colors p-1 hover:bg-rose-500/10 rounded"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* RIGHT COLUMN: Detail pane (8 cols on lg) */}
        <div className="lg:col-span-8 flex flex-col min-h-0 bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
          {selectedLead ? (
            <div className="flex-1 flex flex-col min-h-0 divide-y divide-slate-800">
              
              {/* Lead Details Header */}
              <div className="p-4 bg-slate-950 space-y-4 shrink-0">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                  <div>
                    <div className="text-[10px] text-indigo-400 font-bold uppercase tracking-wider">
                      {selectedLead.business_type}
                    </div>
                    <h3 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
                      {selectedLead.business_name}
                      {selectedLead.contact_method === 'phone' ? (
                        <span className="text-[9px] bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded-full font-semibold">📞 Phone Lead</span>
                      ) : (
                        <span className="text-[9px] bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 px-2 py-0.5 rounded-full font-semibold">✉️ Email Lead</span>
                      )}
                    </h3>
                  </div>

                  <div className="flex items-center gap-2">
                    {selectedLead.contact_method === 'email' && selectedLead.status === 'sent' && (
                      <button
                        onClick={handleMarkBounced}
                        className="text-[10px] font-bold text-rose-400 bg-rose-500/10 border border-rose-500/20 hover:bg-rose-500/25 px-2.5 py-1 rounded-lg transition-all"
                      >
                        🚫 Mark Bounced
                      </button>
                    )}
                    <span className="text-[10px] font-semibold text-slate-400">Status:</span>
                    <select
                      value={selectedLead.status}
                      onChange={(e) => handleStatusChange(e.target.value as LeadStatus)}
                      className="bg-slate-900 border border-slate-800 rounded-lg py-1 px-2.5 text-xs text-slate-100 focus:outline-none focus:border-indigo-500"
                    >
                      <option value="draft">Draft</option>
                      <option value="sent">Sent</option>
                      <option value="replied">Replied</option>
                      <option value="no_response">No Response</option>
                      <option value="won">Won</option>
                      <option value="lost">Lost</option>
                    </select>
                  </div>
                </div>

                {/* Info row */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs bg-slate-900/40 p-3 rounded-xl border border-slate-800/60">
                  <div className="flex items-center gap-2">
                    <User className="h-3.5 w-3.5 text-slate-500" />
                    <span className="text-slate-300 truncate">{selectedLead.contact_name || '—'}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Mail className="h-3.5 w-3.5 text-slate-500" />
                    <span className="text-slate-300 truncate" title={selectedLead.email || 'No Email'}>{selectedLead.email || '—'}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Phone className="h-3.5 w-3.5 text-slate-500" />
                    <span className="text-slate-300 truncate">{selectedLead.phone || '—'}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Calendar className="h-3.5 w-3.5 text-slate-500" />
                    <span suppressHydrationWarning className="text-slate-300 truncate">
                      {selectedLead.last_contacted_at 
                        ? new Date(selectedLead.last_contacted_at).toLocaleDateString()
                        : 'Never'}
                    </span>
                  </div>
                </div>

                {/* Context Notes */}
                {selectedLead.context_notes && (
                  <div className="text-xs text-slate-400 bg-slate-900/60 p-2.5 rounded-lg border border-slate-800 whitespace-pre-wrap leading-relaxed max-h-20 overflow-y-auto">
                    <strong>Context Notes:</strong> {selectedLead.context_notes}
                  </div>
                )}
              </div>

              {/* Pitch Editor Workspace or Call Workspace */}
              <div className="flex-1 flex flex-col p-4 bg-slate-950/20 min-h-0">
                {selectedLead.contact_method === 'phone' ? (
                  <div className="flex-1 flex flex-col items-center justify-center text-center p-6 bg-slate-900/10 border border-dashed border-slate-800 rounded-xl space-y-4">
                    <div className="h-12 w-12 rounded-full bg-amber-500/10 flex items-center justify-center text-amber-500 text-xl border border-amber-500/20 shadow-md">
                      📞
                    </div>
                    <div>
                      <h4 className="text-sm font-semibold text-white">Phone Outreach Lead</h4>
                      <p className="text-xs text-slate-500 max-w-sm mt-1 leading-normal">
                        This business does not have a verified email. Reach out directly to them at:
                      </p>
                      <div className="mt-3 text-lg font-bold text-amber-400 bg-slate-900/80 border border-slate-800 px-4 py-2 rounded-xl inline-block select-all">
                        {selectedLead.phone || 'No phone number listed'}
                      </div>
                    </div>
                    <div className="flex gap-2.5">
                      <button
                        onClick={() => handleStatusChange('won')}
                        className="rounded-lg bg-emerald-600 hover:bg-emerald-500 px-3.5 py-1.5 text-xs font-semibold text-white transition-colors"
                      >
                        Mark Won
                      </button>
                      <button
                        onClick={() => handleStatusChange('lost')}
                        className="rounded-lg bg-rose-600 hover:bg-rose-500 px-3.5 py-1.5 text-xs font-semibold text-white transition-colors"
                      >
                        Mark Lost
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center justify-between mb-2 shrink-0 border-b border-slate-800 pb-2">
                      <div className="flex items-center gap-4">
                        <h4 className="text-sm font-semibold text-white flex items-center gap-1.5">
                          <Sparkles className="h-4 w-4 text-indigo-400" />
                          {latestMessage?.message_type === 'follow_up' ? 'Follow-Up Draft' : 'Outbound Pitch Draft'}
                        </h4>
                        
                        {latestMessage && (
                          <div className="flex bg-slate-900 p-0.5 rounded-lg border border-slate-800 text-[10px]">
                            <button
                              type="button"
                              onClick={() => setEditorTab('edit')}
                              className={`px-2 py-0.5 rounded font-semibold transition-colors ${
                                editorTab === 'edit' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
                              }`}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditorTab('preview')}
                              className={`px-2 py-0.5 rounded font-semibold transition-colors ${
                                editorTab === 'preview' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-slate-200'
                              }`}
                            >
                              Preview Full Email
                            </button>
                          </div>
                        )}
                      </div>
                      
                      <div className="flex items-center gap-2">
                        {latestMessage && (
                          <button
                            onClick={handleRePitchLead}
                            disabled={isGeneratingPitch || isSaving || isSending}
                            className="inline-flex items-center gap-1 text-[10px] bg-indigo-600/10 hover:bg-indigo-600/20 border border-indigo-500/20 hover:border-indigo-500/30 text-indigo-400 py-0.5 px-2.5 rounded-full font-bold transition-all hover:scale-105 disabled:opacity-50"
                          >
                            {isGeneratingPitch ? (
                              <>
                                <Loader2 className="h-2.5 w-2.5 animate-spin" />
                                Regenerating...
                              </>
                            ) : (
                              <>
                                <RefreshCw className="h-2.5 w-2.5" />
                                Re-Pitch Lead
                              </>
                            )}
                          </button>
                        )}
                        {latestMessage && (
                          <span className="text-[10px] bg-slate-900 border border-slate-800 text-slate-500 py-0.5 px-2 rounded-full font-bold">
                            Model: Llama 3.3 (Groq)
                          </span>
                        )}
                      </div>
                    </div>

                    {detailFeedback && (
                      <div className={`mb-3 p-3 rounded-lg flex items-start gap-2 border animate-fade-in shrink-0 text-xs ${
                        detailFeedback.type === 'success' 
                          ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' 
                          : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
                      }`}>
                        <CheckCircle className="h-4 w-4 shrink-0 mt-0.5" />
                        <div className="font-semibold">{detailFeedback.message}</div>
                      </div>
                    )}

                    {latestMessage ? (
                      <div className="flex-1 flex flex-col space-y-3 min-h-0">
                        {editorTab === 'edit' ? (
                          <textarea
                            value={pitchText}
                            onChange={(e) => setPitchText(e.target.value)}
                            disabled={isSaving || isSending}
                            className="flex-1 w-full bg-slate-900 border border-slate-800 rounded-xl p-3 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 leading-relaxed font-mono disabled:opacity-50 min-h-0 resize-none"
                            placeholder="Pitch text body..."
                          />
                        ) : (
                          <iframe
                            srcDoc={getPreviewHtml()}
                            className="flex-1 w-full bg-white rounded-xl border border-slate-800 overflow-hidden shadow-inner"
                            style={{ minHeight: '200px' }}
                            title="Email Preview"
                          />
                        )}
                        
                        <div className="flex justify-between items-center gap-4 shrink-0">
                          <span className="text-[10px] text-slate-500">
                            Chars: <strong className="text-slate-400">{pitchText.length}</strong> &bull; Words: <strong className="text-slate-400">{pitchText.split(/\s+/).filter(Boolean).length}</strong>
                          </span>
                          <div className="flex gap-2">
                            <button
                              onClick={handleSaveDraft}
                              disabled={isSaving || isSending}
                              className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-slate-700 disabled:opacity-50 transition-colors"
                            >
                              {isSaving ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Save className="h-3.5 w-3.5" />
                              )}
                              Save Draft
                            </button>
                            <button
                              onClick={handleSendEmail}
                              disabled={isSending || isSaving}
                              className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50 hover:shadow-lg hover:shadow-indigo-500/20 transition-all"
                            >
                              {isSending ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Send className="h-3.5 w-3.5" />
                              )}
                              Send Email
                            </button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="flex-1 flex flex-col items-center justify-center text-center p-6 bg-slate-900/10 border border-dashed border-slate-800 rounded-xl space-y-3">
                        <div className="flex flex-col items-center">
                          <AlertTriangle className="h-8 w-8 text-yellow-500 mb-2" />
                          <h4 className="text-xs font-semibold text-white">No pitch draft generated yet</h4>
                          <p className="text-[11px] text-slate-500 max-w-xs mt-1 leading-normal">
                            Generate a personalized draft for this lead or use the sidebar button for all drafts.
                          </p>
                        </div>
                        <button
                          onClick={handleRePitchLead}
                          disabled={isGeneratingPitch}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 transition-colors disabled:opacity-50"
                        >
                          {isGeneratingPitch ? (
                            <>
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              Generating...
                            </>
                          ) : (
                            <>
                              <Sparkles className="h-3.5 w-3.5" />
                              Generate Pitch
                            </>
                          )}
                        </button>
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Communication History timeline (compact view) */}
              <div className="p-4 bg-slate-950 shrink-0 border-t border-slate-800 max-h-48 overflow-y-auto">
                <h4 className="text-xs font-bold text-white mb-3 flex items-center gap-1.5">
                  <History className="h-3.5 w-3.5 text-indigo-400" />
                  Communication History
                </h4>

                {selectedLead.messages.length === 0 ? (
                  <div className="text-[11px] text-slate-500">No outreach history found.</div>
                ) : (
                  <div className="relative border-l border-slate-800 pl-4 ml-1.5 space-y-3">
                    {[...selectedLead.messages]
                      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
                      .map((msg) => (
                        <div key={msg.id} className="relative text-[11px]">
                          <span className={`absolute -left-[21px] top-1.5 flex h-2.5 w-2.5 items-center justify-center rounded-full ring-2 ring-slate-950 ${
                            msg.sent_at ? 'bg-emerald-500' : 'bg-yellow-500'
                          }`} />
                          
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-slate-300">
                              {msg.message_type === 'follow_up' ? 'Follow-Up Email' : 'Initial Outreach'}
                            </span>
                            <span className={`text-[8px] uppercase font-bold px-1.5 py-0.2 rounded-full ${
                              msg.sent_at ? 'bg-emerald-500/10 text-emerald-400' : 'bg-yellow-500/10 text-yellow-400'
                            }`}>
                              {msg.sent_at ? 'Sent' : 'Draft'}
                            </span>
                            <span suppressHydrationWarning className="text-[10px] text-slate-500 font-mono ml-auto">
                              {new Date(msg.created_at).toLocaleDateString()}
                            </span>
                          </div>
                          
                          <div className="text-[10px] text-slate-400 bg-slate-900/60 p-2 rounded border border-slate-800/80 font-mono max-h-20 overflow-y-auto mt-1 truncate">
                            {msg.final_text || msg.generated_text}
                          </div>
                        </div>
                      ))}
                  </div>
                )}
              </div>

            </div>
          ) : (
            /* Selected Lead Placeholder (Empty State) */
            <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
              <div className="h-16 w-16 rounded-2xl bg-slate-900 border border-slate-800 flex items-center justify-center text-2xl text-slate-400 shadow-inner shadow-black mb-4 animate-pulse">
                ⚡
              </div>
              <h3 className="text-lg font-bold text-white">No Lead Selected</h3>
              <p className="mt-1.5 text-sm text-slate-400 max-w-sm leading-normal">
                Select a business lead from the sidebar on the left to review their profile, edit their personalized pitch, and send outreach emails.
              </p>
              <div className="mt-4 flex gap-2">
                <button
                  onClick={() => setShowScraper(true)}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-500 transition-colors"
                >
                  <Search className="h-3.5 w-3.5" />
                  Open Lead Finder
                </button>
              </div>
            </div>
          )}
        </div>

      </div>

      {/* Progress Overlay Modal for Bulk Email Sending */}
      {sendProgress && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-xl bg-indigo-600/20 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Sending Outreach Emails</h3>
                <p className="text-[10px] text-slate-400">Please keep this window open while emails are being sent.</p>
              </div>
            </div>

            {/* Progress Bar */}
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs font-semibold text-slate-300">
                <span>Sending...</span>
                <span>{sendProgress.current} / {sendProgress.total}</span>
              </div>
              <div className="w-full bg-slate-950 rounded-full h-2 border border-slate-800 overflow-hidden">
                <div 
                  className="bg-indigo-600 h-full rounded-full transition-all duration-300 ease-out"
                  style={{ width: `${(sendProgress.current / sendProgress.total) * 100}%` }}
                />
              </div>
            </div>

            {/* Current Lead Details */}
            <div className="bg-slate-950 p-3.5 rounded-xl border border-slate-800 space-y-1">
              <div className="text-[9px] font-bold text-indigo-400 uppercase tracking-wider">Current Recipient</div>
              <div className="text-xs font-semibold text-white truncate">{sendProgress.businessName}</div>
            </div>

            {/* Statistics */}
            <div className="grid grid-cols-2 gap-2 text-[10px] font-semibold text-slate-400">
              <div className="bg-slate-900/60 p-2 rounded-lg border border-slate-800/60">
                Success: <span className="text-emerald-400">{sendProgress.current - 1 - sendProgress.failedCount}</span>
              </div>
              <div className="bg-slate-900/60 p-2 rounded-lg border border-slate-800/60">
                Errors: <span className="text-rose-400">{sendProgress.failedCount}</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
