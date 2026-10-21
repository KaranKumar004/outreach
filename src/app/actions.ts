'use server';

import { revalidatePath } from 'next/cache';
import { parse } from 'csv-parse/sync';
import { supabase } from '@/lib/supabase';
import { groq, GROQ_MODEL } from '@/lib/groq';
import { sendEmail } from '@/lib/email';
import { LeadStatus } from '@/types';
import { exec } from 'child_process';
import util from 'util';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const execPromise = util.promisify(exec);
const SENT_LOG_PATH = path.join(process.cwd(), 'sent_log.json');

// Helper to load tracking log
export async function loadSentLogAction() {
  return loadSentLog();
}

function loadSentLog(): Record<string, any> {
  if (!fs.existsSync(SENT_LOG_PATH)) {
    return {};
  }
  try {
    const raw = fs.readFileSync(SENT_LOG_PATH, 'utf-8');
    return JSON.parse(raw);
  } catch (error) {
    console.error('Failed to load sent_log.json:', error);
    return {};
  }
}

function saveLogAtomic(logData: Record<string, any>) {
  const tempPath = SENT_LOG_PATH + '.tmp';
  try {
    fs.writeFileSync(tempPath, JSON.stringify(logData, null, 2), 'utf-8');
    fs.renameSync(tempPath, SENT_LOG_PATH);
  } catch (error) {
    if (fs.existsSync(tempPath)) {
      try { fs.unlinkSync(tempPath); } catch (e) {}
    }
    console.error('Failed to save sent_log.json atomically:', error);
    throw error;
  }
}

function getLeadIdentifier(
  email: string | null | undefined,
  phone: string | null | undefined,
  businessName: string
): string {
  if (email && email.trim() !== '') {
    return email.trim().toLowerCase();
  }
  if (phone) {
    const cleanedPhone = phone.replace(/[^0-9+]/g, '');
    if (cleanedPhone) {
      return cleanedPhone;
    }
  }
  const nameSlug = businessName.toLowerCase().replace(/[^a-z0-9]/g, '');
  const finalSlug = nameSlug || 'unknown';
  const hash = crypto.createHash('sha256').update(finalSlug).digest('hex');
  return `hash-${hash.substring(0, 16)}`;
}

// 1. CSV Import Action
export async function importLeadsAction(formData: FormData) {
  try {
    const file = formData.get('file') as File;
    if (!file) {
      return { success: false, error: 'No file uploaded' };
    }

    const fileContent = await file.text();
    
    // Parse CSV
    const records = parse(fileContent, {
      columns: true,
      skip_empty_lines: true,
      trim: true,
      relax_column_count: true,
    });

    if (records.length === 0) {
      return { success: false, error: 'CSV file is empty' };
    }

    // Validate headers (business_name and business_type are required; email is now optional)
    const requiredHeaders = ['business_name', 'business_type'];
    const headers = Object.keys(records[0] as Record<string, any>);
    const missingHeaders = requiredHeaders.filter(h => !headers.includes(h));

    if (missingHeaders.length > 0) {
      return {
        success: false,
        error: `Missing required columns in CSV: ${missingHeaders.join(', ')}`,
      };
    }

    const profileId = formData.get('profileId') as string | null;

    // Filter records: Keep leads that have either an email OR a phone number
    const validRecords = records.filter((record: any) => {
      const hasEmail = record.email && record.email.trim() !== '' && !record.email.toLowerCase().includes('no-email');
      const hasPhone = record.phone && record.phone.trim() !== '';
      return hasEmail || hasPhone;
    });

    if (validRecords.length === 0) {
      return { 
        success: true, 
        count: 0, 
        message: 'All uploaded leads were skipped because they did not have a valid email or phone number.' 
      };
    }

    // Prepare records for insertion
    const leadsToInsert = validRecords.map((record: any) => {
      const hasEmail = record.email && record.email.trim() !== '' && !record.email.toLowerCase().includes('no-email');
      const contactMethod = hasEmail ? 'email' : 'phone';
      const cleanEmail = hasEmail ? record.email.trim() : null;

      return {
        profile_id: profileId || null,
        business_name: record.business_name,
        email: cleanEmail,
        business_type: record.business_type,
        contact_name: record.contact_name || null,
        phone: record.phone || null,
        context_notes: record.context_notes || null,
        status: 'draft',
        contact_method: contactMethod,
      };
    });

    // Bulk insert into Supabase
    const { error } = await supabase.from('leads').insert(leadsToInsert);

    if (error) {
      console.error('Database error during insert:', error);
      return { success: false, error: `Database error: ${error.message}` };
    }

    revalidatePath('/');
    return { success: true, count: leadsToInsert.length };
  } catch (error: any) {
    console.error('Import action failed:', error);
    return { success: false, error: error.message || 'An unexpected error occurred' };
  }
}

