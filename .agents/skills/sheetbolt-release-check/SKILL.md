---
name: sheetbolt-release-check
description: Final pre-flight and pre-release checklist for Sheetbolt outreach runs. Verifies test suites, dry-run simulation, environment variables, lead counts, suppression lists, rate limiters, and log integrity before any live campaign.
---

# Sheetbolt Pre-Release Verification Checklist

Run this skill before kicking off any outreach campaign, deploying updates to the pipeline, or releasing new lead-generation features.

## Invocation Criteria

Activate when:
- Preparing to run a live outreach batch.
- Releasing changes to `outreach_pipeline.py` or email templates.
- Verifying deployment readiness on a new machine or environment.

## Pre-Release Verification Procedure

### 1. Test Suite Verification
- Run the full test suite:
  ```powershell
  py -m pytest tests/test_outreach.py -v
  ```
- **Pass Gate**: 100% pass rate. Zero failed tests, zero skipped critical assertions.

### 2. Environment & Configuration Check
- Validate `.env` configuration:
  - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` are populated.
  - `SITE_URL` and `SAMPLE_DASHBOARD_URL` point to active live assets.
  - `OUTREACH_SENDER_NAME` is configured.
- Confirm `.env` and sensitive token files are strictly excluded by `.gitignore`.

### 3. Dry-Run Batch Simulation
- Run the pipeline in dry-run mode on the current lead batch:
  ```powershell
  py outreach_pipeline.py --dry-run
  ```
- Verify:
  - Subject lines render properly and meet the < 8 words requirement.
  - Dynamic company names and personalizations format cleanly without broken template tags (`{company}` or `None`).
  - Missing personalisation lines are omitted gracefully rather than producing awkward phrasing.
  - Image attachments (logo, sample dashboard) process within maximum file size bounds (<= 180px width, <= 60KB).

### 4. Data & Suppression Integrity
- Verify `leads.csv` contains valid header columns (`email`, `business_name`, `segment`, `city`, `website`).
- Confirm that existing contacts in `outreach_log.csv` are recognized and skipped (zero duplicate sends).
- Confirm suppression lists (unsubscribes, invalid emails) are honored.

### 5. Transport & Rate-Limiting Guard
- Verify rate limiting / sleep intervals between dispatches are active (e.g. 45–90 seconds).
- Verify daily volume cap is configured to avoid mailbox reputation penalties.

## Release Sign-Off Gate

| Item | Status | Verified Evidence |
| :--- | :--- | :--- |
| **Pytest Suite** | [ ] PASS | All tests passing cleanly |
| **Config Audit** | [ ] PASS | Credentials loaded, gitignore intact |
| **Dry-Run Preview** | [ ] PASS | Zero malformed subjects or broken tags |
| **Deduplication Check**| [ ] PASS | All previously contacted leads suppressed |
| **Volume & Rate Guard**| [ ] PASS | Throttling and daily cap enforced |

Do NOT approve a live send unless every gate is marked PASS.
