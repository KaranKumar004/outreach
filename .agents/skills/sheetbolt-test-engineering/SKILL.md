---
name: sheetbolt-test-engineering
description: Test engineering for Sheetbolt outreach automation. Develops and runs targeted pytest suites for lead extraction, location filtering, personalization lines, segment templates, persistence, mock SMTP/Gmail, and retry handling.
---

# Sheetbolt Test Engineering Guide

Use this skill when developing, augmenting, or running tests for the Sheetbolt codebase (`tests/test_outreach.py`).

## Invocation Criteria

Activate when:
- Creating new tests for lead filtering, location confirmation, or segment rules.
- Writing regression tests after fixing an outreach or scraper bug.
- Testing mock SMTP interactions, rate limiters, or duplicate-send prevention logic.
- Verifying changes before deploying or running campaigns.

## Step-by-Step Testing Procedure

### 1. Identify Seams & Incumbent Conventions
- Review `tests/test_outreach.py` to match existing test class conventions (`TestLocationSetting`, `TestPersonalisationLine`, `TestSegmentConfirmation`, `TestCTAAndPrivacy`).
- Use `pytest` with `tmp_path` fixtures for filesystem interactions (`leads.csv`, `outreach_log.csv`).
- Use `unittest.mock` (`patch`, `MagicMock`) for external boundaries (`smtplib.SMTP`, `requests.Session`, `urllib.request`).

### 2. Test Coverage Matrix for Outreach Logic
1. **Location Filtering (`TestLocationSetting`)**:
   - Confirm valid Bengaluru / Bangalore spellings, known tech parks, and pincodes (`560xxx`).
   - Reject leads from out-of-scope cities (e.g., Delhi, Mumbai, international).
   - Verify proper flagging in the output CSV (`rejected_location`).
2. **Personalization Engine (`TestPersonalisationLine`)**:
   - Verify extraction of clean service noun phrases.
   - Assert rejection of slogans, superlatives ("best", "leading", "#1"), and excessively long phrases (>60 chars).
   - Assert complete omission of personalization lines when no genuine service is identified (never hallucinate a review).
3. **Segment & Template Confirmation (`TestSegmentConfirmation`)**:
   - Test segment-specific keywords (`gyms`, `clinics`, `retail`, `agencies`, `accounting`, `manufacturers`, `coaching`).
   - Assert failure and quarantine when segment keywords do not match.
4. **CTA & Privacy Compliance (`TestCTAAndPrivacy`)**:
   - Verify every email template contains the standardized single CTA ("Reply with 'audit' or one messy sheet...").
   - Verify clear unsubscribe/opt-out instructions and contact information in footers.
5. **Persistence & Idempotency**:
   - Test duplicate-send prevention: dispatching to the same email twice must result in a skip on the second attempt.
   - Verify `outreach_log.csv` updates correctly with timestamps, message IDs, and send statuses.

### 3. Execution & Failure Verification
- Run tests using pytest: `py -m pytest tests/test_outreach.py -v`.
- If testing a new feature or fix, verify that the test fails when the feature is disabled or mutated (prove the test catches defects).

## Verification Requirements

- All pytest tests in `tests/test_outreach.py` must pass with zero failures and zero unhandled warnings.
- No live network requests or emails must be transmitted during tests (mock SMTP and mock HTTP sessions).
- Test execution must complete in seconds.
