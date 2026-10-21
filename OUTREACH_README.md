# Bengaluru Freelance Data Service — Cold Email Outreach Pipeline

A focused, compliant, and battle-tested cold-email outreach pipeline designed for Karan's freelance data automation practice in Bengaluru. Built as an extension of the `lead_finder.py` architecture.

---

## 🎯 The Offer

> **"I turn messy business data (sales, expenses, inventory, attendance) into a simple dashboard or automated report. Fixed-price, delivered in about 3 days. I offer one free small fix (one cleaned sheet or one chart) to prove value."**

- **Target Geographic Focus:** Bengaluru businesses (Indiranagar, Koramangala, HSR Layout, Whitefield, Jayanagar, etc.)
- **Target Segments:**
  1. `gyms`: Gyms and fitness studios (attendance, renewals, drop-offs)
  2. `clinics`: Clinics and dental practices (appointment logs, no-shows, collections)
  3. `retail`: Retail and D2C brands (sales reconciliation, stockouts, dead inventory)
  4. `agencies`: Digital marketing agencies (client reporting, ad spend, ROAS)
  5. `accounting`: CA and accounting firms (filing deadlines, GST reconciliations)
  6. `manufacturers`: Small manufacturers (raw material inventory, machine uptime, dispatch logs)
  7. `coaching`: Coaching centres (student batches, fee installments, test attendance)

---

## 🛡️ Safety & Compliance Architecture

1. **Personalisation Without Fake Review:**
   - Extracts real services, taglines, or specialties directly from the business homepage.
   - Formatted objectively (e.g. `"With your focus on Structured Finance,"`).
   - If no real detail is found, skips line 1 entirely. Never claims a human review occurred.
2. **Benefit-Led Subjects (< 8 Words):**
   - Rotates 2–3 benefit-led subject variants per segment (e.g. `"Fewer no-shows, one simple dashboard"`).
   - Deterministic rotation via email hash.
3. **Clean Business Names & Greetings:**
   - Strips generic noise terms (`"Dental Clinic"`, `"Clinic"`, `"Gym"`).
   - If generic, falls back gracefully to `"Hi there,"`.
   - If specific, greets with `"Hi {clean_name} team,"`.
4. **Target & Inbox Filters:**
   - Excludes known corporate chains (`Kaya`, `Kosmoderma`, `Cult.fit`, `Apollo`, `Fortis`, `Manipal`, `Puma`, `Westside`, etc.) via configurable `CHAIN_BLOCKLIST`.
   - Excludes generic corporate inboxes (`centralenquiry@`, `enquiry@`, `customercare@`, `support@`, `careers@`, `hr@`).
   - Targets independent local businesses with `info@`, `contact@`, `hello@`, or owner inboxes.
5. **Healthcare & Clinic Privacy Protection:**
   - Clinic and diagnostic templates never ask for patient data.
   - Explicitly asks for: `"send me an anonymised or dummy sample sheet with no patient names or details"`.
6. **Sender Safety Pre-Send Check:**
   - Reads `SMTP_USER` and `SMTP_REPLY_TO` from `.env` only.
   - Refuses to send if sender or reply-to address matches any account in `PROTECTED_ACCOUNTS`.
7. **Warm-Up Mode:**
   - Automatically throttles daily caps based on first send date in `outreach_log.csv`:
     - **Week 1:** 5 emails/day
     - **Week 2:** 10 emails/day
     - **Week 3+:** 25 emails/day
   - Can be overridden with `--no-warmup`.
8. **Sending Window:**
   - **10:00 to 17:00 IST**, Monday to Friday only (weekends strictly barred).
9. **Bounce Circuit Breaker:**
   - If `< 20` sends: pauses and alerts after 3 bounces.
   - If `≥ 20` sends: evaluates the 5.0% bounce rate threshold (`bounces / sent > 0.05`).
10. **Follow-up Policy:**
    - Exactly 1 follow-up sent after **4 business days** if no reply (maximum 2 emails total).

