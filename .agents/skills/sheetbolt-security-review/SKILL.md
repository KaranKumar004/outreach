---
name: sheetbolt-security-review
description: Security audit for Sheetbolt outreach infrastructure. Reviews SMTP credentials, OAuth tokens, email header injection risks, webhook validation, lead data protection, and dry-run safety gates.
---

# Sheetbolt Security Review Runbook

Use this skill when auditing credentials, email dispatch mechanics, scrapers, or sensitive data in Sheetbolt.

## Invocation Criteria

Activate when:
- Adding or modifying SMTP or OAuth credential handling.
- Reviewing `.env`, `.env.example`, or token cache persistence.
- Auditing email generation for header injection vulnerabilities (`\r\n` injection).
- Pre-campaign check to ensure live credentials and real recipients are protected during testing.

## Step-by-Step Security Review Procedure

### 1. Credential & Token Protection
- **Environment Isolation**: Confirm `SMTP_USER`, `SMTP_PASS`, `SMTP_HOST`, `SMTP_PORT`, and OAuth tokens are loaded strictly from `.env` via `os.environ` or `load_env()`.
- **Git Ignore Safeguards**: Verify that `.env`, `.env.local`, `oauth_creds.json`, `jetski-standalone-oauth-token`, `sent_log.json`, and cached tokens are strictly listed in `.gitignore`.
- **Transcript & Log Masking**: Ensure logs, exception dumps, and dry-run prints redact passwords, API tokens, and authorization headers (`Authorization: Bearer <REDACTED>`).

### 2. Email Injection & Transport Security
- **Header Injection Prevention**: Ensure recipient email addresses, subjects, and sender names are validated to contain no carriage returns or newlines (`\r` or `\n`), which could allow SMTP header injection.
- **TLS/SSL Enforcement**: Verify SMTP transport connects over TLS/STARTTLS (`smtp.starttls()`) and verifies host certificates. Never allow insecure fallback to plain text without encryption.
- **HTML Sanitization**: Ensure dynamic lead attributes (business name, owner name, services) injected into HTML email templates are properly escaped using `html.escape()` to prevent HTML/CSS injection.

### 3. Dry-Run & Accidental Send Safety
- **Mandatory Default Guard**: Verify that scripts default to `--dry-run` unless an explicit command-line flag (e.g. `--send-live` or `--production`) is passed with interactive confirmation.
- **Test Address Quarantine**: During development and testing, ensure test recipients are strictly routed to test sinks (e.g., mailhog, dummy addresses, or the developer's verified inbox) and cannot blast real leads.

### 4. Scraper & External Request Safety
- **Request Throttling & User-Agent**: Verify that web scrapers (`lead_finder.py`, OSM lookups) respect rate limits, back off on HTTP 429/503, and set polite User-Agent headers.
- **SSRF Prevention**: Validate target URLs before fetching; restrict protocols to `http` and `https`, and disallow loopback/internal addresses (`localhost`, `127.0.0.1`, `169.254.169.254`).

## Verification Requirements

1. **Secret Leak Audit**: Run automated checks across committed code to confirm zero raw credentials exist in repository tracking.
2. **Safety Gate Audit**: Verify that running `py outreach_pipeline.py` without arguments defaults to dry-run or diagnostic mode without sending a live email.
3. **Template Escape Check**: Run unit test verifying HTML escaping on dirty lead input (`<script>`, `"`, `&`).
