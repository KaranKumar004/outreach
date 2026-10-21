# LeadPilot — AI Outreach Automation (Phase 1 MVP)
**For: Karan | Personal use first, productize later | Stack: Next.js + Supabase + Claude API**

---

## 1. Problem
Karan is manually personalizing and sending WhatsApp/email pitches to local Bengaluru businesses (e.g. Dreams Realty), tracking replies in a spreadsheet. This is slow and doesn't scale past a handful of leads/day.

## 2. Goal (MVP only)
Build a single-user web app that:
1. Imports a list of leads (CSV)
2. Uses Claude API to generate a personalized pitch per lead
3. Lets Karan review/edit before sending (no blind auto-send)
4. Sends via Email (SMTP/Gmail) — WhatsApp deferred to Phase 2 (Cloud API approval takes days)
5. Tracks status (Draft → Sent → Replied → No Response → Won/Lost)
6. Auto-schedules a follow-up nudge if no reply after N days

## 3. Explicit Non-Goals (MVP)
- No multi-tenant / multi-user support
- No WhatsApp integration yet (email-first, WhatsApp Cloud API in Phase 2 once verified)
- No billing/Razorpay (that's Phase 2 productization)
- No AI auto-reply handling — just outbound + manual reply logging

## 4. Tech Stack
- **Frontend/Backend**: Next.js (App Router)
- **Database**: Supabase (Postgres)
- **AI**: Anthropic Claude API (claude-sonnet-4-6) for message personalization
- **Email sending**: Gmail API or Nodemailer + SMTP (Karan's existing Gmail)
- **Hosting**: Vercel (free tier) for frontend, Supabase free tier for DB

## 5. Data Model

**leads** table
| column | type | notes |
|---|---|---|
| id | uuid | pk |
| business_name | text | |
| contact_name | text | nullable |
| email | text | |
| phone | text | nullable, for future WhatsApp |
| business_type | text | e.g. "real estate", "salon" |
| context_notes | text | nullable — anything scraped/observed about the business |
| status | enum | draft, sent, replied, no_response, won, lost |
| created_at | timestamp | |
| last_contacted_at | timestamp | nullable |
| follow_up_due_at | timestamp | nullable |

**messages** table
| column | type | notes |
|---|---|---|
| id | uuid | pk |
| lead_id | uuid | fk → leads |
| generated_text | text | AI-generated draft |
| final_text | text | after Karan edits |
| sent_at | timestamp | nullable |
| message_type | enum | initial, follow_up |

## 6. Core Features (build in this order)

### Feature 1: Lead Import
- CSV upload → parse → insert into `leads` table
- Required columns: business_name, email, business_type (others optional)

### Feature 2: AI Personalization
- Button: "Generate pitches" → for each lead without a draft, call Claude API
- Prompt template (system prompt for the API call):
  > "You are writing a short, friendly cold outreach email from Karan, a freelance developer/data professional in Bengaluru, to a local business. Business name: {business_name}. Business type: {business_type}. Context notes: {context_notes}. Write a 3-4 sentence email pitching a relevant service (e.g. a simple website, automation tool, or data dashboard) without sounding like a template. No generic flattery. End with a soft call-to-action (15-min call). Keep it under 80 words."
- Store result in `messages.generated_text`, lead status stays `draft`

### Feature 3: Review Dashboard
- Table view of all leads with status, business name, draft preview
- Click into a lead → see AI draft, editable textarea → save as `final_text`
- "Send" button only enabled once `final_text` exists

### Feature 4: Send via Email
- On Send: use Gmail API (preferred, since Karan already has Gmail) to send `final_text`
- Update lead: `status = sent`, `last_contacted_at = now()`, `follow_up_due_at = now() + 4 days`

### Feature 5: Follow-Up Automation
- A scheduled job (Vercel Cron, runs daily) checks leads where `status = sent` AND `follow_up_due_at <= now()`
- Auto-generates a short follow-up draft via Claude API, sets lead back to `draft` status with `message_type = follow_up` for Karan to review/send (still manual send — no fully blind automation in MVP)

### Feature 6: Manual Reply Logging
- Simple dropdown on each lead to mark: Replied / No Response / Won / Lost
- (Phase 2: auto-detect replies via Gmail inbox polling)

## 7. UI Pages
1. `/` — Dashboard: leads table (filter by status), "Import CSV" button, "Generate Pitches" button
2. `/leads/[id]` — Lead detail: AI draft, edit box, send button, status dropdown, history of messages
3. `/import` — CSV upload page

## 8. MVP Success Criteria
- Karan can upload 20 real leads, generate pitches, review/edit, send 20 emails, and see status update — all in under 30 minutes, replacing the manual spreadsheet process.

---

## ✅ COPY-PASTE PROMPT FOR ANTIGRAVITY

```
Build a Next.js (App Router) web app called "LeadPilot" — a personal outreach automation tool. Use Supabase for the database and the Anthropic Claude API for AI-generated message personalization.

Requirements:

1. Database schema (Supabase/Postgres):
   - leads table: id (uuid, pk), business_name (text), contact_name (text, nullable), email (text), phone (text, nullable), business_type (text), context_notes (text, nullable), status (enum: draft, sent, replied, no_response, won, lost — default draft), created_at (timestamp, default now), last_contacted_at (timestamp, nullable), follow_up_due_at (timestamp, nullable)
   - messages table: id (uuid, pk), lead_id (uuid, fk -> leads.id), generated_text (text), final_text (text, nullable), sent_at (timestamp, nullable), message_type (enum: initial, follow_up — default initial)

2. Pages:
   - "/" Dashboard: table of all leads (business name, type, status, last contacted), filterable by status. Buttons: "Import CSV" and "Generate Pitches for new leads".
   - "/import": CSV upload form. Expected columns: business_name, email, business_type, contact_name (optional), phone (optional), context_notes (optional). Parse and bulk-insert into leads table.
   - "/leads/[id]": Lead detail page showing lead info, the latest AI-generated draft in an editable textarea, a "Send Email" button, and a status dropdown (Replied/No Response/Won/Lost). Show message history below.

3. AI personalization (server action or API route):
   - For each lead without a draft message, call the Anthropic API (model: claude-sonnet-4-6) with this system prompt template, filling in the lead's data:
     "You are writing a short, friendly cold outreach email from Karan, a freelance developer/data professional in Bengaluru, to a local business. Business name: {business_name}. Business type: {business_type}. Context notes: {context_notes}. Write a 3-4 sentence email pitching a relevant service (e.g. a simple website, automation tool, or data dashboard) without sounding like a template. No generic flattery. End with a soft call-to-action (15-min call). Keep it under 80 words."
   - Save the result to messages.generated_text, lead status stays "draft".

4. Email sending:
   - Integrate Gmail API (OAuth) or Nodemailer+SMTP to send the final_text as an email to the lead's email address.
   - On successful send: update lead status to "sent", set last_contacted_at to now, set follow_up_due_at to 4 days from now.

5. Follow-up automation:
   - Add a Vercel Cron job (daily) that finds leads with status "sent" and follow_up_due_at in the past, generates a short follow-up draft via the same Claude API pattern (message_type: follow_up), and sets the lead status back to "draft" so Karan can review and send manually.

6. Keep the UI minimal and functional — no need for elaborate design, just clean and usable. Use Tailwind for styling.

Build this in working, runnable order: schema first, then CSV import, then AI generation, then review/send UI, then the cron follow-up job. Ask me for my Anthropic API key, Supabase project URL/key, and Gmail OAuth credentials as environment variables when needed — do not hardcode any secrets.
```

---

**Next step after Antigravity builds this**: test with 10–15 real leads from your tracker before scaling up.