---

## 🚀 Setup & Installation

### 1. Environment Configuration
Copy `.env.example` to `.env.local` and configure your credentials:
```bash
cp .env.example .env.local
```

```env
# Gmail SMTP
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=sheetbolt.analytics@gmail.com
SMTP_PASS=your-16-char-app-password
SMTP_REPLY_TO=sheetbolt.analytics@gmail.com

# Sender identity
OUTREACH_SENDER_NAME=Karan from Sheetbolt
OUTREACH_SUPPORT_EMAIL=sheetbolt.analytics@gmail.com

# Pre-send protection
PROTECTED_ACCOUNTS=your_personal_email@gmail.com

# Recipient for --test-send
TEST_RECIPIENTS=your_test_email@gmail.com

# Website & Sample dashboard URLs
SITE_URL=https://sheetboltanalytics.netlify.app
SAMPLE_DASHBOARD_URL=https://sheetboltanalytics.netlify.app/#top
EMAIL_IMAGES=on

# Optional chain blocklist overrides
CHAIN_BLOCKLIST=Kaya,Kosmoderma,Cult.fit,Apollo,Fortis,Manipal,Puma,Westside,Golds Gym
```

### 2. Run Test Suite
Verify that all 40 unit tests pass:
```bash
.\lead-finder-standalone\.venv\Scripts\pytest.exe tests/test_outreach.py -v
```

---

## 💻 CLI Commands

### 1. Find & Source New Leads
Scrape Bengaluru businesses, visit websites, extract public business emails, verify MX records, and dedupe into `leads.csv`:
```bash
# Sourcing clinics in Indiranagar
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --find-leads --segment clinics --area "Indiranagar" --limit 10

# Sourcing gyms in Koramangala
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --find-leads --segment gyms --area "Koramangala" --limit 10

# Sourcing accounting firms in Indiranagar
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --find-leads --segment accounting --area "Indiranagar" --limit 5
```

### 2. Preview Drafts (Dry-Run Mode — Default)
Generates `.txt` drafts inside `preview_drafts/` and prints the first 5 drafted emails for manual review. Zero emails are sent:
```bash
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --dry-run --limit 5
```

### 3. Test Send (`--test-send`)
Dispatches the first generated draft strictly to the addresses configured in `TEST_RECIPIENTS` in `.env` (never emails the business lead):
```bash
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --test-send
```

### 4. Send Live Emails Safely
Sends up to the active warmup cap (5/10/25 per day) within the 10:00–17:00 IST weekday window, enforcing 60–180s delays:
```bash
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --send --limit 5
```
*(Optional flag `--force-window` is available strictly for manual testing outside business hours; `--no-warmup` disables warmup throttling).*

### 5. Follow-up Pipeline
Finds leads contacted $\ge 4$ business days ago that have not replied, and drafts/sends follow-up #2:
```bash
# Preview follow-up drafts:
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --followup --dry-run

# Send eligible follow-ups live:
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --followup --send
```

### 6. Mark Replies & Opt-Outs
```bash
# Mark as replied (never sends follow-up)
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --mark-replied "client@clinic.com"

# Mark as unsubscribed (permanently removes from outreach)
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --mark-unsubscribed "optout@gym.com"

# Mark as bounced
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --mark-bounced "dead@domain.com"
```

### 7. View Outreach Status Report
Display status breakdown (sent, bounced, replied, unsubscribed) by segment:
```bash
.\lead-finder-standalone\.venv\Scripts\python.exe outreach_pipeline.py --report
```

---

## 📊 File Reference

- `leads.csv`: Primary database storing:
  - `business_name,segment,website,email,source_url,status,last_contacted,website_detail`
- `outreach_log.csv`: Transaction log recording every send event.
- `preview_drafts/`: Folder containing audit trails of generated `.txt` email drafts.
- `tests/test_outreach.py`: Comprehensive test suite verifying all 14 rules and constraints.