// 2. AI Pitch Generation Action
export async function generatePitchesAction(profileId: string) {
  try {
    if (!profileId) {
      return { success: false, error: 'No profile ID provided' };
    }

    // Fetch profile details
    const { data: profile, error: profileError } = await supabase
      .from('profiles')
      .select('*')
      .eq('id', profileId)
      .single();

    if (profileError) {
      return { success: false, error: `Error fetching profile: ${profileError.message}` };
    }

    // Query leads with 'draft' status belonging to this profile that don't have any messages associated
    const { data: leads, error: leadsError } = await supabase
      .from('leads')
      .select('*, messages(id)')
      .eq('status', 'draft')
      .eq('profile_id', profileId);

    if (leadsError) {
      return { success: false, error: `Error fetching leads: ${leadsError.message}` };
    }

    if (!leads || leads.length === 0) {
      return { success: true, count: 0, message: 'No leads found in draft status for this profile.' };
    }

    // Filter leads that don't have any messages generated yet
    const leadsNeedPitch = leads.filter(
      (lead: any) => !lead.messages || lead.messages.length === 0
    );

    if (leadsNeedPitch.length === 0) {
      return { success: true, count: 0, message: 'All draft leads already have generated pitches.' };
    }

    // Limit to maximum 20 pitches per run to prevent server timeout and Groq rate limiting
    const MAX_BATCH_SIZE = 20;
    const batchToProcess = leadsNeedPitch.slice(0, MAX_BATCH_SIZE);

    let generatedCount = 0;
    const isSKM = profile.name === 'SKM Dev Team';

    // Process sequentially to remain within rate limits
    for (const lead of batchToProcess) {
      const notes = lead.context_notes ? lead.context_notes : 'None';
      
      let systemPrompt = '';
      if (isSKM) {
        systemPrompt = `You are writing a personalized cold outreach sentence from SKM Enterprises (civil contracting company in Bengaluru) to a commercial business.
Business name: ${lead.business_name}.
Business category: ${lead.business_type}.
Context notes: ${notes}.

Write exactly one sentence following this pattern: "SKM Enterprises offers [category-specific] services like [1-2 relevant services, e.g., flooring/painting for salon, fit-outs for office, concrete flooring/scaffolding for warehouse] to enhance [Business Name]'s ambiance/facility, supporting their [summarized context notes] with a well-maintained facility."
Do not include any greeting or sign-off. Start directly with the sentence. Keep it under 40 words.`;
      } else {
        systemPrompt = `You are writing a short, friendly cold outreach email from Karan, a freelance developer/data professional in Bengaluru, to a local business. Business name: ${lead.business_name}. Business type: ${lead.business_type}. Context notes: ${notes}. Write a 3-4 sentence email pitching a relevant service (e.g. a simple website, automation tool, or data dashboard) without sounding like a template. No generic flattery. End with a soft call-to-action (15-min call). Keep it under 80 words.`;
      }

      const response = await groq.chat.completions.create({
        model: GROQ_MODEL,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: 'Generate the outreach pitch.' }
        ],
        temperature: 0.7,
        max_tokens: 150,
      });

      const generatedText = response.choices[0]?.message?.content?.trim() || '';

      if (generatedText) {
        // Insert into messages table
        const { error: msgError } = await supabase
          .from('messages')
          .insert({
            lead_id: lead.id,
            generated_text: generatedText,
            message_type: 'initial',
          });

        if (msgError) {
          console.error(`Error saving message for lead ${lead.id}:`, msgError);
          continue;
        }

        generatedCount++;
      }
    }

    revalidatePath('/');
    return { success: true, count: generatedCount };
  } catch (error: any) {
    console.error('Pitch generation failed:', error);
    return { success: false, error: error.message || 'An unexpected error occurred' };
  }
}

