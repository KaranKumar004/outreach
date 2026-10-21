# Website Creation Outreach Engine (Setup #2)

A dedicated, multi-channel outreach pipeline designed to find businesses and agencies **without a website** and offer modern, high-converting website design services.

---

## 🎯 The Offer & Value Proposition

> **"I build fast, clean, mobile-ready websites for local businesses and agencies to get found on Google, accept online inquiries, and turn visitors into paying clients. I offer a free 1-page sample preview before you commit."**

- **Target Niches:** Digital agencies, marketing consultancies, medical clinics, dental practices, fitness centers & gyms, salons & spas, local retail shops, restaurants, accounting & CA firms.
- **Geography:** Configurable for both India (Bengaluru, Mumbai, Delhi, etc.) and International markets (US, UK, etc.).
- **Channels:**
  1. **Cold Email:** Sent via Gmail SMTP with deterministic subject rotation (< 8 words), short copy (< 90 words), and warm-up throttling.
  2. **WhatsApp / Phone:** Generates pre-formatted Click-to-Chat WhatsApp links (`https://wa.me/...`) and tailored pitch scripts for businesses that list only a phone number.

---

## 📁 Folder Structure

```
website_outreach/
├── README.md                   # This documentation guide
├── .env.example                # Configuration template
├── web_lead_finder.py          # Finds businesses WITHOUT websites via OpenStreetMap
├── web_outreach_pipeline.py    # Cold email pipeline (dry-run, live, warmup, templates)
├── whatsapp_templates.py       # WhatsApp message builder & click-to-chat link generator
├── leads_website.csv           # Master database of discovered prospects
├── leads_phone_whatsapp.csv    # Exported phone list ready for WhatsApp / Phone outreach
├── outreach_log.csv            # Persistent log of all email sends & delivery statuses
├── sent_log.json               # Deduplication cache preventing repeated scraping
└── preview_drafts/             # HTML & plain-text previews generated during dry-runs
```

---

## 🚀 Quick Start Guide

### 1. Configuration
Create your local environment file:
```bash
cp website_outreach/.env.example website_outreach/.env.local
```

Set your details in `website_outreach/.env.local`:
- `SMTP_USER` and `SMTP_PASS` (Gmail 16-character App Password)
- `OUTREACH_SENDER_NAME` (e.g. `Karan`)
- `PORTFOLIO_URL` (Link to your web design portfolio or sample site)
- `DEFAULT_PHONE_COUNTRY` (`IN` for India, `US` for United States)
- `TEST_RECIPIENTS` (Your email for testing drafts)

---

### 2. Sourcing Leads Without Websites

Use `web_lead_finder.py` to discover businesses in any niche and location:

```bash
# Find agencies in Koramangala, Bengaluru
py website_outreach/web_lead_finder.py agency "Koramangala, Bengaluru" 3000

# Find clinics in Indiranagar
py website_outreach/web_lead_finder.py clinic "Indiranagar, Bengaluru" 2500

# Find gyms in Austin, Texas (US mode)
py website_outreach/web_lead_finder.py gym "Austin, TX" 15000

# Check total sourced counts
py website_outreach/web_lead_finder.py --report
```

**What it does:**
- Queries OpenStreetMap / Overpass for the requested niche and radius.
- Filters out all businesses that already have a website.
- Verifies absence of official domains (separating real domains from Instagram/Maps/Facebook links).
- Categorizes contacts into `email` channel or `whatsapp` channel.
- Automatically exports `leads_website.csv` and `leads_phone_whatsapp.csv`.

---

### 3. Reviewing WhatsApp / Phone Leads

Open `website_outreach/leads_phone_whatsapp.csv`. You will find:
- `business_name`: The prospect's business name.
- `phone` / `normalized_phone`: E.164 formatted phone number.
- `whatsapp_link`: A direct `https://wa.me/<number>?text=...` link. Clicking this immediately opens a chat with the prospect pre-filled with the tailored pitch message.
- `pitch_message`: Segment-specific pitch offering a free 1-page sample preview.

---

### 4. Running the Email Outreach Pipeline

#### A. Safe Dry-Run (Default)
Simulate the run and inspect generated drafts in `website_outreach/preview_drafts/`:
```bash
py website_outreach/web_outreach_pipeline.py
```

#### B. Test Send (Deliver to Your Own Inbox First)
Verify formatting and deliverability in your own email before contacting real leads:
```bash
py website_outreach/web_outreach_pipeline.py --test-send --send-live
```

#### C. Live Batch Sending
Send live emails throttled by the warmup schedule:
```bash
py website_outreach/web_outreach_pipeline.py --send-live
```

---

## 🛡️ Deliverability & Safety Rules

1. **Dry-Run by Default**: Unless `--send-live` is explicitly passed, no email is ever sent.
2. **Subject Lines < 8 Words**: Benefit-led, conversational, zero spam keywords.
3. **Body < 90 Words**: Concise, respectful of the recipient's time, offering a zero-pressure sample mockup.
4. **Warm-Up Limits**:
   - Week 1: 5 emails / day
   - Week 2: 10 emails / day
   - Week 3+: 25 emails / day
5. **Duplicate Prevention**: Every recipient is checked against `outreach_log.csv` before dispatch.
