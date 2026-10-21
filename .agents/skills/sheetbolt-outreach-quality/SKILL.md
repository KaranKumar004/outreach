---
name: sheetbolt-outreach-quality
description: Domain-specific quality audit for Sheetbolt B2B cold outreach. Verifies campaign state management, duplicate-send prevention, email deliverability/SPF/DKIM/DMARC checks, subject line guidelines (<8 words), spam trigger suppression, and opt-out handling.
---

# Sheetbolt Outreach Quality Audit

Use this skill when preparing, validating, or auditing cold-email campaigns, email copy, lead batches, or outreach deliverability in Sheetbolt.

## Invocation Criteria

Activate when:
- Reviewing email templates or proposed copy variations.
- Validating lead datasets before initiating outreach campaigns.
- Auditing suppression lists, follow-up cadences, or duplicate-send guards.
- Diagnosing bounce rates, spam complaints, or reply classification issues.

## Step-by-Step Outreach Quality Audit

### 1. Copy & Compliance Standards
- **Subject Line Discipline**: Subject lines must be benefit-led and strictly under 8 words (e.g., *"Fewer no-shows, one simple dashboard"* or *"Automate client ad reporting in minutes"*). Avoid spam triggers (ALL-CAPS, exclamation marks, "FREE", "Act now", "$$$").
- **Objective Line 1 Personalization**:
  - Personalization must reference real, verifiable offerings extracted from the prospect's public website (e.g., *"With your focus on Structured Finance,"*).
  - Never fake a human review (never write *"I was browsing your website yesterday"* or *"I love what you're doing"*).
  - If no clear offering is found, omit Line 1 completely.
- **The Core Offer**: Clearly state the Sheetbolt fixed-price value proposition: *"I turn messy business data into a simple dashboard or automated report in about 3 days. I offer one free small fix to prove value."*
- **Single Low-Friction CTA**: Every email must conclude with the unified CTA: *"Reply with 'audit' or one messy sheet and I'll send back a clean preview."*
- **Privacy & Opt-Out**: Include polite, direct opt-out language and clear physical/contact identity in footers.

### 2. Deliverability & Technical Configuration
- **DNS Authentication**: Verify sender domain has valid SPF (`v=spf1`), DKIM (`v=DKIM1`), and DMARC (`v=DMARC1; p=quarantine` or `p=reject`) records.
- **Message-ID & In-Reply-To Threading**: Verify follow-up emails properly populate `In-Reply-To` and `References` headers referencing the initial message ID so follow-ups thread correctly in the prospect's inbox.
- **Sender Reputation Throttle**: Ensure daily volume caps and inter-message jitter delays (e.g. 45–90 seconds between sends) are enforced to maintain mailbox reputation.

### 3. Duplicate Prevention & Suppression Checks
- **Outreach Log Check**: Check destination email against `outreach_log.csv` and historical sent archives before dispatching. If an email has received an initial outreach within the cooldown window (e.g. 30 days), skip immediately.
- **Unsubscribe & Bounced Suppression**: Verify that unsubscribes, hard bounces, and existing clients are strictly present in a suppression list and automatically filtered out.
- **Domain-Level Caps**: Do not send to more than 2 distinct contacts at the same company domain within a single week.

## Verification Requirements

1. **Copy Audit**: Run a copy check verifying subject length (< 8 words), presence of unified CTA, and absence of fake-review phrases.
2. **Duplicate Check Simulation**: Run a test batch containing duplicate leads against an existing `outreach_log.csv` fixture; verify 100% duplicate suppression rate.
3. **HTML / Plaintext Parity**: Verify that HTML emails have an accompanying multipart plaintext alternative (`MIMEMultipart('alternative')`).