// 2.5. Generate Pitch for a Single Lead (Re-Pitch / Individual Generation)
export async function generateSinglePitchAction(leadId: string, profileId: string) {
  try {
    if (!leadId || !profileId) {
      return { success: false, error: 'Missing lead ID or profile ID' };
    }

    // Fetch profile details
    const { data: profile, error: profileError } = await supabase
      .from('profiles')
      .select('*')
      .eq('id', profileId)
      .single();

    if (profileError) {
      return { success: false, error: `Error fetching profile: ${profileError.message}` };
    }

    // Fetch lead details
    const { data: lead, error: leadError } = await supabase
      .from('leads')
      .select('*')
      .eq('id', leadId)
      .single();

    if (leadError) {
      return { success: false, error: `Error fetching lead: ${leadError.message}` };
    }

    const notes = lead.context_notes ? lead.context_notes : 'None';
    const isSKM = profile.name === 'SKM Dev Team';
    
    let systemPrompt = '';
    if (isSKM) {
      systemPrompt = `You are writing a personalized cold outreach sentence from SKM Enterprises (civil contracting company in Bengaluru) to a commercial business.
Business name: ${lead.business_name}.
Business category: ${lead.business_type}.
Context notes: ${notes}.

Write exactly one sentence following this pattern: "SKM Enterprises offers [category-specific] services like [1-2 relevant services, e.g., flooring/painting for salon, fit-outs for office, concrete flooring/scaffolding for warehouse] to enhance [Business Name]'s ambiance/facility, supporting their [summarized context notes] with a well-maintained facility."
Do not include any greeting or sign-off. Start directly with the sentence. Keep it under 40 words.`;
    } else {
      systemPrompt = `You are writing a friendly cold outreach email from Karan, a freelance developer/data professional in Bengaluru, to a local business. Business name: ${lead.business_name}. Business type: ${lead.business_type}. Context notes: ${notes}. Write a 3-4 sentence email pitching a relevant service (e.g. a simple website, automation tool, or data dashboard) without sounding like a template. No generic flattery. End with a soft call-to-action (15-min call). Keep it under 80 words.`;
    }

    const response = await groq.chat.completions.create({
      model: GROQ_MODEL,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: 'Generate the outreach pitch.' }
      ],
      temperature: 0.7,
      max_tokens: 150,
    });

    const generatedText = response.choices[0]?.message?.content?.trim() || '';

    if (!generatedText) {
      return { success: false, error: 'Groq failed to generate pitch text.' };
    }

    // 1. Delete any existing UN-SENT message of type 'initial' for this lead
    await supabase
      .from('messages')
      .delete()
      .eq('lead_id', leadId)
      .eq('message_type', 'initial')
      .is('sent_at', null);

    // 2. Insert the new message
    const { error: msgError } = await supabase
      .from('messages')
      .insert({
        lead_id: leadId,
        generated_text: generatedText,
        message_type: 'initial',
      });

    if (msgError) {
      return { success: false, error: `Error saving pitch message: ${msgError.message}` };
    }

    // 3. Reset lead status back to 'draft' so the user can edit/send it
    const { error: leadUpdateError } = await supabase
      .from('leads')
      .update({ status: 'draft' })
      .eq('id', leadId);

    if (leadUpdateError) {
      console.warn('Failed to reset lead status to draft:', leadUpdateError.message);
    }

    revalidatePath('/');
    return { success: true, message: 'New pitch generated successfully!' };
  } catch (error: any) {
    console.error('generateSinglePitchAction failed:', error);
    return { success: false, error: error.message || 'An unexpected error occurred' };
  }
}

