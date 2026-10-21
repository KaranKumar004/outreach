---
name: sheetbolt-python-review
description: Code review and quality audit for Sheetbolt Python codebase (outreach pipeline, scrapers, spreadsheet handlers, and email generators). Covers correctness, error handling, type safety, CSV/JSON data integrity, and regression detection.
---

# Sheetbolt Python Code Review

Use this skill whenever modifying, refactoring, or reviewing Python code in the Sheetbolt project (`outreach_pipeline.py`, `lead_finder.py`, email generators, or data scripts).

## Invocation Criteria

Activate when:
- Reviewing diffs or refactorings in `outreach_pipeline.py` or `lead_finder.py`.
- Adding new scraping, lead parsing, or email assembly logic.
- Verifying CSV reading/writing, caching, or rate-limiting routines.
- Pre-merge check on any Sheetbolt Python file.

## Step-by-Step Review Procedure

### 1. Architectural Alignment & Safety Seams
- **Check Pipeline Flow**: Trace lead flow: Raw source -> Scraping/OSM -> Extraction -> Location confirmation -> Personalization generation -> Deduplication check -> Draft generation -> Dispatch.
- **Dry-Run Enforcement**: Confirm that any dispatch or mutation logic strictly respects `--dry-run` or `dry_run=True` flags by default. Real network side-effects must be gated behind explicit production flags.

### 2. Correctness & Data Integrity
- **CSV & JSON State Handling**: Verify that reading and writing to `leads.csv`, `outreach_log.csv`, and JSON caches (`verified_emails_cache.json`, `website_details_cache.json`) handle missing headers, empty strings, and special characters safely.
- **Atomic File Writing**: Ensure file writes to logs and lead files do not truncate or corrupt data on crash.
- **Regex & Parsing Boundaries**: Check regex extractors for catastrophic backtracking and handle malformed HTML / text inputs gracefully.

### 3. Error Handling & Resilience
- **No Swallowed Exceptions**: Disallow empty `except:` or `except Exception: pass`. Ensure specific network/HTTP errors (e.g. `requests.RequestException`, `smtplib.SMTPException`) are caught, logged, and trigger a graceful retry or item quarantine.
- **Logging vs Printing**: Prefer structured logging with severity levels over arbitrary `print()` statements in core pipeline functions.
- **Clean Resource Teardown**: Verify SMTP connections, sessions, and file descriptors are properly closed (using `with` context managers).

### 4. Type Annotations & Signatures
- Check that function signatures have explicit type annotations (`lead: dict[str, Any]`, `dry_run: bool = True -> OutreachResult`).
- Avoid vague variable names; use domain-specific identifiers (`lead_email`, `business_name`, `segment_name`).

## Verification Requirements

1. **Static Syntax & Type Check**: Run `py -m py_compile <file.py>` to guarantee syntax validity.
2. **Regression Test Run**: Execute targeted test suites (`pytest tests/test_outreach.py`) to confirm zero breakages in location filtering, personalization lines, or segment templates.
3. **Diff Minimality**: Verify the proposed diff touches only intended functions without unintended whitespace or formatting churn.
