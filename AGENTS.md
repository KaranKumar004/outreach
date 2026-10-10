<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# Sheetbolt Development Guidelines

These rules apply specifically to Sheetbolt outreach and automation modules.

1. **Safety First**: All outreach pipeline executions must default to `--dry-run`. Never trigger live emails without explicit confirmation and `--send-live`.
2. **Duplicate Prevention**: Before sending any email, verify that the lead has not already been contacted in `outreach_log.csv`.
3. **Objective Personalization**: Line 1 personalization must be objective and derived from real prospect content. Never fabricate reviews or compliments. Omit line 1 if no clear service is detected.
4. **Subject Lines**: Keep all subject lines strictly under 8 words, benefit-led, with zero spam trigger words.
5. **Credential Isolation**: Keep all credentials in `.env`. Never commit secrets or print them in terminal logs.
6. **Testing Gate**: Always run `py -m pytest tests/test_outreach.py` after editing pipeline logic or email templates.
7. **Use Reusable Skills**:
   - For reviewing pipeline changes: use `/sheetbolt-python-review`.
   - For writing or running outreach tests: use `/sheetbolt-test-engineering`.
   - For auditing credentials and email transport: use `/sheetbolt-security-review`.
   - For checking campaign copy and deliverability: use `/sheetbolt-outreach-quality`.
   - Before any batch release: run `/sheetbolt-release-check`.