// 3. Save Edited Final Text Action
export async function saveFinalTextAction(messageId: string, finalText: string) {
  try {
    const { error } = await supabase
      .from('messages')
      .update({ final_text: finalText })
      .eq('id', messageId);

    if (error) {
      return { success: false, error: error.message };
    }

    return { success: true };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

// 4. Send Pitch Action
export async function sendPitchAction(
  leadId: string,
  messageId: string,
  email: string,
  businessName: string,
  text: string
) {
  try {
    // Fetch lead with its associated profile
    const { data: lead, error: leadFetchError } = await supabase
      .from('leads')
      .select('*, profiles(*)')
      .eq('id', leadId)
      .single();

    if (leadFetchError || !lead) {
      throw new Error(`Failed to fetch lead profile: ${leadFetchError?.message || 'Lead not found'}`);
    }

    if (!email || email.trim() === '') {
      throw new Error("Cannot send email: lead has no email address.");
    }

    const profile = (lead as any).profiles;
    const isSKM = profile && profile.name === 'SKM Dev Team';
    const cleanEmail = email.trim().replace(/\.$/, '');

    const subject = isSKM 
      ? `SKM Enterprises — Civil Contracting & Maintenance for ${businessName}`
      : `Proposal for ${businessName} — Web & Automation services`;

    if (isSKM && profile.email_template) {
      let html = profile.email_template;
      
      // Target paragraph placeholders to replace with edited pitch text
      const defaultParagraph = "Buildings always need work eventually &mdash; a renovation, an interior upgrade, structural repairs, or scaffolding for maintenance. When that time comes for {{company_name}}, I''d like SKM Enterprises to be the name you already know.";
      const defaultParagraphPlain = "Buildings always need work eventually &mdash; a renovation, an interior upgrade, structural repairs, or scaffolding for maintenance. When that time comes for {{company_name}}, I'd like SKM Enterprises to be the name you already know.";
      
      html = html.replace(defaultParagraph, text);
      html = html.replace(defaultParagraphPlain, text);

      // Substitute variables
      const contactName = lead.contact_name || 'Owner / Manager';
      html = html.replace(/\{\{company_name\}\}/g, lead.business_name);
      html = html.replace(/\{\{first_name\}\}/g, contactName);

      // Send email via Nodemailer as HTML
      await sendEmail({
        to: cleanEmail,
        subject,
        html,
        senderName: profile.sender_name,
        replyTo: profile.sender_email,
      });
    } else {
      // Send email via Nodemailer as Text
      await sendEmail({
        to: cleanEmail,
        subject,
        text,
        senderName: profile ? profile.sender_name : undefined,
        replyTo: profile ? profile.sender_email : undefined,
      });
    }

    const now = new Date().toISOString();
    
    // Set follow_up_due_at to 4 days from now
    const followUpDate = new Date();
    followUpDate.setDate(followUpDate.getDate() + 4);
    const followUpDueAt = followUpDate.toISOString();

    // 1. Update lead status to 'sent'
    const { error: leadUpdateError } = await supabase
      .from('leads')
      .update({
        status: 'sent',
        last_contacted_at: now,
        follow_up_due_at: followUpDueAt,
      })
      .eq('id', leadId);

    if (leadUpdateError) {
      throw new Error(`Failed to update lead status: ${leadUpdateError.message}`);
    }

    // 2. Update message record to note sent_at and save the final_text
    const { error: msgUpdateError } = await supabase
      .from('messages')
      .update({
        sent_at: now,
        final_text: text,
      })
      .eq('id', messageId);

    if (msgUpdateError) {
      throw new Error(`Failed to update message: ${msgUpdateError.message}`);
    }

    // 3. Update the persistent sent_log.json atomically
    try {
      const identifier = getLeadIdentifier(cleanEmail, lead.phone, businessName);
      const logData = loadSentLog();
      
      if (logData[identifier]) {
        logData[identifier].contact_status = 'sent';
        logData[identifier].date_last_contacted = now;
        logData[identifier].number_of_contacts = (logData[identifier].number_of_contacts || 0) + 1;
      } else {
        logData[identifier] = {
          identifier,
          business_name: businessName,
          source: profile?.name ? `Lead Finder -- ${profile.name}` : 'Lead Finder Manual',
          date_first_sourced: now,
          date_last_contacted: now,
          contact_status: 'sent',
          number_of_contacts: 1
        };
      }
      
      saveLogAtomic(logData);
    } catch (logErr) {
      console.error('Failed to update sent_log.json in sendPitchAction:', logErr);
    }

    revalidatePath(`/leads/${leadId}`);
    revalidatePath('/');
    return { success: true };
  } catch (error: any) {
    console.error('Failed to send email:', error);
    return { success: false, error: error.message || 'Failed to send email' };
  }
}

// 4.5. Send All Draft Pitches for a Profile
export async function sendAllDraftsAction(profileId: string) {
  try {
    if (!profileId) {
      return { success: false, error: 'No profile ID provided.' };
    }

    // Fetch profile details
    const { data: profile, error: profileError } = await supabase
      .from('profiles')
      .select('*')
      .eq('id', profileId)
      .single();

    if (profileError || !profile) {
      return { success: false, error: `Failed to fetch profile: ${profileError?.message || 'Profile not found'}` };
    }

    // Fetch all leads in 'draft' status belonging to this profile
    const { data: leads, error: leadsError } = await supabase
      .from('leads')
      .select('*, messages(*)')
      .eq('profile_id', profileId)
      .eq('status', 'draft');

    if (leadsError) {
      return { success: false, error: `Failed to fetch draft leads: ${leadsError.message}` };
    }

    if (!leads || leads.length === 0) {
      return { success: true, count: 0, message: 'No draft leads found for this profile.' };
    }

    // Filter leads that have an unsent 'initial' pitch message (sent_at is null)
    const leadsWithDraftMessages = leads.filter(lead => {
      const draftMsg = lead.messages?.find(
        (m: any) => m.message_type === 'initial' && !m.sent_at
      );
      // Also make sure they have a valid email address
      const hasEmail = lead.email && !lead.email.toLowerCase().includes('no-email') && lead.email.trim() !== '';
      return draftMsg && hasEmail;
    });

    if (leadsWithDraftMessages.length === 0) {
      return { success: true, count: 0, message: 'No unsent draft pitches found for this profile. Please generate pitches first.' };
    }

    let sentCount = 0;
    const isSKM = profile.name === 'SKM Dev Team';

    // Loop through each lead and send the email
    for (const lead of leadsWithDraftMessages) {
      const draftMsg = lead.messages.find(
        (m: any) => m.message_type === 'initial' && !m.sent_at
      );
      
      const cleanEmail = lead.email.trim().replace(/\.$/, '');
      const subject = isSKM 
        ? `SKM Enterprises — Civil Contracting & Maintenance for ${lead.business_name}`
        : `Proposal for ${lead.business_name} — Web & Automation services`;

      const textBody = draftMsg.final_text || draftMsg.generated_text;

      if (isSKM && profile.email_template) {
        let html = profile.email_template;
        
        // Target paragraph placeholders to replace with edited pitch text
        const defaultParagraph = "Buildings always need work eventually &mdash; a renovation, an interior upgrade, structural repairs, or scaffolding for maintenance. When that time comes for {{company_name}}, I''d like SKM Enterprises to be the name you already know.";
        const defaultParagraphPlain = "Buildings always need work eventually &mdash; a renovation, an interior upgrade, structural repairs, or scaffolding for maintenance. When that time comes for {{company_name}}, I'd like SKM Enterprises to be the name you already know.";
        
        html = html.replace(defaultParagraph, textBody);
        html = html.replace(defaultParagraphPlain, textBody);

        // Substitute variables
        const contactName = lead.contact_name || 'Owner / Manager';
        html = html.replace(/\{\{company_name\}\}/g, lead.business_name);
        html = html.replace(/\{\{first_name\}\}/g, contactName);

        // Send email via Nodemailer as HTML
        await sendEmail({
          to: cleanEmail,
          subject,
          html,
          senderName: profile.sender_name,
          replyTo: profile.sender_email,
        });
      } else {
        // Send email via Nodemailer as Text
        await sendEmail({
          to: cleanEmail,
          subject,
          text: textBody,
          senderName: profile.sender_name,
          replyTo: profile.sender_email,
        });
      }

      const now = new Date().toISOString();
      const followUpDate = new Date();
      followUpDate.setDate(followUpDate.getDate() + 4);
      const followUpDueAt = followUpDate.toISOString();

      // 1. Update lead status to 'sent'
      await supabase
        .from('leads')
        .update({
          status: 'sent',
          last_contacted_at: now,
          follow_up_due_at: followUpDueAt,
        })
        .eq('id', lead.id);

      // 2. Update message record to note sent_at
      await supabase
        .from('messages')
        .update({
          sent_at: now,
          final_text: textBody,
        })
        .eq('id', draftMsg.id);

      sentCount++;
    }

    revalidatePath('/');
    return { success: true, count: sentCount, message: `Successfully sent ${sentCount} outreach emails!` };
  } catch (error: any) {
    console.error('sendAllDraftsAction failed:', error);
    return { success: false, error: error.message || 'An unexpected error occurred' };
  }
}

// 5. Update Lead Status Manually Action
export async function updateLeadStatusAction(leadId: string, status: LeadStatus) {
  try {
    const { error } = await supabase
      .from('leads')
      .update({ status })
      .eq('id', leadId);

    if (error) {
      return { success: false, error: error.message };
    }

    revalidatePath(`/leads/${leadId}`);
    revalidatePath('/');
    return { success: true };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

// 6. Delete Lead Action
export async function deleteLeadAction(leadId: string) {
  try {
    const { error } = await supabase
      .from('leads')
      .delete()
      .eq('id', leadId);

    if (error) {
      return { success: false, error: error.message };
    }

    revalidatePath('/');
    return { success: true };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

// 7. Manual Follow-up Trigger Action
export async function triggerFollowUpsAction() {
  try {
    const now = new Date().toISOString();

    // Query leads that are in 'sent' status and have a follow_up_due_at that is in the past/due
    const { data: leads, error: leadsError } = await supabase
      .from('leads')
      .select('*')
      .eq('status', 'sent')
      .lte('follow_up_due_at', now);

    if (leadsError) {
      console.error('Error fetching leads for follow-up:', leadsError);
      return { success: false, error: `Database error: ${leadsError.message}` };
    }

    if (!leads || leads.length === 0) {
      return { success: true, count: 0 };
    }

    let processedCount = 0;

    // Process sequentially to remain within rate limits
    for (const lead of leads) {
      const notes = lead.context_notes ? lead.context_notes : 'None';
      
      const systemPrompt = `You are writing a short, polite cold follow-up email from Karan, a freelance developer/data professional in Bengaluru, to a local business. We previously sent them a proposal. Business name: ${lead.business_name}. Business type: ${lead.business_type}. Context notes: ${notes}. Write a 2-3 sentence follow-up email politely checking in, bumping the previous proposal, and asking if they had a chance to review it. No generic flattery. Keep it under 60 words.`;

      const response = await groq.chat.completions.create({
        model: GROQ_MODEL,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: 'Generate the follow-up email pitch.' }
        ],
        temperature: 0.7,
        max_tokens: 100,
      });

      const generatedText = response.choices[0]?.message?.content?.trim() || '';

      if (generatedText) {
        // A. Insert follow-up message draft
        const { error: msgError } = await supabase
          .from('messages')
          .insert({
            lead_id: lead.id,
            generated_text: generatedText,
            message_type: 'follow_up',
          });

        if (msgError) {
          console.error(`Error saving follow-up message for lead ${lead.id}:`, msgError);
          continue;
        }

        // B. Update lead status back to 'draft' and clear the follow-up due date
        const { error: leadError } = await supabase
          .from('leads')
          .update({
            status: 'draft',
            follow_up_due_at: null,
          })
          .eq('id', lead.id);

        if (leadError) {
          console.error(`Error updating status for lead ${lead.id}:`, leadError);
          continue;
        }

        processedCount++;
      }
    }

    revalidatePath('/');
    return { success: true, count: processedCount };
  } catch (error: any) {
    console.error('Follow-up generation failed:', error);
    return { success: false, error: error.message || 'An unexpected error occurred' };
  }
}

// 8. Run Python Lead Finder Action (Karan/Salons version)
export async function runLeadFinderAction(
  businessType: string,
  areas: string,
  radius: number,
  profileId: string
) {
  try {
    // Sanitize inputs
    const sanitizedType = businessType.replace(/[^a-zA-Z0-9\s]/g, '').trim();
    const sanitizedAreas = areas.replace(/[^a-zA-Z0-9\s,]/g, '').trim();
    const sanitizedRadius = Math.min(Math.max(Number(radius) || 1500, 500), 10000);

    console.log(`Executing: python lead_finder.py "${sanitizedType}" "${sanitizedAreas}" ${sanitizedRadius}`);

    // Execute script
    const { stdout, stderr } = await execPromise(
      `python lead_finder.py "${sanitizedType}" "${sanitizedAreas}" ${sanitizedRadius}`,
      { cwd: process.cwd() }
    );

    console.log('Lead finder stdout:', stdout);
    if (stderr) {
      console.warn('Lead finder stderr:', stderr);
    }

    // Helper to read CSV safely
    const readCsvFile = (filename: string) => {
      const csvPath = path.join(process.cwd(), filename);
      if (!fs.existsSync(csvPath)) return [];
      const content = fs.readFileSync(csvPath, 'utf-8');
      return parse(content, {
        columns: true,
        skip_empty_lines: true,
        trim: true,
      });
    };

    // Load from both output files
    const readyRecords = readCsvFile('leads_ready_for_email.csv');
    const phoneRecords = readCsvFile('leads_phone_only.csv');
    const records = [...readyRecords, ...phoneRecords];

    if (records.length === 0) {
      return { success: true, count: 0, message: 'Scrape completed, but no new leads found in CSV files.' };
    }

    // Get existing leads to prevent duplicates for this profile
    let dbQuery = supabase.from('leads').select('business_name');
    if (profileId) {
      dbQuery = dbQuery.eq('profile_id', profileId);
    } else {
      dbQuery = dbQuery.is('profile_id', null);
    }
    const { data: existingLeads, error: fetchError } = await dbQuery;

    if (fetchError) {
      throw new Error(`Failed to query existing leads: ${fetchError.message}`);
    }

    const existingNames = new Set(
      (existingLeads || []).map((l: any) => l.business_name.trim().toLowerCase())
    );

    // Filter for new leads that are not already in DB
    const newLeads = records.filter(
      (record: any) => 
        (record.email || record.phone) &&
        !existingNames.has(record.business_name.trim().toLowerCase())
    );

    if (newLeads.length === 0) {
      return { 
        success: true, 
        count: 0, 
        message: 'Scrape completed. All found leads are already in your Lead Finder database.' 
      };
    }

    // Prepare for insertion
    const leadsToInsert = newLeads.map((record: any) => {
      const hasEmail = record.email && record.email.trim() !== '' && !record.email.toLowerCase().includes('no-email');
      const contactMethod = hasEmail ? 'email' : 'phone';
      const cleanEmail = hasEmail ? record.email.trim() : null;

      return {
        profile_id: profileId || null,
        business_name: record.business_name,
        email: cleanEmail,
        business_type: record.business_type,
        contact_name: record.contact_name || null,
        phone: record.phone || null,
        context_notes: record.context_notes || null,
        status: 'draft',
        contact_method: contactMethod,
      };
    });

    const { error: insertError } = await supabase.from('leads').insert(leadsToInsert);

    if (insertError) {
      throw new Error(`Failed to save new leads: ${insertError.message}`);
    }

    revalidatePath('/');
    return { 
      success: true, 
      count: leadsToInsert.length, 
      message: `Scrape complete! Imported ${leadsToInsert.length} new leads to your active profile.` 
    };
  } catch (error: any) {
    console.error('runLeadFinderAction failed:', error);
    return { success: false, error: error.message || 'Failed to execute lead scraper.' };
  }
}

// 9. Run Python Building Lead Finder Action (SKM/Buildings version)
export async function runLeadFinderBuildingsAction(
  category: string,
  areas: string,
  radius: number,
  profileId: string
) {
  try {
    const sanitizedCategory = category.replace(/[^a-zA-Z0-9\s_]/g, '').trim();
    const sanitizedAreas = areas.replace(/[^a-zA-Z0-9\s,]/g, '').trim();
    const sanitizedRadius = Math.min(Math.max(Number(radius) || 1500, 500), 10000);

    console.log(`Executing: python lead_finder_buildings.py "${sanitizedCategory}" "${sanitizedAreas}" ${sanitizedRadius}`);

    // Execute script
    const { stdout, stderr } = await execPromise(
      `python lead_finder_buildings.py "${sanitizedCategory}" "${sanitizedAreas}" ${sanitizedRadius}`,
      { cwd: process.cwd() }
    );

    console.log('Building scraper stdout:', stdout);
    if (stderr) {
      console.warn('Building scraper stderr:', stderr);
    }

    // Helper to read CSV safely
    const readCsvFile = (filename: string) => {
      const csvPath = path.join(process.cwd(), filename);
      if (!fs.existsSync(csvPath)) return [];
      const content = fs.readFileSync(csvPath, 'utf-8');
      return parse(content, {
        columns: true,
        skip_empty_lines: true,
        trim: true,
      });
    };

    // Load from both output files
    const readyRecords = readCsvFile('leads_ready_for_email.csv');
    const phoneRecords = readCsvFile('leads_phone_only.csv');
    const records = [...readyRecords, ...phoneRecords];

    if (records.length === 0) {
      return { success: true, count: 0, message: 'Scrape completed, but no new building leads found in CSV files.' };
    }

    // Get existing leads for this profile
    let dbQuery = supabase.from('leads').select('business_name');
    if (profileId) {
      dbQuery = dbQuery.eq('profile_id', profileId);
    } else {
      dbQuery = dbQuery.is('profile_id', null);
    }
    const { data: existingLeads, error: fetchError } = await dbQuery;

    if (fetchError) {
      throw new Error(`Failed to query existing leads: ${fetchError.message}`);
    }

    const existingNames = new Set(
      (existingLeads || []).map((l: any) => l.business_name.trim().toLowerCase())
    );

    // Filter for new leads that are not already in DB
    const newLeads = records.filter(
      (record: any) => 
        (record.email || record.phone) &&
        !existingNames.has(record.business_name.trim().toLowerCase())
    );

    if (newLeads.length === 0) {
      return { 
        success: true, 
        count: 0, 
        message: 'Scrape completed. All found leads are already in your Lead Finder database.' 
      };
    }

    // Prepare leads for insertion linked to profileId
    const leadsToInsert = newLeads.map((record: any) => {
      const hasEmail = record.email && record.email.trim() !== '' && !record.email.toLowerCase().includes('no-email');
      const contactMethod = hasEmail ? 'email' : 'phone';
      const cleanEmail = hasEmail ? record.email.trim() : null;

      return {
        profile_id: profileId || null,
        business_name: record.business_name,
        email: cleanEmail,
        business_type: record.business_type,
        contact_name: record.contact_name || null,
        phone: record.phone || null,
        context_notes: record.context_notes || null,
        status: 'draft',
        contact_method: contactMethod,
      };
    });

    const { error: insertError } = await supabase.from('leads').insert(leadsToInsert);

    if (insertError) {
      throw new Error(`Failed to save new leads: ${insertError.message}`);
    }

    revalidatePath('/');
    return { 
      success: true, 
      count: leadsToInsert.length, 
      message: `Scrape complete! Imported ${leadsToInsert.length} new building leads to your active profile.` 
    };
  } catch (error: any) {
    console.error('runLeadFinderBuildingsAction failed:', error);
    return { success: false, error: error.message || 'Failed to execute building scraper.' };
  }
}

// 9.5 Mark Lead as Bounced Action
export async function markLeadBouncedAction(leadId: string) {
  try {
    const { data: lead, error: fetchError } = await supabase
      .from('leads')
      .select('*')
      .eq('id', leadId)
      .single();

    if (fetchError || !lead) {
      throw new Error(`Failed to fetch lead: ${fetchError?.message || 'Lead not found'}`);
    }

    const bounceNote = lead.context_notes 
      ? `[BOUNCED] ${lead.context_notes}`
      : '[BOUNCED] Email bounced.';

    // Update status in Supabase to 'lost'
    const { error: updateError } = await supabase
      .from('leads')
      .update({
        status: 'lost',
        context_notes: bounceNote
      })
      .eq('id', leadId);

    if (updateError) {
      throw new Error(`Failed to update lead status: ${updateError.message}`);
    }

    // Update sent_log.json
    try {
      const identifier = getLeadIdentifier(lead.email, lead.phone, lead.business_name);
      const logData = loadSentLog();
      
      if (logData[identifier]) {
        logData[identifier].contact_status = 'bounced';
      } else {
        logData[identifier] = {
          identifier,
          business_name: lead.business_name,
          source: 'Lead Finder Manual Mark',
          date_first_sourced: new Date().toISOString(),
          date_last_contacted: new Date().toISOString(),
          contact_status: 'bounced',
          number_of_contacts: 1
        };
      }
      
      saveLogAtomic(logData);
    } catch (logErr) {
      console.error('Failed to update sent_log.json in markLeadBouncedAction:', logErr);
    }

    revalidatePath(`/leads/${leadId}`);
    revalidatePath('/');
    return { success: true };
  } catch (error: any) {
    console.error('Failed to mark lead as bounced:', error);
    return { success: false, error: error.message || 'Failed to mark lead as bounced' };
  }
}

// 10. Get All Profiles Action
export async function getProfilesAction() {
  try {
    const { data, error } = await supabase
      .from('profiles')
      .select('*')
      .order('name', { ascending: true });

    if (error) {
      throw error;
    }

    return { success: true, data: data || [] };
  } catch (error: any) {
    console.error('getProfilesAction failed:', error);
    return { success: false, error: error.message || 'Failed to load profiles.' };
  }
}

