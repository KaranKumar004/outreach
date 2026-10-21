"""
tests/test_outreach.py — Comprehensive test suite for Bengaluru freelance outreach pipeline.

Tests verify:
1. Location setting (ALLOWED_CITIES, neighbourhoods, 560xxx pincode, audit marking rejected_location)
2. Personalisation line (clean service noun phrase under 6 words, no superlatives, "I saw you offer <detail>.")
3. Segment confirmation (accounting, clinics, gyms terms; unclassified excluded)
4. CTA & privacy (unified dummy data CTA; no patient data; no request for client sheets)
5. Sample link ("Here's a sample: <url>"; refuses send if empty; dry-run works)
6. Footer & sender (loaded from .env only; pre-send check against PROTECTED_ACCOUNTS)
7. Word limit (strictly < 90 words across all templates including sample link line)
8. Safety limits (daily cap, warmup mode, sending window, bounce circuit breaker, deduplication, follow-ups)
"""

import os
import sys
import pytest
from datetime import datetime, date, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import outreach_pipeline as op
from outreach_pipeline import (
    normalize_email,
    extract_domain,
    is_valid_email_syntax,
    is_duplicate_lead,
    is_in_sending_window,
    calculate_business_days_between,
    count_words,
    generate_email,
    check_circuit_breaker,
    get_daily_sent_count,
    get_warmup_cap,
    clean_business_name,
    get_greeting,
    extract_website_detail,
    is_clean_service_noun_phrase,
    format_personalisation_line,
    verify_lead_location,
    audit_leads_location,
    confirm_segment_from_text,
    is_chain_business,
    is_excluded_corporate_inbox,
    verify_sender_safety,
    get_rotated_subject,
    SEGMENTS,
    SUBJECT_VARIANTS,
    DAILY_SEND_CAP,
    BOUNCE_RATE_LIMIT,
    IST,
)


@pytest.fixture(autouse=True)
def mock_extract_website_detail(monkeypatch):
    monkeypatch.setattr(op, "extract_website_detail", lambda *args, **kwargs: "")



class TestLocationSetting:
    """Test ALLOWED_CITIES, neighbourhood matching, 560xxx pincodes, and audit logic."""

    def test_location_confirms_bengaluru_and_bangalore(self):
        ok1, _ = verify_lead_location(website_url="https://site.com", address_text="MG Road, Bengaluru", allowed_cities=["bengaluru", "bangalore"])
        assert ok1 is True

        ok2, _ = verify_lead_location(website_url="https://site.com", address_text="Brigade Road, Bangalore", allowed_cities=["bengaluru", "bangalore"])
        assert ok2 is True

    def test_location_confirms_known_neighbourhoods(self):
        ok, reason = verify_lead_location(website_url="https://site.com", address_text="100 Feet Road, Indiranagar", allowed_cities=["bengaluru"])
        assert ok is True
        assert "indiranagar" in reason.lower()

        ok_kor, _ = verify_lead_location(website_url="https://site.com", address_text="5th Block, Koramangala", allowed_cities=["bengaluru"])
        assert ok_kor is True

    def test_location_confirms_560_pincode(self):
        ok, reason = verify_lead_location(website_url="https://site.com", address_text="Karnataka 560038, India", allowed_cities=["bengaluru"])
        assert ok is True
        assert "560038" in reason

    def test_location_rejects_other_cities(self):
        ok, reason = verify_lead_location(website_url="https://site.com", address_text="Fateh Sagar, Udaipur, Rajasthan 313001", allowed_cities=["bengaluru", "bangalore"])
        assert ok is False
        assert "not confirmed" in reason.lower()

    def test_empty_allowed_cities_accepts_any(self):
        ok, _ = verify_lead_location(website_url="https://site.com", address_text="Connaught Place, New Delhi", allowed_cities=[])
        assert ok is True

    def test_audit_marks_rejected_location_in_csv(self, tmp_path):
        csv_file = tmp_path / "leads.csv"
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write("business_name,segment,website,email,source_url,status,last_contacted,website_detail\n")
            f.write("Good Clinic,clinics,https://good.in,info@good.in,Indiranagar Bengaluru,new,,\n")
            f.write("Udaipur Gym,gyms,https://gym.in,info@gym.in,Udaipur Rajasthan 313001,new,,\n")

        total, updated = audit_leads_location(str(csv_file))
        assert total == 2
        assert updated == 1

        leads = op.load_leads(str(csv_file))
        assert leads[0]["status"] == "new"
        assert leads[1]["status"] == "rejected_location"


class TestPersonalisationLine:
    """Test clean service/specialty noun phrases under 6 words without superlatives."""

    def test_clean_service_noun_phrase_valid(self):
        assert is_clean_service_noun_phrase("dental implants and root canals") is True
        assert is_clean_service_noun_phrase("structured finance") is True
        assert is_clean_service_noun_phrase("crossfit and strength training") is True

    def test_clean_service_noun_phrase_rejects_superlatives_and_slogans(self):
        assert is_clean_service_noun_phrase("They Are Always Best") is False
        assert is_clean_service_noun_phrase("Best Gym in Udaipur") is False
        assert is_clean_service_noun_phrase("No. 1 dental clinic") is False
        assert is_clean_service_noun_phrase("Leading dental care") is False
        assert is_clean_service_noun_phrase("top rated coaching") is False

    def test_clean_service_noun_phrase_rejects_long_phrases(self):
        # 6 or more words
        assert is_clean_service_noun_phrase("one two three four five six") is False

    def test_format_personalisation_line_generates_full_sentence(self):
        line = format_personalisation_line("dental implants and root canals")
        assert line == "I saw you offer dental implants and root canals."

    def test_format_personalisation_line_omitted_when_invalid(self):
        assert format_personalisation_line("They Are Always Best") == ""
        assert format_personalisation_line("") == ""


class TestSegmentConfirmation:
    """Test homepage text confirmation for segments."""

    def test_accounting_confirmed_with_keywords(self):
        text = "Welcome to our firm. We handle GST filings, tax audits, and chartered accountant services."
        ok, terms = confirm_segment_from_text("accounting", text)
        assert ok is True
        assert "gst" in terms

    def test_clinics_confirmed_with_keywords(self):
        text = "Our dental clinic provides comprehensive doctor consultations and diagnostics."
        ok, terms = confirm_segment_from_text("clinics", text)
        assert ok is True
        assert "dental" in terms or "clinic" in terms

    def test_gyms_confirmed_with_keywords(self):
        text = "Join our fitness centre for crossfit, strength training, and yoga classes."
        ok, terms = confirm_segment_from_text("gyms", text)
        assert ok is True
        assert "fitness" in terms or "crossfit" in terms

    def test_segment_fails_when_keywords_missing(self):
        text = "We sell handmade wooden furniture and interior home decor."
        ok, terms = confirm_segment_from_text("clinics", text)
        assert ok is False
        assert len(terms) == 0


class TestCTAAndPrivacy:
    """Test unified CTA and removal of all client data requests."""

    def test_unified_cta_in_all_templates(self):
        for seg in SEGMENTS:
            lead = {"business_name": "Test Co", "segment": seg, "website": "https://test.co", "email": "info@test.co"}
            _, body = generate_email(lead)
            if seg in op.NEW_SEGMENT_TEMPLATES:
                assert op.OFFER_TEXT in body
            else:
                assert "Want me to make a free sample like it for your business, using dummy data?" in body

    def test_no_data_or_sheets_requested_from_recipient(self):
        for seg in SEGMENTS:
            lead = {"business_name": "Test Co", "segment": seg, "website": "https://test.co", "email": "info@test.co"}
            _, body = generate_email(lead)
            assert "send me your" not in body.lower()
            assert "send me an anonymised" not in body.lower()
            assert "patient data" not in body.lower()
            assert "patient" not in body.lower()


class TestSampleLink:
    """Test inclusion of SAMPLE_DASHBOARD_URL and send safety."""

    def test_sample_link_included_in_body(self, monkeypatch):
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        lead = {"business_name": "Test Co", "segment": "gyms", "website": "https://test.co", "email": "info@test.co"}
        _, body = generate_email(lead)
        assert "Here's an example of what I build: https://sheetboltanalytics.netlify.app/#top" in body

    def test_dry_run_works_even_if_sample_url_empty(self, monkeypatch):
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "")
        lead = {"business_name": "Test Co", "segment": "gyms", "website": "https://test.co", "email": "info@test.co"}
        _, body = generate_email(lead)

        assert op.UNIFIED_CTA in body


class TestFooterAndSender:
    """Test sender, reply-to, and support address read strictly from .env without hardcoding."""

    def test_refuses_when_sender_or_support_missing(self, monkeypatch):
        monkeypatch.setenv("SMTP_USER", "")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        with pytest.raises(ValueError):
            verify_sender_safety()

    def test_refuses_when_sender_in_protected_accounts(self, monkeypatch):
        monkeypatch.setenv("SMTP_USER", "personal@example.invalid")
        monkeypatch.setenv("SMTP_REPLY_TO", "outreach@example.invalid")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "outreach@example.invalid")
        monkeypatch.setenv("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("PROTECTED_ACCOUNTS", "personal@example.invalid")
        monkeypatch.setattr(op, "PROTECTED_ACCOUNTS", ["personal@example.invalid"])

        with pytest.raises(PermissionError) as excinfo:
            verify_sender_safety()
        assert "PROTECTED_ACCOUNTS" in str(excinfo.value)

    def test_footer_uses_env_values(self, monkeypatch):
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "support@example.invalid")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        lead = {"business_name": "Test Co", "segment": "gyms", "website": "https://test.co", "email": "info@test.co"}
        _, body = generate_email(lead)
        assert "Best,\nKaran\nSheetbolt · Automate the mess" in body
        assert "https://sheetboltanalytics.netlify.app" in body
        assert "Support: support@example.invalid" in body


class TestWordLimit:
    """Test that all templates have main body strictly under 90 words and subject under 8 words."""

    @pytest.mark.parametrize("segment", SEGMENTS)
    def test_all_segments_under_90_words(self, segment, monkeypatch):
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "support@example.invalid")

        # Test with personalisation line
        lead_with_detail = {
            "business_name": "Vibha Dental Care",
            "segment": segment,
            "website": "https://vibhadental.com",
            "email": "info@vibhadental.com",
            "website_detail": "cosmetic dentistry and dental implants",
        }
        subj1, body1 = generate_email(lead_with_detail)
        body1_main = body1.split("Best,\n")[0].strip()
        words1 = count_words(body1_main)
        assert words1 < 90, f"Segment '{segment}' with detail has {words1} words (must be < 90)"
        assert count_words(subj1) < 8

        # Test without personalisation line
        lead_no_detail = {
            "business_name": "Vibha Dental Care",
            "segment": segment,
            "website": "https://vibhadental.com",
            "email": "info@vibhadental.com",
            "website_detail": "",
        }
        subj2, body2 = generate_email(lead_no_detail)
        body2_main = body2.split("Best,\n")[0].strip()
        words2 = count_words(body2_main)
        assert words2 < 90, f"Segment '{segment}' without detail has {words2} words (must be < 90)"
        assert count_words(subj2) < 8

    def test_followup_under_90_words(self, monkeypatch):
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "support@example.invalid")
        lead = {"business_name": "Test Co", "segment": "gyms", "website": "https://test.co", "email": "info@test.co"}
        subj, body = generate_email(lead, email_type="followup")
        body_main = body.split("Best,\n")[0].strip()
        words = count_words(body_main)
        assert words < 90
        assert count_words(subj) < 8


class TestBusinessNameCleaning:
    """Test cleaning extracted business names and greeting fallback."""

    def test_generic_name_falls_back_to_hi_there(self):
        assert clean_business_name("Dental Clinic") == ""
        assert get_greeting("Dental Clinic") == "Hi there,"
        assert get_greeting("Clinic") == "Hi there,"
        assert get_greeting("Gym") == "Hi there,"

    def test_specific_name_greets_team(self):
        assert clean_business_name("Vibha Dental Care") == "Vibha Dental Care"
        assert get_greeting("Vibha Dental Care") == "Hi Vibha Dental Care team,"


class TestBenefitLedSubjects:
    """Test rotated benefit-led subjects under 8 words."""

    def test_all_variants_under_8_words(self):
        for seg, variants in SUBJECT_VARIANTS.items():
            for v in variants:
                assert count_words(v) < 8

    def test_rotation_deterministic_by_email(self):
        s1 = get_rotated_subject("clinics", "a@test.com")
        s2 = get_rotated_subject("clinics", "b@test.com")
        s3 = get_rotated_subject("clinics", "c@test.com")
        assert len({s1, s2, s3}) >= 2


class TestDeduplication:
    def test_dedupe_by_email_and_domain(self):
        existing = [{"email": "contact@cultfit.in", "website": "https://cultfit.in"}]
        assert is_duplicate_lead("contact@cultfit.in", "https://other.com", existing) is True
        assert is_duplicate_lead("other@cultfit.in", "https://cultfit.in", existing) is True
        assert is_duplicate_lead("unique@fresh.in", "https://fresh.in", existing) is False


class TestSendingWindow:
    def test_window_allowed_weekdays_10_to_17(self):
        dt_ok = datetime(2026, 9, 21, 14, 0, tzinfo=IST)
        allowed, _ = is_in_sending_window(dt_ok)
        assert allowed is True

    def test_window_blocked_weekends(self):
        dt_sat = datetime(2026, 9, 26, 12, 0, tzinfo=IST)
        allowed, msg = is_in_sending_window(dt_sat)
        assert allowed is False
        assert "weekend" in msg.lower()


class TestBounceCircuitBreaker:
    def test_circuit_breaker_under_20_sends(self, tmp_path):
        log_file = tmp_path / "outreach_log.csv"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            for i in range(8):
                f.write(f"2026-09-24T11:00:00+05:30,u{i}@test.com,Biz{i},gyms,initial,Test,sent,\n")
            f.write("2026-09-24T11:30:00+05:30,bad1@test.com,Biz1,gyms,initial,Test,bounced,550\n")
            f.write("2026-09-24T11:31:00+05:30,bad2@test.com,Biz2,gyms,initial,Test,bounced,550\n")

        tripped, _, b_cnt, _, _ = check_circuit_breaker(str(log_file))
        assert tripped is False
        assert b_cnt == 2

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-09-24T11:32:00+05:30,bad3@test.com,Biz3,gyms,initial,Test,bounced,550\n")

        tripped, _, b_cnt, _, reason = check_circuit_breaker(str(log_file))
        assert tripped is True
        assert b_cnt == 3
        assert "3 bounces recorded" in reason


class TestWarmupMode:
    def test_warmup_caps(self, tmp_path):
        log_file = tmp_path / "outreach_log.csv"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            f.write("2026-09-24T11:00:00+05:30,u1@test.com,Biz1,gyms,initial,Test,sent,\n")

        cap1, _, _ = get_warmup_cap(str(log_file), target_date=date(2026, 9, 24))
        assert cap1 == 5

        cap2, _, _ = get_warmup_cap(str(log_file), target_date=date(2026, 10, 2))
        assert cap2 == 10

        cap3, _, _ = get_warmup_cap(str(log_file), target_date=date(2026, 10, 15))
        assert cap3 == min(op.DAILY_SEND_CAP, op.HARD_DAILY_CAP_LIMIT)


class TestDomainMatchingAndReviewFlagging:
    """Test domain matching and review_flagged rules."""

    def test_exact_domain_match_passes(self):
        flagged, _ = op.check_lead_domain_match("info@stevesgym.com", "https://stevesgym.com/")
        assert flagged is False

    def test_subdomain_match_passes(self):
        flagged, _ = op.check_lead_domain_match("support@app.stevesgym.com", "https://stevesgym.com/")
        assert flagged is False

    def test_root_domain_slug_match_passes(self):
        flagged, _ = op.check_lead_domain_match("salesmmt@acemicromatic.com", "https://www.acemicromatic.net/")
        assert flagged is False

    def test_suspicious_keywords_flagged(self):
        flagged, reason = op.check_lead_domain_match("sales@test.infycons.com", "https://infycons.com/")
        assert flagged is True
        assert "test" in reason

        flagged2, reason2 = op.check_lead_domain_match("demo@mybiz.com", "https://mybiz.com/")
        assert flagged2 is True
        assert "demo" in reason2

    def test_mall_directory_flagged(self):
        flagged, reason = op.check_lead_domain_match("digitalmarketing@garudamall.net", "https://garudamall.in/")
        assert flagged is True
        assert "Mall directory" in reason

    def test_free_webmail_mismatch_flagged(self):
        flagged, reason = op.check_lead_domain_match("lotusdiagnostic@gmail.com", "https://lotusdiagnostic.com/")
        assert flagged is True
        assert "Free webmail" in reason

    def test_unrelated_domain_mismatch_flagged(self):
        flagged, reason = op.check_lead_domain_match("care@nnnow.com", "https://global.tommy.com/")
        assert flagged is True
        assert "Domain mismatch" in reason

    def test_audit_marks_review_flagged_in_csv(self, tmp_path):
        csv_file = tmp_path / "leads.csv"
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write("business_name,segment,website,email,source_url,status,last_contacted,website_detail\n")
            f.write("Clean Gym,gyms,https://cleangym.com,info@cleangym.com,src,new,,\n")
            f.write("Mall Shop,retail,https://mallshop.in,contact@garudamall.net,src,new,,\n")
            f.write("Gmail Clinic,clinics,https://myclinic.com,doc@gmail.com,src,new,,\n")

        flagged = op.audit_leads_domain_match(str(csv_file))
        assert len(flagged) == 2

        updated_leads = op.load_leads(str(csv_file))
        statuses = {l["business_name"]: l["status"] for l in updated_leads}
        assert statuses["Clean Gym"] == "new"
        assert statuses["Mall Shop"] == "review_flagged"
        assert statuses["Gmail Clinic"] == "review_flagged"

    def test_name_vs_domain_ace_designers_flagged(self):
        flagged, reason = op.check_lead_name_vs_domain("Ace Designers", "salesmmt@acemicromatic.com", "https://www.acemicromatic.net/")
        assert flagged is True
        assert "business name does not match domain" in reason

    def test_name_vs_domain_steves_gym_not_flagged(self):
        flagged, _ = op.check_lead_name_vs_domain("Steve's Gym", "info@stevesgym.com", "https://stevesgym.com/")
        assert flagged is False

        # Even with empty website URL, 'steve' matches domain 'stevesgym.com'
        flagged_no_site, _ = op.check_lead_name_vs_domain("Steve's Gym", "info@stevesgym.com", "")
        assert flagged_no_site is False



class TestSheetboltRebrandingRules:
    """Test suite covering Sheetbolt rebranding, safety guards, HTML formatting, and images."""

    def test_sender_identity_reads_from_env_without_hardcoding(self, monkeypatch):
        test_sender = os.environ.get("SMTP_USER", "sheetbolt.analytics@example.invalid")
        test_reply = os.environ.get("SMTP_REPLY_TO", "sheetbolt.analytics@example.invalid")
        test_support = os.environ.get("OUTREACH_SUPPORT_EMAIL", "sheetbolt.analytics@example.invalid")
        monkeypatch.setenv("SMTP_USER", test_sender)
        monkeypatch.setenv("SMTP_REPLY_TO", test_reply)
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", test_support)
        monkeypatch.setenv("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")

        # verify_sender_safety should pass without raising
        verify_sender_safety(check_urls_live=False)

    def test_protected_account_refuses_send(self, monkeypatch):
        # Read protected account from env or configure dynamic test protected account
        raw_protected = os.environ.get("PROTECTED_ACCOUNTS", "protected_test@example.invalid")
        target_account = raw_protected.split(",")[0].strip()

        monkeypatch.setenv("SMTP_USER", target_account)
        monkeypatch.setenv("SMTP_REPLY_TO", "other@example.invalid")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "other@example.invalid")
        monkeypatch.setenv("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("PROTECTED_ACCOUNTS", target_account)

        with pytest.raises(PermissionError) as excinfo:
            verify_sender_safety(check_urls_live=False)
        assert "PROTECTED_ACCOUNTS" in str(excinfo.value)

    def test_all_templates_and_followup_signature_and_footer(self, monkeypatch):
        site_url = "https://sheetboltanalytics.netlify.app"
        support_email = "support@example.invalid"
        monkeypatch.setenv("SITE_URL", site_url)
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", support_email)
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")

        expected_sig = (
            "Best,\n"
            "Karan\n"
            "Sheetbolt · Automate the mess\n"
            f"{site_url}\n"
            "--\n"
            f"Reply STOP and I won't email again. Support: {support_email}"
        )

        for seg in SEGMENTS:
            lead = {"business_name": "Test Clinic", "segment": seg, "website": "https://test.in", "website_detail": "health services", "email": "info@test.in"}
            _, body = generate_email(lead, email_type="initial")
            assert expected_sig in body, f"Signature missing or incorrect in segment {seg}"

        lead = {"business_name": "Test Clinic", "segment": "clinics", "website": "https://test.in", "website_detail": "health services", "email": "info@test.in"}
        _, followup_body = generate_email(lead, email_type="followup")
        assert expected_sig in followup_body, "Signature missing or incorrect in followup"

    def test_sample_and_site_url_safety_guards(self, monkeypatch):
        monkeypatch.setenv("SMTP_USER", "sender@example.invalid")
        monkeypatch.setenv("SMTP_REPLY_TO", "sender@example.invalid")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "support@example.invalid")
        monkeypatch.setenv("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
        monkeypatch.setenv("PROTECTED_ACCOUNTS", "protected@example.invalid")

        # 1. Refuse if SAMPLE_DASHBOARD_URL is empty
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        with pytest.raises(ValueError) as excinfo:
            verify_sender_safety(check_urls_live=False)
        assert "SAMPLE_DASHBOARD_URL" in str(excinfo.value)

        # 2. Refuse if SAMPLE_DASHBOARD_URL contains leadpilot-dashboards.vercel.app
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://leadpilot-dashboards.vercel.app/demo")
        with pytest.raises(ValueError) as excinfo:
            verify_sender_safety(check_urls_live=False)
        assert "leadpilot-dashboards.vercel.app" in str(excinfo.value)

        # 3. Refuse if SITE_URL is empty
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("SITE_URL", "")
        with pytest.raises(ValueError) as excinfo:
            verify_sender_safety(check_urls_live=False)
        assert "SITE_URL" in str(excinfo.value)

    def test_no_sheetbolt_com_in_templates_env_or_drafts(self, monkeypatch):
        # 1. Check env files
        for env_file in [".env.local", ".env.example"]:
            if os.path.exists(env_file):
                with open(env_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    assert "sheetbolt.com" not in content, f"'sheetbolt.com' found in {env_file}"

        # 2. Check generated drafts across all segments and followup
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "sheetbolt.analytics@gmail.com")

        for seg in SEGMENTS:
            lead = {"business_name": "Test Co", "segment": seg, "website": "https://test.co", "website_detail": "health services", "email": "info@test.co"}
            _, text_body = generate_email(lead, email_type="initial")
            assert "sheetbolt.com" not in text_body, f"'sheetbolt.com' found in initial {seg} draft"

            html_body = op.generate_html_email(lead, email_type="initial")
            assert "sheetbolt.com" not in html_body, f"'sheetbolt.com' found in HTML {seg} draft"

        lead = {"business_name": "Test Co", "segment": "gyms", "website": "https://test.co", "website_detail": "health services", "email": "info@test.co"}
        _, followup_text = generate_email(lead, email_type="followup")
        assert "sheetbolt.com" not in followup_text
        followup_html = op.generate_html_email(lead, email_type="followup")
        assert "sheetbolt.com" not in followup_html

    def test_live_url_check_in_verify_sender_safety(self, monkeypatch):
        monkeypatch.setenv("SMTP_USER", "sender@example.invalid")
        monkeypatch.setenv("SMTP_REPLY_TO", "sender@example.invalid")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "support@example.invalid")
        monkeypatch.setenv("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("PROTECTED_ACCOUNTS", "protected@example.invalid")

        class MockResponse:
            def __init__(self, status_code=200):
                self.status_code = status_code

        # Case A: Both return 200 -> Success
        def mock_get_200(url, **kwargs):
            return MockResponse(200)

        monkeypatch.setattr(op.requests, "get", mock_get_200)
        verify_sender_safety(check_urls_live=True)

        # Case B: SITE_URL returns 404 -> ConnectionError
        def mock_get_site_404(url, **kwargs):
            if "top" in url:
                return MockResponse(200)
            return MockResponse(404)

        monkeypatch.setattr(op.requests, "get", mock_get_site_404)
        with pytest.raises(ConnectionError) as excinfo:
            verify_sender_safety(check_urls_live=True)
        assert "SITE_URL" in str(excinfo.value)

        # Case C: SAMPLE_DASHBOARD_URL returns 500 -> ConnectionError
        def mock_get_sample_500(url, **kwargs):
            if "#top" in url or url.endswith("/#top"):
                return MockResponse(500)
            return MockResponse(200)

        monkeypatch.setattr(op.requests, "get", mock_get_sample_500)
        with pytest.raises(ConnectionError) as excinfo:
            verify_sender_safety(check_urls_live=True)
        assert "SAMPLE_DASHBOARD_URL" in str(excinfo.value)

    def test_warmup_cap_ignores_test_sends(self, tmp_path):
        log_file = tmp_path / "outreach_log.csv"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            f.write("2026-09-01T10:00:00+05:30,test@test.com,Biz,clinics,test_send,Subj,test_sent,\n")
            f.write("2026-09-01T10:05:00+05:30,test2@test.com,Biz2,gyms,dry_run,Subj,dry_run,\n")

        cap, week, desc = get_warmup_cap(str(log_file), target_date=date(2026, 9, 28))
        assert cap == 5
        assert week == 1
        assert "no prior sends" in desc.lower()

    def test_html_email_max_two_images_and_followup_rules(self):
        lead = {"business_name": "Test Clinic", "segment": "clinics", "website": "https://test.in", "email": "info@test.in"}

        # 1. Initial email with 2 images passes
        html_init = op.generate_html_email(lead, email_type="initial", cid_logo="sheetbolt_logo", cid_dashboard="sample_dashboard")
        assert "cid:sheetbolt_logo" in html_init
        assert "cid:sample_dashboard" in html_init
        assert "alt=\"Sheetbolt logo\"" in html_init
        assert "alt=\"Sample sales dashboard built on dummy data\"" in html_init

        # 2. More than 2 images raises ValueError
        with pytest.raises(ValueError) as exc:
            op.generate_html_email(lead, email_type="initial", cid_logo="logo", cid_dashboard="dash", extra_images=["extra_img"])
        assert "maximum allowed is 2" in str(exc.value)

        # 3. Followup email carries logo only, skips dashboard
        html_followup = op.generate_html_email(lead, email_type="followup", cid_logo="sheetbolt_logo", cid_dashboard=None)
        assert "cid:sheetbolt_logo" in html_followup
        assert "cid:sample_dashboard" not in html_followup

    def test_email_images_toggle(self, monkeypatch):
        monkeypatch.setenv("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
        monkeypatch.setenv("SMTP_USER", "sender@example.invalid")
        monkeypatch.setenv("SMTP_REPLY_TO", "sender@example.invalid")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "support@example.invalid")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("SMTP_PASS", "mock-pass")

        sent_messages = []

        class MockSMTP:
            def __init__(self, *args, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def ehlo(self):
                pass
            def starttls(self):
                pass
            def login(self, u, p):
                pass
            def send_message(self, msg):
                sent_messages.append(msg)

        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTP)

        lead = {"business_name": "Test Clinic", "segment": "clinics", "website": "https://test.in", "email": "lead@test.in"}
        subj, body = generate_email(lead)

        # When EMAIL_IMAGES = "off" -> Plain-text only
        monkeypatch.setenv("EMAIL_IMAGES", "off")
        sent_messages.clear()
        op.send_smtp_email("lead@test.in", subj, body, lead=lead, check_urls_live=False)
        assert len(sent_messages) == 1
        assert sent_messages[0].get_content_type() == "text/plain"

        # When EMAIL_IMAGES = "on" -> Multipart with HTML
        monkeypatch.setenv("EMAIL_IMAGES", "on")
        sent_messages.clear()
        op.send_smtp_email("lead@test.in", subj, body, lead=lead, check_urls_live=False)
        assert len(sent_messages) == 1
        assert "multipart" in sent_messages[0].get_content_type()

    def test_missing_image_file_does_not_fail(self, tmp_path, monkeypatch):
        # Point EMAIL_ASSETS_DIR to an empty temp dir
        empty_assets = tmp_path / "empty_assets"
        empty_assets.mkdir()
        monkeypatch.setattr(op, "EMAIL_ASSETS_DIR", str(empty_assets))
        monkeypatch.setattr(op, "PROCESSED_ASSETS_DIR", str(empty_assets / "processed"))

        img = op.get_processed_image("non_existent_logo.png", max_width=180)
        assert img is None

        # generate_html_email should succeed without failing
        lead = {"business_name": "Test Clinic", "segment": "clinics", "website": "https://test.in", "email": "lead@test.in"}
        html = op.generate_html_email(lead, email_type="initial", cid_logo=None, cid_dashboard=None)
        assert "<html" in html
        assert "Sheetbolt" in html


class TestRefinedScopeAndClassification:
    """Test refined service scope, accounting classification, name cleaning, and blocked inboxes."""

    def test_forbidden_service_words_rejected(self):
        forbidden = ["reminder", "sms", "whatsapp", "chatbot"]
        # 1. Check all subject variants
        for seg, variants in op.SUBJECT_VARIANTS.items():
            for v in variants:
                for bad in forbidden:
                    assert bad not in v.lower(), f"Forbidden word '{bad}' found in {seg} subject: '{v}'"

        for v in op.FOLLOWUP_SUBJECT_VARIANTS:
            for bad in forbidden:
                assert bad not in v.lower(), f"Forbidden word '{bad}' found in followup subject: '{v}'"

        # 2. Check all template bodies
        for seg, copy in op.SEGMENT_COPY.items():
            combined = f"{copy['problem']} {copy['offer']}".lower()
            for bad in forbidden:
                assert bad not in combined, f"Forbidden word '{bad}' found in {seg} template copy"

        # 3. Check generated text and HTML drafts
        for seg in op.SEGMENTS:
            lead = {"business_name": "Test Co", "segment": seg, "website": "https://test.co", "website_detail": "quality service", "email": "info@test.co"}
            _, text_body = op.generate_email(lead, email_type="initial")
            for bad in forbidden:
                assert bad not in text_body.lower(), f"Forbidden word '{bad}' found in initial text draft for {seg}"

            html_body = op.generate_html_email(lead, email_type="initial")
            for bad in forbidden:
                assert bad not in html_body.lower(), f"Forbidden word '{bad}' found in initial HTML draft for {seg}"

        lead = {"business_name": "Test Co", "segment": "clinics", "website": "https://test.co", "website_detail": "quality service", "email": "info@test.co"}
        _, followup_text = op.generate_email(lead, email_type="followup")
        for bad in forbidden:
            assert bad not in followup_text.lower(), f"Forbidden word '{bad}' found in followup text draft"

        followup_html = op.generate_html_email(lead, email_type="followup")
        for bad in forbidden:
            assert bad not in followup_html.lower(), f"Forbidden word '{bad}' found in followup HTML draft"

    def test_clinic_subject_variant_contains_fewer_noshows(self):
        assert "Fewer no-shows, one simple dashboard" in op.SUBJECT_VARIANTS["clinics"]

    def test_accounting_small_ca_firm_with_new_ventures_stays_accounting(self):
        # A small CA firm mentioning "new ventures" stays accounting
        text = "We are a CA firm handling GST, tax filing and audit for new ventures in Bengaluru."
        ok, terms = op.confirm_segment_from_text("accounting", text)
        assert ok is True
        assert any(t in terms for t in ["gst", "tax", "audit", "ca firm"])

    def test_accounting_ca_meaning_california_does_not_count(self):
        # "CA" meaning California does not count
        text = "Headquartered in San Francisco, CA. We provide premier cloud infrastructure."
        ok, terms = op.confirm_segment_from_text("accounting", text)
        assert ok is False

    def test_accounting_raintree_partners_becomes_unclassified(self):
        # Raintree Partners still becomes unclassified
        text = "Raintree Partners advises clients on structured finance, debt syndication, and private equity deals."
        ok, terms = op.confirm_segment_from_text("accounting", text)
        assert ok is False

    def test_accounting_disqualifier_overridden_by_two_or_more_strong_terms(self):
        # A disqualifying term makes a lead unclassified only if fewer than 2 distinct strong accounting terms appear
        # Case A: 2 distinct strong terms + venture capital -> Stays accounting
        text_strong = "Our chartered accountant practice handles GST filings and statutory audit for venture capital backed companies."
        ok1, terms1 = op.confirm_segment_from_text("accounting", text_strong)
        assert ok1 is True

        # Case B: 1 strong term + venture capital -> Disqualified
        text_weak = "We advise venture capital funds on tax strategies."
        ok2, terms2 = op.confirm_segment_from_text("accounting", text_weak)
        assert ok2 is False

    def test_business_name_cleaning_saartha_labs(self):
        assert op.clean_business_name("Saartha Labs Private Labs") == "Saartha Labs"
        assert op.get_greeting("Saartha Labs Private Labs") == "Hi Saartha Labs team,"

    def test_business_name_cleaning_corporate_suffixes(self):
        cases = [
            ("Sirius Embedded Software Private Limited", "Sirius Embedded Software", "Hi Sirius Embedded Software team,"),
            ("emids Technologies Pvt Ltd", "emids Technologies", "Hi emids Technologies team,"),
            ("Acme Services Pvt. Ltd.", "Acme Services", "Hi Acme Services team,"),
            ("Beta Ventures LLP", "Beta Ventures", "Hi Beta Ventures team,"),
            ("Gamma Labs Inc.", "Gamma Labs", "Hi Gamma Labs team,"),
            ("Delta Analytics Private", "Delta Analytics", "Hi Delta Analytics team,"),
        ]
        for raw, expected_clean, expected_greeting in cases:
            cleaned = op.clean_business_name(raw)
            assert cleaned == expected_clean, f"Failed for raw '{raw}': got '{cleaned}', expected '{expected_clean}'"
            assert op.get_greeting(raw) == expected_greeting

    def test_business_name_cleaning_generic_fallback(self):
        assert op.clean_business_name("Private Limited") == ""
        assert op.get_greeting("Private Limited") == "Hi there,"
        assert op.clean_business_name("Dental Clinic") == ""
        assert op.get_greeting("Dental Clinic") == "Hi there,"

    def test_blocked_inboxes_marked_review_flagged(self):
        blocked_emails = [
            ("help@mustardfashion.com", "https://www.mustardfashion.com/"),
            ("care@andindia.com", "https://www.andindia.com/"),
            ("orders@brand.in", "https://brand.in/"),
            ("returns@store.com", "https://store.com/"),
            ("feedback@company.in", "https://company.in/"),
            ("contactus@himalayawellness.com", "https://www.himalayawellness.com/"),
        ]
        for em, site in blocked_emails:
            flagged, reason = op.check_lead_domain_match(em, site)
            assert flagged is True
            assert "Blocked corporate/generic inbox prefix" in reason

    def test_chain_blocklist_national_brands(self):
        national_brands = [
            ("Chumbak", "https://chumbak.com", "info@chumbak.com"),
            ("Superkicks", "https://superkicks.in", "info@superkicks.in"),
            ("Global Desi", "https://globaldesi.in", "info@globaldesi.in"),
            ("AND", "https://andindia.com", "care@andindia.com"),
            ("Ancestry", "https://theancestrystore.in", "info@theancestrystore.in"),
            ("Cashfree Payments", "https://cashfree.com", "info@cashfree.com"),
            ("Mustard", "https://mustardfashion.com", "info@mustardfashion.com"),
            ("Puma", "https://puma.com", "info@puma.com"),
            ("Westside", "https://westside.com", "info@westside.com"),
        ]
        for name, site, em in national_brands:
            assert op.is_chain_business(name, site, em) is True, f"Failed to detect {name} as chain"

        # Ensure no false positive on 'and' in legitimate boutique names
        assert op.is_chain_business("the Studio by Copper + Cloves", "https://copperandcloves.com", "info@copperandcloves.com") is False
        assert op.is_chain_business("The Registry of Sarees", "https://theregistryofsarees.com", "contact@theregistryofsarees.com") is False

    def test_review_flagged_domain_mismatch_and_keywords(self):
        # 1. Free webmail vs own website
        f1, r1 = op.check_lead_domain_match("drkarthik@gmail.com", "https://vibhadental.com")
        assert f1 is True
        assert "Free webmail" in r1

        # 2. Suspicious keywords (test, staging, demo, noreply)
        f2, r2 = op.check_lead_domain_match("sales@test.infycons.com", "https://infycons.com")
        assert f2 is True
        assert "contains 'test'" in r2

        f3, r3 = op.check_lead_domain_match("noreply@company.com", "https://company.com")
        assert f3 is True
        assert "contains 'noreply'" in r3

        # 3. Legitimate match passes
        f4, _ = op.check_lead_domain_match("info@stevesgym.com", "https://stevesgym.com")
        assert f4 is False


class TestPersonalisationOffAndNewBodyRules:
    """Test Personalisation Off, Body Structure, Greeting Rules, Coaching Template, and Unclassified Exclusion."""

    def test_no_i_saw_you_offer_in_any_draft(self, monkeypatch):
        monkeypatch.setenv("PERSONALISATION", "off")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "sheetbolt.analytics@gmail.com")

        for seg in op.SEGMENTS:
            lead = {
                "business_name": "Test Co",
                "segment": seg,
                "website": "https://test.co",
                "email": "info@test.co",
                "website_detail": "dental implants and teeth cleaning",
            }
            _, text_body = op.generate_email(lead, email_type="initial")
            assert "i saw you offer" not in text_body.lower(), f"'I saw you offer' found in {seg} text draft"

            html_body = op.generate_html_email(lead, email_type="initial")
            assert "i saw you offer" not in html_body.lower(), f"'I saw you offer' found in {seg} HTML draft"

        lead = {"business_name": "Test Co", "segment": "gyms", "website": "https://test.co", "email": "info@test.co", "website_detail": "crossfit workouts"}
        _, followup_text = op.generate_email(lead, email_type="followup")
        assert "i saw you offer" not in followup_text.lower()
        followup_html = op.generate_html_email(lead, email_type="followup")
        assert "i saw you offer" not in followup_html.lower()

    def test_personalisation_off_skips_detail_extraction(self, monkeypatch):
        monkeypatch.setenv("PERSONALISATION", "off")
        detail_off = op._real_extract_website_detail("https://example.com", html="<html><body>specializing in cosmetic surgery</body></html>")
        assert detail_off == ""

        monkeypatch.setenv("PERSONALISATION", "on")
        detail_on = op._real_extract_website_detail("https://example.com", html="<p>specializing in cosmetic surgery.</p>")
        assert detail_on == "cosmetic surgery"



    def test_no_free_small_fix_or_want_me_to_send_a_sample_in_templates_or_drafts(self, monkeypatch):
        forbidden_phrases = ["free small fix", "want me to send a sample"]

        for seg, copy in op.SEGMENT_COPY.items():
            combined = f"{copy['problem']} {copy['offer']}".lower()
            for bad in forbidden_phrases:
                assert bad not in combined, f"Forbidden phrase '{bad}' found in {seg} template copy"

        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "sheetbolt.analytics@gmail.com")

        for seg in op.SEGMENTS:
            lead = {"business_name": "Acme", "segment": seg, "website": "https://acme.in", "email": "info@acme.in"}
            subj, text_body = op.generate_email(lead, email_type="initial")
            for bad in forbidden_phrases:
                assert bad not in text_body.lower(), f"Forbidden phrase '{bad}' found in text draft for {seg}"
                assert bad not in subj.lower(), f"Forbidden phrase '{bad}' found in subject for {seg}"

            html_body = op.generate_html_email(lead, email_type="initial")
            for bad in forbidden_phrases:
                assert bad not in html_body.lower(), f"Forbidden phrase '{bad}' found in HTML draft for {seg}"

        lead = {"business_name": "Acme", "segment": "gyms", "website": "https://acme.in", "email": "info@acme.in"}
        subj_fu, text_fu = op.generate_email(lead, email_type="followup")
        for bad in forbidden_phrases:
            assert bad not in text_fu.lower()
            assert bad not in subj_fu.lower()

        html_fu = op.generate_html_email(lead, email_type="followup")
        for bad in forbidden_phrases:
            assert bad not in html_fu.lower()

    def test_body_structure_shape_and_length(self, monkeypatch):
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "sheetbolt.analytics@gmail.com")

        expected_cta = "Want me to make a free sample like it for your business, using dummy data?"
        expected_sample = "Here's an example of what I build: https://sheetboltanalytics.netlify.app/#top"

        for seg in op.SEGMENTS:
            lead = {"business_name": "Zenith", "segment": seg, "website": "https://zenith.in", "email": "info@zenith.in"}
            subj, body = op.generate_email(lead, email_type="initial")

            body_only = body.split("Best,\n")[0].strip()
            assert op.count_words(body_only) < 90, f"Body for {seg} exceeds 90 words ({op.count_words(body_only)})"
            assert op.count_words(subj) < 8, f"Subject for {seg} exceeds 8 words ({op.count_words(subj)})"

            assert "Sheetbolt · Automate the mess" in body
            if seg in op.NEW_SEGMENT_TEMPLATES:
                assert "Hi," in body
                assert "I'm Karan, a freelance data analyst." in body
                assert op.NEW_SEGMENT_TEMPLATES[seg]["what_i_do"] in body
                assert op.NEW_SEGMENT_TEMPLATES[seg]["question"] in body
                assert op.OFFER_TEXT in body
                assert expected_sample not in body
            else:
                assert "Hi Zenith team," in body
                assert op.SEGMENT_COPY[seg]["problem"] in body
                assert op.SEGMENT_COPY[seg]["offer"] in body
                assert expected_sample in body
                assert expected_cta in body

    def test_greeting_rules_strip_leading_the_and_length_fallback(self):
        # 1. "The Registry of Sarees" -> strips "The " -> "Registry of Sarees" -> <=4 words and <=30 chars -> "Hi Registry of Sarees team,"
        assert op.clean_business_name("The Registry of Sarees") == "Registry of Sarees"
        assert op.get_greeting("The Registry of Sarees") == "Hi Registry of Sarees team,"

        # 2. "Lavonne Academy of Baking Science and Pastry Arts" -> > 4 words / > 30 chars -> falls back to "Hi there,"
        assert op.get_greeting("Lavonne Academy of Baking Science and Pastry Arts") == "Hi there,"

        # 3. Clean business name with "The " case-insensitively
        assert op.clean_business_name("the studio copper cloves") == "studio copper cloves"
        assert op.get_greeting("the studio copper cloves") == "Hi studio copper cloves team,"

    def test_coaching_template_problem_line(self):
        coaching_problem = op.SEGMENT_COPY["coaching"]["problem"]
        assert coaching_problem == "If tracking student batches, pending fee installments, and attendance across multiple spreadsheets is messy, I can help."
        assert "attendance" in coaching_problem
        assert "test" not in coaching_problem

    def test_unclassified_lead_never_selected(self, monkeypatch):
        monkeypatch.setattr(op, "verify_email_mailbox_live", lambda email, **kwargs: (True, "mocked"))
        test_leads = [
            {"business_name": "Valid Agency", "segment": "agencies", "website": "https://agency.com", "email": "info@agency.com", "status": "new", "source_url": "Indiranagar, Bengaluru"},
            {"business_name": "Unclassified Lead 1", "segment": "unclassified", "website": "https://unc1.com", "email": "info@unc1.com", "status": "new", "source_url": "Indiranagar, Bengaluru"},
            {"business_name": "Unclassified Lead 2", "segment": "unclassified", "website": "https://unc2.com", "email": "info@unc2.com", "status": "unclassified_hold", "source_url": "Indiranagar, Bengaluru"},
            {"business_name": "Held Lead", "segment": "gyms", "website": "https://heldgym.com", "email": "info@heldgym.com", "status": "unclassified_hold", "source_url": "Indiranagar, Bengaluru"},
        ]
        eligible = op.get_eligible_leads(test_leads, allowed_cities=["bengaluru"])
        selected_names = [l["business_name"] for l in eligible]
        assert "Valid Agency" in selected_names
        assert "Unclassified Lead 1" not in selected_names
        assert "Unclassified Lead 2" not in selected_names
        assert "Held Lead" not in selected_names

    def test_leads_csv_unclassified_all_have_unclassified_hold(self):
        leads = op.load_leads(op.LEADS_CSV)
        unclassified_leads = [l for l in leads if l.get("segment") == "unclassified"]
        assert len(unclassified_leads) > 0, "Expected unclassified leads in leads.csv"
        for l in unclassified_leads:
            assert l.get("status") == "unclassified_hold", f"Lead {l.get('business_name')} has status '{l.get('status')}', expected 'unclassified_hold'"


class TestFollowupThreadingAndFreeMailRules:
    """Tests for new follow-up shape & length, threading headers, and free-mail name checks."""

    def test_free_mail_rule_lotusdiagnostic_and_chesssaga_pass(self):
        # lotusdiagnostic@gmail.com for Lotus Diagnostic Centre passes
        flagged, reason = op.check_lead_name_vs_domain("Lotus Diagnostic Centre", "lotusdiagnostic@gmail.com")
        assert flagged is False

        # chesssaga@gmail.com for Chess SaGa passes
        flagged2, reason2 = op.check_lead_name_vs_domain("Chess SaGa", "chesssaga@gmail.com")
        assert flagged2 is False

    def test_free_mail_rule_unrelated_address_flagged_even_with_segment_match(self):
        # john123@gmail.com for Ace Designers is flagged even though its segment check passes
        flagged, reason = op.check_lead_name_vs_domain("Ace Designers", "john123@gmail.com")
        assert flagged is True
        assert reason == "free-mail address does not match business name; check manually"

    def test_followup_body_shape_and_word_limit_with_longest_greeting(self, monkeypatch):
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "sheetbolt.analytics@gmail.com")

        # 4-word business name gives the longest greeting: "Hi Alpha Beta Gamma Delta team,"
        longest_biz_name = "Alpha Beta Gamma Delta"
        expected_greeting = op.get_greeting(longest_biz_name)
        assert expected_greeting == "Hi Alpha Beta Gamma Delta team,"

        for seg in op.SEGMENTS:
            lead = {
                "business_name": longest_biz_name,
                "segment": seg,
                "website": "https://example.com",
                "email": "info@example.com",
            }
            subj, body = op.generate_email(lead, email_type="followup")
            body_only = body.split("Best,\n")[0].strip()
            word_cnt = op.count_words(body_only)

            # Body limit: under 70 words including greeting
            assert word_cnt < 70, f"Followup body for {seg} with longest greeting has {word_cnt} words (must be < 70)"

            # Exact shape verification
            seg_noun = op.FOLLOWUP_SEGMENT_NOUNS[seg]
            expected_p1 = f"Following up on my earlier note. In short: I turn messy {seg_noun} data into simple dashboards and reports, at a fixed price, with a first version in about 3 days."
            expected_p2 = "If it's useful, I can make a free sample using dummy data. Just reply 'yes'."
            expected_p3 = "If it's not relevant, no worries. I won't email again."

            assert expected_greeting in body_only
            assert expected_p1 in body_only
            assert expected_p2 in body_only
            assert expected_p3 in body_only

    def test_followup_absence_of_first_email_text(self, monkeypatch):
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "sheetbolt.analytics@gmail.com")

        for seg in op.SEGMENTS:
            lead = {"business_name": "Zenith", "segment": seg, "website": "https://zenith.in", "email": "info@zenith.in"}
            subj_fu, text_fu = op.generate_email(lead, email_type="followup")

            # Must NOT repeat sample URL or first email pitch
            assert "sheetboltanalytics.netlify.app/#top" not in text_fu
            assert "Here's an example of what I build:" not in text_fu
            assert "Want me to make a free sample like it for your business, using dummy data?" not in text_fu
            assert op.SEGMENT_COPY[seg]["problem"] not in text_fu

            html_fu = op.generate_html_email(
                lead,
                email_type="followup",
                cid_logo="sheetbolt_logo",
                cid_dashboard="sample_dashboard",
            )
            assert "sheetboltanalytics.netlify.app/#top" not in html_fu
            assert "cid:sample_dashboard" not in html_fu
            assert "cid:sheetbolt_logo" in html_fu

    def test_threading_headers_when_message_id_present(self, monkeypatch):
        sent_messages = []
        class MockSMTP:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def ehlo(self): pass
            def starttls(self): pass
            def login(self, u, p): pass
            def send_message(self, msg): sent_messages.append(msg)

        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTP)
        monkeypatch.setattr(op, "fetch_sent_message_id_via_imap", lambda *args, **kwargs: None)
        monkeypatch.setenv("SMTP_PASS", "dummy_pass")
        monkeypatch.setenv("SMTP_USER", "sheetbolt.analytics@gmail.com")

        lead = {"business_name": "Test Clinic", "segment": "clinics", "email": "test@clinic.com"}
        orig_subj = "Clinic data dashboard"
        orig_msgid = "<test12345@gmail.com>"

        subj, body = op.generate_email(lead, email_type="followup", original_subject=orig_subj, message_id=orig_msgid)
        assert subj == f"Re: {orig_subj}"

        final_id, msg = op.send_smtp_email(
            "test@clinic.com",
            subj,
            body,
            lead=lead,
            email_type="followup",
            check_urls_live=False,
            in_reply_to=orig_msgid,
            references=orig_msgid,
        )
        assert len(sent_messages) == 1
        sent_msg = sent_messages[0]
        assert sent_msg["In-Reply-To"] == orig_msgid
        assert sent_msg["References"] == orig_msgid
        assert sent_msg["Subject"] == f"Re: {orig_subj}"

    def test_threading_headers_when_message_id_missing(self, monkeypatch):
        sent_messages = []
        class MockSMTP:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def ehlo(self): pass
            def starttls(self): pass
            def login(self, u, p): pass
            def send_message(self, msg): sent_messages.append(msg)

        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTP)
        monkeypatch.setattr(op, "fetch_sent_message_id_via_imap", lambda *args, **kwargs: None)
        monkeypatch.setenv("SMTP_PASS", "dummy_pass")
        monkeypatch.setenv("SMTP_USER", "sheetbolt.analytics@gmail.com")

        lead = {"business_name": "Test Clinic", "segment": "clinics", "email": "test@clinic.com"}
        orig_subj = "Clinic data dashboard"

        subj, body = op.generate_email(lead, email_type="followup", original_subject=orig_subj, message_id=None)
        assert subj == f"Following up: {orig_subj}"
        assert "Re:" not in subj

        final_id, msg = op.send_smtp_email(
            "test@clinic.com",
            subj,
            body,
            lead=lead,
            email_type="followup",
            check_urls_live=False,
            in_reply_to=None,
            references=None,
        )
        assert len(sent_messages) == 1
        sent_msg = sent_messages[0]
        assert sent_msg["In-Reply-To"] is None
        assert sent_msg["References"] is None
        assert "Re:" not in sent_msg["Subject"]

class TestFollowupEligibilityAndImapSettings:
    """Test follow-up strict eligibility criteria and IMAP configuration/error messages."""

    def test_followup_never_emailed_lead_never_selected(self, tmp_path):
        dummy_log = str(tmp_path / "outreach_log.csv")
        with open(dummy_log, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message,message_id,original_subject\n")

        lead = {
            "business_name": "Never Emailed Clinic",
            "segment": "clinics",
            "website": "https://neveremailed.com",
            "email": "dr@neveremailed.com",
            "source_url": "Indiranagar, Bengaluru 560038",
            "status": "new",
        }
        eligible = op.get_eligible_leads([lead], followup_mode=True, log_filepath=dummy_log)
        assert len(eligible) == 0

        ok, reason, _, _ = op.check_lead_followup_qualification(lead, log_filepath=dummy_log)
        assert not ok
        assert "Never emailed" in reason

    def test_followup_replied_lead_never_selected(self, tmp_path):
        dummy_log = str(tmp_path / "outreach_log.csv")
        with open(dummy_log, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message,message_id,original_subject\n")
            f.write("2026-09-15T10:00:00+05:30,dr@repliedclinic.com,Replied Clinic,clinics,initial,Subject,sent,,<msg1>,Subject\n")
            f.write("2026-09-16T11:00:00+05:30,dr@repliedclinic.com,Replied Clinic,clinics,status_update,Marked as replied,replied,,,\n")

        # 1. Flagged via leads.csv status
        lead_with_status = {
            "business_name": "Replied Clinic",
            "segment": "clinics",
            "website": "https://repliedclinic.com",
            "email": "dr@repliedclinic.com",
            "source_url": "Indiranagar, Bengaluru 560038",
            "status": "replied",
        }
        assert len(op.get_eligible_leads([lead_with_status], followup_mode=True, log_filepath=dummy_log)) == 0

        # 2. Flagged via outreach log status
        lead_in_log = {
            "business_name": "Replied Clinic",
            "segment": "clinics",
            "website": "https://repliedclinic.com",
            "email": "dr@repliedclinic.com",
            "source_url": "Indiranagar, Bengaluru 560038",
            "status": "contacted_1",
        }
        assert len(op.get_eligible_leads([lead_in_log], followup_mode=True, log_filepath=dummy_log)) == 0
        ok, reason, _, _ = op.check_lead_followup_qualification(lead_in_log, log_filepath=dummy_log)
        assert not ok
        assert "replied" in reason.lower()

    def test_followup_unsubscribed_lead_never_selected(self, tmp_path):
        dummy_log = str(tmp_path / "outreach_log.csv")
        with open(dummy_log, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message,message_id,original_subject\n")
            f.write("2026-09-15T10:00:00+05:30,user@unsubgym.com,Unsub Gym,gyms,initial,Subject,sent,,<msg1>,Subject\n")
            f.write("2026-09-16T11:00:00+05:30,user@unsubgym.com,Unsub Gym,gyms,status_update,Marked as unsubscribed,unsubscribed,,,\n")

        lead = {
            "business_name": "Unsub Gym",
            "segment": "gyms",
            "website": "https://unsubgym.com",
            "email": "user@unsubgym.com",
            "source_url": "Indiranagar, Bengaluru 560038",
            "status": "unsubscribed",
        }
        assert len(op.get_eligible_leads([lead], followup_mode=True, log_filepath=dummy_log)) == 0

        lead_active_status = dict(lead, status="contacted_1")
        assert len(op.get_eligible_leads([lead_active_status], followup_mode=True, log_filepath=dummy_log)) == 0
        ok, reason, _, _ = op.check_lead_followup_qualification(lead_active_status, log_filepath=dummy_log)
        assert not ok
        assert "unsubscribed" in reason.lower()

    def test_followup_already_followed_up_never_selected(self, tmp_path):
        dummy_log = str(tmp_path / "outreach_log.csv")
        with open(dummy_log, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message,message_id,original_subject\n")
            f.write("2026-09-15T10:00:00+05:30,contact@followedup.com,Followed Agency,agencies,initial,Subject,sent,,<msg1>,Subject\n")
            f.write("2026-09-22T10:00:00+05:30,contact@followedup.com,Followed Agency,agencies,followup,Re: Subject,sent,,<msg2>,Subject\n")

        # 1. Lead marked contacted_2
        lead_contacted_2 = {
            "business_name": "Followed Agency",
            "segment": "agencies",
            "website": "https://followedup.com",
            "email": "contact@followedup.com",
            "source_url": "Indiranagar, Bengaluru 560038",
            "status": "contacted_2",
        }
        assert len(op.get_eligible_leads([lead_contacted_2], followup_mode=True, log_filepath=dummy_log)) == 0

        # 2. Lead marked contacted_1 but log has followup sent
        lead_contacted_1 = dict(lead_contacted_2, status="contacted_1")
        assert len(op.get_eligible_leads([lead_contacted_1], followup_mode=True, log_filepath=dummy_log)) == 0
        ok, reason, _, _ = op.check_lead_followup_qualification(lead_contacted_1, log_filepath=dummy_log)
        assert not ok
        assert "already sent" in reason.lower()

    def test_followup_under_4_business_days_never_selected(self, tmp_path):
        dummy_log = str(tmp_path / "outreach_log.csv")
        # Thursday 2026-09-24 to Monday 2026-09-28 is 2 business days (Friday, Monday)
        with open(dummy_log, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message,message_id,original_subject\n")
            f.write("2026-09-24T10:00:00+05:30,contact@recentlead.com,Recent Lead,agencies,initial,Subject,sent,,<msg1>,Subject\n")

        lead = {
            "business_name": "Recent Lead",
            "segment": "agencies",
            "website": "https://recentlead.com",
            "email": "contact@recentlead.com",
            "source_url": "Indiranagar, Bengaluru 560038",
            "status": "contacted_1",
        }
        today = op.date(2026, 9, 28)
        ok, reason, _, bdays = op.check_lead_followup_qualification(lead, log_filepath=dummy_log, today=today)
        assert not ok
        assert bdays < 4
        assert "< 4 required" in reason

    def test_followup_qualifying_lead_selected_with_reason(self, tmp_path, monkeypatch):
        dummy_log = str(tmp_path / "outreach_log.csv")
        # Monday 2026-09-21 to Monday 2026-09-28 is 5 business days
        with open(dummy_log, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message,message_id,original_subject\n")
            f.write("2026-09-21T10:00:00+05:30,info@goodclinic.com,Good Dental Clinic,clinics,initial,Subject,sent,,<msg1>,Subject\n")

        lead = {
            "business_name": "Good Dental Clinic",
            "segment": "clinics",
            "website": "https://goodclinic.com",
            "email": "info@goodclinic.com",
            "source_url": "Indiranagar, Bengaluru 560038",
            "status": "contacted_1",
            "website_detail": "dental treatments and clinic",
        }
        today = op.date(2026, 9, 28)
        monkeypatch.setattr(op, "get_ist_now", lambda: op.datetime(2026, 9, 28, 11, 0, tzinfo=op.IST))
        monkeypatch.setattr(op, "verify_email_mailbox_live", lambda email, **kwargs: (True, "mocked"))

        ok, reason, send_dt, bdays = op.check_lead_followup_qualification(lead, log_filepath=dummy_log, today=today)
        assert ok
        assert bdays >= 4
        assert "2026-09-21" in reason
        assert f"{bdays} business days elapsed" in reason

        # get_eligible_leads with monkeypatched date
        eligible = op.get_eligible_leads([lead], followup_mode=True, log_filepath=dummy_log)
        assert len(eligible) == 1
        assert eligible[0]["_followup_qualification"] == reason

    def test_imap_settings_and_error_message_on_login_failure(self, monkeypatch, capsys):
        class FailingIMAP:
            def __init__(self, host, port, timeout=10):
                assert host == op.IMAP_HOST == "imap.gmail.com"
                assert port == op.IMAP_PORT == 993
            def login(self, u, p):
                raise op.imaplib.IMAP4.error("Invalid credentials (Failure)")
            def logout(self):
                pass

        monkeypatch.setattr(op.imaplib, "IMAP4_SSL", FailingIMAP)
        res = op.fetch_sent_message_id_via_imap(
            subject="Automated reporting",
            to_email="test@example.com",
            user="sheetbolt.analytics@gmail.com",
            password="wrong_password",
        )
        assert res is None

        captured = capsys.readouterr().out
        assert "imap.gmail.com" in captured
        assert "993 (SSL)" in captured
        assert '"[Gmail]/Sent Mail"' in captured
        assert "Enable IMAP" in captured
        assert "Forwarding and POP/IMAP" in captured


class TestPhase2CircuitBreakerAndMailboxSafety:
    """Boundary and behavioral tests for Phase 2 circuit breaker and probe fail-closed rules."""

    def test_circuit_breaker_boundary_cases(self, tmp_path):
        log_file = tmp_path / "outreach_log.csv"
        # 1. 2 bounces out of 10 -> False (under 3 bounces, under 20 window)
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            for i in range(8):
                f.write(f"2026-09-24T11:00:00+05:30,u{i}@test.com,Biz{i},gyms,initial,Test,sent,\n")
            f.write("2026-09-24T11:30:00+05:30,bad1@test.com,Biz1,gyms,initial,Test,bounced,550\n")
            f.write("2026-09-24T11:31:00+05:30,bad2@test.com,Biz2,gyms,initial,Test,bounced,550\n")

        tripped, rate, b_cnt, denom, _ = op.check_circuit_breaker(str(log_file))
        assert not tripped
        assert b_cnt == 2
        assert denom == 10

        # 2. Add 3rd bounce -> Trips because bounces >= 3
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("2026-09-24T11:32:00+05:30,bad3@test.com,Biz3,gyms,initial,Test,bounced,550\n")
        tripped, rate, b_cnt, denom, reason = op.check_circuit_breaker(str(log_file))
        assert tripped
        assert b_cnt == 3
        assert "limit is 3" in reason

        # 3. 2 bounces in window of 20 sends -> 10% bounce rate > 5% -> Trips!
        log_file_20 = tmp_path / "outreach_log_20.csv"
        with open(log_file_20, "w", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            for i in range(18):
                f.write(f"2026-09-24T11:00:00+05:30,user{i}@test.com,Biz{i},gyms,initial,Test,sent,\n")
            f.write("2026-09-24T11:30:00+05:30,bad1@test.com,Biz1,gyms,initial,Test,bounced,550\n")
            f.write("2026-09-24T11:31:00+05:30,bad2@test.com,Biz2,gyms,initial,Test,bounced,550\n")
        tripped, rate, b_cnt, denom, reason = op.check_circuit_breaker(str(log_file_20))
        assert tripped
        assert b_cnt == 2
        assert denom == 20
        assert "exceeding 5% limit" in reason

        # 4. 1 bounce in window of 25 sends -> 4% <= 5% -> Healthy!
        log_file_25 = tmp_path / "outreach_log_25.csv"
        with open(log_file_25, "w", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            for i in range(24):
                f.write(f"2026-09-24T11:00:00+05:30,usr{i}@test.com,Biz{i},gyms,initial,Test,sent,\n")
            f.write("2026-09-24T11:30:00+05:30,bad1@test.com,Biz1,gyms,initial,Test,bounced,550\n")
        tripped, rate, b_cnt, denom, reason = op.check_circuit_breaker(str(log_file_25))
        assert not tripped
        assert b_cnt == 1
        assert denom == 25
        assert "healthy" in reason.lower()

    def test_followup_bounces_never_count_toward_initial_circuit_breaker(self, tmp_path):
        log_file = tmp_path / "outreach_log_followup.csv"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            for i in range(10):
                f.write(f"2026-09-24T11:00:00+05:30,u{i}@test.com,Biz{i},gyms,initial,Test,sent,\n")
            for i in range(5):
                f.write(f"2026-09-28T11:00:00+05:30,fu{i}@test.com,FuBiz{i},gyms,followup,Test,bounced,550\n")

        tripped, rate, b_cnt, denom, _ = op.check_circuit_breaker(str(log_file))
        assert not tripped
        assert b_cnt == 0
        assert denom == 10

    def test_circuit_breaker_override_reason_logged(self, tmp_path, monkeypatch):
        override_file = tmp_path / "overrides.log"
        monkeypatch.setattr(op, "OVERRIDE_LOG_FILE", str(override_file))
        op.log_circuit_breaker_override(
            reason="Special test batch with client approval",
            tripped_reason="3 bounces in window",
            window_stats="3/10 bounces (30.0%)"
        )
        assert override_file.exists()
        content = override_file.read_text(encoding="utf-8")
        assert "Special test batch with client approval" in content
        assert "3 bounces in window" in content

    def test_mailbox_verify_fails_closed_on_connection_error_or_timeout(self, monkeypatch):
        monkeypatch.setattr(op, "get_mx_hosts", lambda domain, **kwargs: ["mx.example.com"])
        
        class FailingSMTP:
            def __init__(self, host, port, timeout=7):
                raise op.socket.timeout("timed out connecting to port 25")
        monkeypatch.setattr(op.smtplib, "SMTP", FailingSMTP)

        ok, reason = op.verify_email_mailbox_live("test@example.com")
        assert not ok
        assert "unverified: SMTP port 25 probe failed" in reason
        assert "timed out" in reason.lower()
        assert "verified mailbox" not in reason.lower()


class TestPhase2CrossFileSuppressionAndCapGuard:
    """Tests for cross-file suppression and hard daily cap guard."""

    def test_cross_file_suppression_blocks_bounced_and_unsubscribed_leads(self, tmp_path, monkeypatch):
        outreach_log = tmp_path / "outreach_log.csv"

        with open(outreach_log, "w", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            f.write("2026-09-24T11:00:00+05:30,bounced@test.com,Bounced Biz,agencies,initial,Test,bounced,550\n")
            f.write("2026-09-24T11:05:00+05:30,unsub@test.com,Unsub Biz,agencies,initial,Test,unsubscribed,\n")

        monkeypatch.setattr(op, "verify_email_mailbox_live", lambda email, **kwargs: (True, "mocked"))

        leads = [
            {"business_name": "Valid Agency", "segment": "agencies", "website": "https://agency.com", "email": "valid@agency.com", "status": "new", "source_url": "Indiranagar, Bengaluru"},
            {"business_name": "Bounced Lead", "segment": "agencies", "website": "https://bounced.com", "email": "bounced@test.com", "status": "new", "source_url": "Indiranagar, Bengaluru"},
            {"business_name": "Unsub Lead", "segment": "agencies", "website": "https://unsub.com", "email": "unsub@test.com", "status": "new", "source_url": "Indiranagar, Bengaluru"},
        ]

        eligible = op.get_eligible_leads(leads, log_filepath=str(outreach_log))
        selected_emails = [l["email"] for l in eligible]
        assert "valid@agency.com" in selected_emails
        assert "bounced@test.com" not in selected_emails
        assert "unsub@test.com" not in selected_emails

    def test_daily_cap_guard_cannot_exceed_hard_limit(self, tmp_path):
        log_file = tmp_path / "outreach_log.csv"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            f.write("2026-08-01T11:00:00+05:30,u1@test.com,Biz1,clinics,initial,Test,sent,\n")

        cap, week, desc = op.get_warmup_cap(str(log_file), target_date=op.date(2026, 9, 1))
        assert cap <= op.HARD_DAILY_CAP_LIMIT


class TestPhase3InboxSyncAndClassification:
    """Tests for deterministic inbox sync classification and IMAP handling."""

    def test_deterministic_classification_rules(self):
        # 1. Unsubscribe phrases
        c1, _ = op.classify_inbound_message("Please unsubscribe", "Take me off your list", "user@test.com")
        assert c1 == "unsubscribe"
        c2, _ = op.classify_inbound_message("Re: reports", "STOP", "user@test.com")
        assert c2 == "unsubscribe"
        c3, _ = op.classify_inbound_message("Re: data service", "not interested thank you", "user@test.com")
        assert c3 == "unsubscribe"

        # 2. Bounce notices
        c4, _ = op.classify_inbound_message("Delivery Status Notification (Failure)", "Delivery failed to user", "mailer-daemon@googlemail.com")
        assert c4 in ["bounce_notice", "bounce_permanent"]

        # 3. Auto replies
        c5, _ = op.classify_inbound_message("Automatic reply: Out of office", "I am out of the office until next week", "user@test.com")
        assert c5 == "auto_reply"

        # 4. Pricing inquiry
        c6, _ = op.classify_inbound_message("Re: automated reporting", "How much do you charge for this?", "user@test.com")
        assert c6 == "pricing"

        # 5. Information inquiry
        c7, _ = op.classify_inbound_message("Re: sample dashboard", "Could you share more details or examples?", "user@test.com")
        assert c7 == "wants_info"

        # 6. Interested
        c8, _ = op.classify_inbound_message("Re: reports", "Sounds good, let's schedule a call this week", "user@test.com")
        assert c8 == "interested"

        # 7. Wrong contact
        c9, _ = op.classify_inbound_message("Re: reports", "I am the wrong person for this, contact our IT head", "user@test.com")
        assert c9 == "wrong_contact"

        # 8. Needs review fallback
        c10, _ = op.classify_inbound_message("Re: reports", "Hello Karan, acknowledging your email.", "user@test.com")
        assert c10 == "needs_review"

    def test_mocked_imap_sync_inbox_idempotency_and_state_updates(self, tmp_path, monkeypatch):
        dummy_log = tmp_path / "outreach_log.csv"
        dummy_leads = tmp_path / "leads.csv"
        monkeypatch.setattr(op, "OUTREACH_LOG_CSV", str(dummy_log))
        monkeypatch.setattr(op, "LEADS_CSV", str(dummy_leads))

        with open(dummy_log, "w", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message,message_id,original_subject\n")
            f.write("2026-09-21T10:00:00+05:30,client@test.com,Client Clinic,clinics,initial,Subject,sent,,<initial-msg-1>,Subject\n")

        with open(dummy_leads, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            writer.writeheader()
            writer.writerow({"business_name": "Client Clinic", "segment": "clinics", "email": "client@test.com", "status": "contacted_1", "website": "https://client.com"})

        # Mock IMAP connection returning one unsubscribe message
        raw_msg = (
            b"From: client@test.com\r\n"
            b"To: sender@sheetbolt.com\r\n"
            b"Subject: Re: Subject\r\n"
            b"In-Reply-To: <initial-msg-1>\r\n"
            b"Message-ID: <reply-msg-1@test.com>\r\n"
            b"\r\n"
            b"Please unsubscribe me and remove me from your list.\r\n"
        )

        class MockIMAP:
            def select(self, folder, readonly=True):
                return "OK", [b"1"]
            def search(self, charset, criteria):
                return "OK", [b"1"]
            def fetch(self, num, parts):
                return "OK", [(b"1", raw_msg)]
            def logout(self):
                pass

        res = op.sync_inbox(log_filepath=str(dummy_log), imap_conn=MockIMAP())
        assert res["matched_messages"] == 1
        assert res["unsubscribes"] == 1

        # Check lead was updated to unsubscribed in leads.csv
        updated_leads = op.load_leads(str(dummy_leads))
        assert updated_leads[0]["status"] == "unsubscribed"

        # Check idempotency: run again, should skip already synced
        res2 = op.sync_inbox(log_filepath=str(dummy_log), imap_conn=MockIMAP(), lead_files=[str(dummy_leads)])
        assert res2["skipped_already_synced"] == 1
        assert res2["unsubscribes"] == 0

    def test_verify_email_mailbox_live_probe_paths(self, monkeypatch):
        """Test that verify_email_mailbox_live returns MailboxVerifyResult with correct probe_path."""
        # 1. No MX
        monkeypatch.setattr(op, "get_mx_hosts", lambda domain, **kwargs: [])
        res_no_mx = op.verify_email_mailbox_live("user@nomxdomain.com")
        assert not res_no_mx.is_valid
        assert res_no_mx.probe_path == "no_mx"
        # Unpacks as (is_valid, reason)
        valid, reason = res_no_mx
        assert not valid
        assert "no active MX" in reason

        # 2. 250 OK
        class MockSMTP250:
            def __init__(self, host, port, timeout=7): pass
            def ehlo(self, name): pass
            def mail(self, sender): pass
            def rcpt(self, rcpt): return (250, b"OK")
            def quit(self): pass
            def close(self): pass

        monkeypatch.setattr(op, "get_mx_hosts", lambda domain, **kwargs: ["mx.example.com"])
        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTP250)
        res_250 = op.verify_email_mailbox_live("user@example.com")
        assert res_250.is_valid
        assert res_250.probe_path == "probe_250"

        # 3. 550 permanent bounce
        class MockSMTP550:
            def __init__(self, host, port, timeout=7): pass
            def ehlo(self, name): pass
            def mail(self, sender): pass
            def rcpt(self, rcpt): return (550, b"User unknown")
            def quit(self): pass
            def close(self): pass

        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTP550)
        res_550 = op.verify_email_mailbox_live("bad@example.com")
        assert not res_550.is_valid
        assert res_550.probe_path == "probe_5xx"

        # 4. 450 / 4xx transient rejection treated as UNVERIFIED (is_valid=False)
        class MockSMTP450:
            def __init__(self, host, port, timeout=7): pass
            def ehlo(self, name): pass
            def mail(self, sender): pass
            def rcpt(self, rcpt): return (450, b"Mailbox temporarily unavailable / greylisted")
            def quit(self): pass
            def close(self): pass

        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTP450)
        res_450 = op.verify_email_mailbox_live("temp@example.com")
        assert not res_450.is_valid
        assert res_450.probe_path == "probe_4xx"
        assert "unverified" in res_450.reason

        # 5. Connection error / port 25 blocked
        def mock_smtp_err(host, port, timeout=7):
            raise socket.timeout("Timed out connecting to port 25")

        monkeypatch.setattr(op.smtplib, "SMTP", mock_smtp_err)
        res_err = op.verify_email_mailbox_live("err@example.com")
        assert not res_err.is_valid
        assert res_err.probe_path == "probe_error"
        assert "unverified" in res_err.reason

    def test_port_25_startup_warning(self, monkeypatch, capsys):
        """Test check_port_25_reachability prints warning when port 25 is blocked."""
        monkeypatch.setattr(op.socket, "create_connection", lambda addr, timeout=3: (_ for _ in ()).throw(OSError("Port 25 blocked")))
        reachable = op.check_port_25_reachability(timeout=1, force=True)
        assert not reachable
        out = capsys.readouterr().out
        assert "[WARNING]" in out
        assert "port 25" in out.lower()

    def test_sync_inbox_dry_run_mode(self, tmp_path, monkeypatch):
        """Test that sync_inbox with dry_run=True classifies and prints but writes nothing."""
        dummy_log = tmp_path / "outreach_log_dry.csv"
        dummy_leads = tmp_path / "leads_dry.csv"

        with open(dummy_log, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message,message_id,original_subject,probe_path\n")
            f.write("2026-09-21T10:00:00+05:30,client@test.com,Client Clinic,clinics,initial,Subject,sent,,<initial-msg-dry>,Subject,\n")

        with open(dummy_leads, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            writer.writeheader()
            writer.writerow({"business_name": "Client Clinic", "segment": "clinics", "email": "client@test.com", "status": "contacted_1", "website": "https://client.com"})

        raw_msg = (
            b"From: client@test.com\r\n"
            b"To: sender@sheetbolt.com\r\n"
            b"Subject: Re: Subject\r\n"
            b"In-Reply-To: <initial-msg-dry>\r\n"
            b"Message-ID: <reply-msg-dry@test.com>\r\n"
            b"\r\n"
            b"Stop emailing me please.\r\n"
        )

        class MockIMAP:
            def select(self, folder, readonly=True):
                return "OK", [b"1"]
            def search(self, charset, criteria):
                return "OK", [b"1"]
            def fetch(self, num, parts):
                return "OK", [(b"1", raw_msg)]
            def logout(self):
                pass

        # Run with dry_run=True
        res = op.sync_inbox(log_filepath=str(dummy_log), imap_conn=MockIMAP(), lead_files=[str(dummy_leads)], dry_run=True)
        assert res["matched_messages"] == 1
        assert res["unsubscribes"] == 1
        assert "[DRY-RUN]" in res["items"][0]["action"]

        # Verify NOTHING was written to dummy_leads
        leads = op.load_leads(str(dummy_leads))
        assert leads[0]["status"] == "contacted_1"

        # Verify NO new rows in dummy_log
        log_rows = op.load_outreach_log(str(dummy_log))
        assert len(log_rows) == 1

    def test_circuit_breaker_evaluates_all_send_history_regardless_of_file_scope(self, tmp_path):
        """Test that circuit breaker evaluates across all send history regardless of enabled_files."""
        log_file = tmp_path / "outreach_log_scope.csv"
        leads_domestic = tmp_path / "leads_domestic.csv"
        leads_foreign = tmp_path / "leads_foreign.csv"

        # Domestic leads: 5 attempts, 3 bounces
        with open(leads_domestic, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            writer.writeheader()
            for i in range(5):
                writer.writerow({"email": f"dom{i}@test.com", "business_name": f"Dom{i}", "segment": "clinics"})

        # Foreign leads: 25 attempts, 0 bounces
        with open(leads_foreign, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            writer.writeheader()
            for i in range(25):
                writer.writerow({"email": f"foreign{i}@test.com", "business_name": f"Foreign{i}", "segment": "agencies"})

        with open(log_file, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message,message_id,original_subject,probe_path\n")
            # Domestic: 3 bounces out of 5
            for i in range(3):
                f.write(f"2026-09-01T10:00:00+05:30,dom{i}@test.com,Dom{i},clinics,initial,Subj,bounced,550 error,,,\n")
            for i in range(3, 5):
                f.write(f"2026-09-01T10:00:00+05:30,dom{i}@test.com,Dom{i},clinics,initial,Subj,sent,,,\n")
            # Foreign: 25 sends appended afterwards
            for i in range(25):
                f.write(f"2026-09-02T10:00:00+05:30,foreign{i}@test.com,Foreign{i},agencies,initial,Subj,sent,,,\n")

        # Breaker evaluates all 30 sends across entire log, detects 3 bounces, and trips
        tripped, rate, b_cnt, denom, reason = op.check_circuit_breaker(str(log_file), enabled_files=[str(leads_domestic)])
        assert tripped
        assert b_cnt == 3
        assert denom == 30

        tripped_global, rate_g, b_cnt_g, denom_g, _ = op.check_circuit_breaker(str(log_file), enabled_files=None)
        assert tripped_global
        assert b_cnt_g == 3
        assert denom_g == 30

    def test_circuit_breaker_persistent_lock_and_manual_reset(self, tmp_path):
        """Test persistent breaker locking, absence of window rolloff, and manual reset logging."""
        log_file = tmp_path / "outreach_log_cb.csv"
        state_file = tmp_path / "cb_state.json"
        reset_log = tmp_path / "cb_resets.log"

        with open(log_file, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            f.write("2026-10-01T10:00:00+05:30,b1@test.com,B1,clinics,initial,Subj,bounced,550\n")
            f.write("2026-10-01T10:01:00+05:30,b2@test.com,B2,clinics,initial,Subj,bounced,550\n")
            f.write("2026-10-01T10:02:00+05:30,b3@test.com,B3,clinics,initial,Subj,bounced,550\n")

        # Initial evaluation trips breaker and saves persistent state lock
        tripped, rate, b_cnt, denom, reason = op.check_circuit_breaker(str(log_file), state_file=str(state_file))
        assert tripped
        assert b_cnt == 3
        assert state_file.exists()

        # Add 100 successful sends afterwards. Must NOT self-reset or rolloff!
        with open(log_file, "a", newline="", encoding="utf-8") as f:
            for i in range(100):
                f.write(f"2026-10-02T10:{i%60:02d}:00+05:30,ok{i}@test.com,Ok{i},clinics,initial,Subj,sent,\n")

        tripped_after, _, _, _, reason_after = op.check_circuit_breaker(str(log_file), state_file=str(state_file))
        assert tripped_after
        assert "locked" in reason_after.lower()

        # Attempt reset without reason raises ValueError
        with pytest.raises(ValueError, match="operational justification is required"):
            op.reset_circuit_breaker("", state_file=str(state_file), reset_log_file=str(reset_log))

        # Reset with documented operational justification
        reset_ok = op.reset_circuit_breaker(
            "Cleaned list and verified SPF/DKIM with domain admin",
            state_file=str(state_file),
            reset_log_file=str(reset_log),
        )
        assert reset_ok is True
        assert reset_log.exists()
        log_content = reset_log.read_text(encoding="utf-8")
        assert "Cleaned list and verified SPF/DKIM with domain admin" in log_content

        # Breaker after reset ignores pre-reset entries and is healthy
        tripped_now, _, b_now, d_now, r_now = op.check_circuit_breaker(str(log_file), state_file=str(state_file))
        assert not tripped_now
        assert b_now == 0
        assert "healthy" in r_now.lower()


class TestPhase4bHardeningAndVerification:
    """Tests for Phase 4b verification, auth abort, bounce splitting, and reporting."""

    def test_circuit_breaker_recomputes_on_missing_or_corrupt_state(self, tmp_path):
        """When state file is missing or corrupt, recompute from log and never default to healthy."""
        log_file = tmp_path / "outreach_log.csv"
        state_file = tmp_path / "cb_state.json"

        # Create log with 3 unique bounces
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            f.write("2026-10-01T10:00:00+05:30,b1@test.com,B1,clinics,initial,Subj,bounced,550\n")
            f.write("2026-10-01T10:01:00+05:30,b2@test.com,B2,clinics,initial,Subj,bounced,550\n")
            f.write("2026-10-01T10:02:00+05:30,b3@test.com,B3,clinics,initial,Subj,bounced,550\n")

        # 1. State file missing -> recomputes and trips
        assert not state_file.exists()
        tripped, rate, b_cnt, denom, reason = op.check_circuit_breaker(str(log_file), state_file=str(state_file))
        assert tripped is True
        assert b_cnt == 3
        assert denom == 3
        assert state_file.exists()

        # 2. Corrupt state file with malformed JSON
        with open(state_file, "w", encoding="utf-8") as f:
            f.write("{invalid-json-data: not-closed")

        # Must NOT default to healthy! Recomputes from log, trips, and repairs file
        tripped_corrupt, _, b_c, d_c, _ = op.check_circuit_breaker(str(log_file), state_file=str(state_file))
        assert tripped_corrupt is True
        assert b_c == 3
        # Confirm state file is repaired and valid JSON
        repaired_state, is_valid = op.load_circuit_breaker_state(str(state_file))
        assert is_valid is True
        assert repaired_state.get("is_tripped") is True

    def test_smtp_auth_challenge_stops_batch_immediately(self, tmp_path, monkeypatch):
        """
        Reproduce 2026-10-02 failure: When SMTP returns 534 WebLoginRequired,
        abort run immediately. Exactly 1 failure logged, 0 subsequent sends attempted.
        """
        log_file = tmp_path / "outreach_log.csv"
        leads_file = tmp_path / "leads.csv"
        state_file = tmp_path / "cb_state.json"

        # Create 5 leads
        with open(leads_file, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            writer.writeheader()
            for i in range(5):
                writer.writerow({
                    "business_name": f"Smile Studio {i}",
                    "segment": "clinics",
                    "website": f"https://smilestudio{i}.in",
                    "email": f"contact@smilestudio{i}.in",
                    "source_url": "Indiranagar Bengaluru",
                    "status": "contacted_1",
                    "last_contacted": "2026-09-24T11:00:00+05:30",
                    "website_detail": "dental clinic",
                })

        # Initial log entries
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message,message_id,original_subject,probe_path\n")
            for i in range(5):
                f.write(f"2026-09-24T11:00:00+05:30,contact@smilestudio{i}.in,Smile Studio {i},clinics,initial,Subj,sent,,<orig-{i}>,Subj,probe_250\n")

        # Mock mailbox check to pass
        monkeypatch.setattr(op, "verify_email_mailbox_live", lambda email: op.MailboxVerifyResult(True, "250 OK", "probe_250"))
        monkeypatch.setattr(op, "is_in_sending_window", lambda: (True, "Mock window open"))
        monkeypatch.setattr(op, "fetch_sent_message_id_via_imap", lambda *args, **kwargs: "<msgid>")

        # Mock SMTP to fail on login with Google 534 WebLoginRequired
        class AuthFailingSMTP:
            def __init__(self, host, port, timeout=20):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def ehlo(self):
                pass
            def starttls(self):
                pass
            def login(self, user, password):
                raise op.smtplib.SMTPAuthenticationError(
                    534,
                    b"5.7.9 Please log in with your web browser and then try again. Learn more at https://support.google.com/mail/answer/78754"
                )

        monkeypatch.setattr(op.smtplib, "SMTP", AuthFailingSMTP)
        monkeypatch.setenv("SMTP_USER", "sender@sheetbolt.com")
        monkeypatch.setenv("SMTP_PASS", "app_pass")

        # Run followup outreach
        op.run_outreach(
            leads_filepath=str(leads_file),
            log_filepath=str(log_file),
            state_file=str(state_file),
            send_live=True,
            followup_mode=True,
            force_window=True,
            limit=5,
        )

        # Verify only 1 followup attempt was logged (not 5 in a row!)
        entries = op.load_outreach_log(str(log_file))
        followup_attempts = [e for e in entries if e.get("email_type") == "followup"]
        assert len(followup_attempts) == 1
        assert followup_attempts[0]["status"] == "failed"
        assert "534" in followup_attempts[0]["error_message"]

    def test_inbound_bounce_split_delivery_delay_and_permanent(self, tmp_path, monkeypatch):
        """Test splitting bounce notices into delivery_delay (no suppression) vs bounce_permanent (suppressed)."""
        log_file = tmp_path / "outreach_log.csv"
        leads_file = tmp_path / "leads.csv"

        # 1. Classification check
        delay_subj = "Delivery Status Notification (Delay)"
        delay_body = "This is an automatically generated Delivery Status Notification.\nTHIS IS A WARNING MESSAGE ONLY.\nYOU DO NOT NEED TO RESEND YOUR MESSAGE.\nDelivery to recipient has been delayed."
        cat_delay, reason_delay = op.classify_inbound_message(delay_subj, delay_body, "mailer-daemon@googlemail.com")
        assert cat_delay == "delivery_delay"
        assert "transient delay; flag for recheck after 72h" in reason_delay

        perm_subj = "Delivery Status Notification (Failure)"
        perm_body = "550 5.1.1 The email account that you tried to reach does not exist."
        cat_perm, reason_perm = op.classify_inbound_message(perm_subj, perm_body, "mailer-daemon@googlemail.com")
        assert cat_perm == "bounce_permanent"

        # 2. sync_inbox behavior check
        with open(leads_file, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            writer.writeheader()
            writer.writerow({"business_name": "Delay Biz", "segment": "clinics", "email": "delay@test.com", "status": "contacted_1"})
            writer.writerow({"business_name": "Perm Biz", "segment": "clinics", "email": "perm@test.com", "status": "contacted_1"})

        with open(log_file, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message,message_id,original_subject,probe_path\n")
            f.write("2026-10-01T10:00:00+05:30,delay@test.com,Delay Biz,clinics,initial,Subj,sent,,<delay-mid>,Subj,probe_250\n")
            f.write("2026-10-01T10:00:00+05:30,perm@test.com,Perm Biz,clinics,initial,Subj,sent,,<perm-mid>,Subj,probe_250\n")

        class MockIMAPDelayAndPerm:
            def select(self, *args, **kwargs):
                return "OK", [b"2"]
            def search(self, *args, **kwargs):
                return "OK", [b"1 2"]
            def fetch(self, msg_num, *args, **kwargs):
                if str(msg_num) == "1" or msg_num == b"1":
                    raw = (
                        b"From: mailer-daemon@googlemail.com\r\n"
                        b"Subject: Delivery Status Notification (Delay)\r\n"
                        b"Message-ID: <bounce-msg-delay@google.com>\r\n"
                        b"\r\n"
                        b"Delivery to delay@test.com has been delayed. Will keep trying for 72 hours."
                    )
                else:
                    raw = (
                        b"From: mailer-daemon@googlemail.com\r\n"
                        b"Subject: Delivery Status Notification (Failure)\r\n"
                        b"Message-ID: <bounce-msg-perm@google.com>\r\n"
                        b"\r\n"
                        b"550 5.1.1 The email account that you tried to reach does not exist: perm@test.com"
                    )
                return "OK", [(b"1 (RFC822)", raw)]
            def logout(self):
                pass

        results = op.sync_inbox(
            log_filepath=str(log_file),
            leads_filepath=str(leads_file),
            lead_files=[str(leads_file)],
            imap_conn=MockIMAPDelayAndPerm(),
            dry_run=False,
        )

        assert results.get("delivery_delays", 0) == 1
        assert results.get("bounces", 0) == 1

        leads = op.load_leads(str(leads_file))
        delay_lead = next(l for l in leads if l["email"] == "delay@test.com")
        perm_lead = next(l for l in leads if l["email"] == "perm@test.com")

        # delay@test.com is NOT suppressed (remains contacted_1)
        assert delay_lead["status"] == "contacted_1"
        # perm@test.com IS suppressed (status changed to bounced)
        assert perm_lead["status"] == "bounced"

    def test_unique_prospects_reporting(self, tmp_path):
        """Test reporting generates unique prospect breakdown with denominators."""
        log_file = tmp_path / "outreach_log.csv"
        leads_file1 = tmp_path / "leads1.csv"
        leads_file2 = tmp_path / "leads2.csv"

        with open(leads_file1, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            writer.writeheader()
            for i in range(10):
                writer.writerow({"business_name": f"BizA{i}", "segment": "clinics", "email": f"a{i}@test.com", "status": "new"})

        with open(leads_file2, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            writer.writeheader()
            for i in range(5):
                writer.writerow({"business_name": f"BizB{i}", "segment": "agencies", "email": f"b{i}@test.com", "status": "new"})

        with open(log_file, "w", newline="", encoding="utf-8") as f:
            f.write("timestamp,recipient_email,business_name,segment,email_type,subject,status,error_message\n")
            # 4 sent in file1, 1 bounced
            for i in range(4):
                f.write(f"2026-10-01T10:00:00+05:30,a{i}@test.com,BizA{i},clinics,initial,Subj,sent,\n")
            f.write("2026-10-01T10:05:00+05:30,a0@test.com,BizA0,clinics,initial,Subj,bounced,550\n")
            # 2 followups in file1
            f.write("2026-10-05T10:00:00+05:30,a1@test.com,BizA1,clinics,followup,Subj,sent,\n")
            f.write("2026-10-05T10:00:00+05:30,a2@test.com,BizA2,clinics,followup,Subj,sent,\n")
            # 2 sent in file2
            for i in range(2):
                f.write(f"2026-10-01T10:00:00+05:30,b{i}@test.com,BizB{i},agencies,initial,Subj,sent,\n")

        rep = op.generate_report(log_filepath=str(log_file), lead_files=[str(leads_file1), str(leads_file2)])

        assert rep["files"]["leads1.csv"]["total_prospects"] == 10
        assert rep["files"]["leads1.csv"]["initial_sent"] == 4
        assert rep["files"]["leads1.csv"]["bounced"] == 1
        assert rep["files"]["leads1.csv"]["followed_up"] == 2
        assert rep["files"]["leads1.csv"]["suppressed"] == 1

        assert rep["files"]["leads2.csv"]["total_prospects"] == 5
        assert rep["files"]["leads2.csv"]["initial_sent"] == 2
        assert rep["files"]["leads2.csv"]["bounced"] == 0

        assert rep["global"]["total_prospects"] == 15
        assert rep["global"]["initial_sent"] == 6
        assert rep["global"]["bounced"] == 1
        assert rep["global"]["followed_up"] == 2


class TestPhase4cHardening:
    """Tests for Phase 4c: probe_blocked, 24h probe caching & rate limiting, strict DSN delay markers, OOO, and recheck-delays."""

    def test_mailbox_probe_blocked_policy_responses(self, monkeypatch, tmp_path):
        """Test responses with Spamhaus, blacklist, client host blocked, or 5.7.x classify as probe_blocked."""
        cache_file = tmp_path / "probe_cache.json"

        # Mock DNS MX lookup
        monkeypatch.setattr(op, "get_mx_hosts", lambda dom, timeout=7: ["mx.target.com"])

        blocked_cases = [
            (550, b"5.7.1 Service unavailable, Client host [203.0.113.1] blocked using Spamhaus"),
            (554, b"5.7.1 Client host blocked by recipient policy"),
            (550, b"5.7.0 Rejected: IP address is on blacklist"),
            (550, b"5.7.26 Message rejected due to sender reputation policy"),
        ]

        for code, msg_bytes in blocked_cases:
            class MockSMTPBlocked:
                def __init__(self, host, port, timeout=7):
                    pass
                def ehlo(self, name):
                    pass
                def mail(self, sender):
                    pass
                def rcpt(self, recipient):
                    return code, msg_bytes
                def quit(self):
                    pass
                def close(self):
                    pass

            monkeypatch.setattr(op.smtplib, "SMTP", MockSMTPBlocked)
            res = op.verify_email_mailbox_live(f"user_{code}_{len(msg_bytes)}@target.com", cache_file=str(cache_file), min_interval=0)
            assert not res.is_valid, "probe_blocked must be unverified (is_valid=False) to prevent live sends"
            assert res.probe_path == "probe_blocked"
            assert "unverified" in res.reason
            assert "blocked" in res.reason.lower()

    def test_mailbox_probe_caching_24h(self, monkeypatch, tmp_path):
        """Test probe results are cached for 24h and avoid redundant network/SMTP calls."""
        cache_file = tmp_path / "probe_cache.json"
        monkeypatch.setattr(op, "get_mx_hosts", lambda dom, timeout=7: ["mx.target.com"])

        probe_call_count = 0

        class MockSMTPCounting:
            def __init__(self, host, port, timeout=7):
                nonlocal probe_call_count
                probe_call_count += 1
            def ehlo(self, name):
                pass
            def mail(self, sender):
                pass
            def rcpt(self, recipient):
                return 250, b"2.1.5 Recipient OK"
            def quit(self):
                pass
            def close(self):
                pass

        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTPCounting)

        # 1st call: cache miss -> network call
        res1 = op.verify_email_mailbox_live("cached_user@target.com", cache_file=str(cache_file), min_interval=0)
        assert res1.is_valid
        assert res1.probe_path == "probe_250"
        assert probe_call_count == 1

        # 2nd call: cache hit within 24h -> no SMTP call
        res2 = op.verify_email_mailbox_live("cached_user@target.com", cache_file=str(cache_file), min_interval=0)
        assert res2.is_valid
        assert probe_call_count == 1, "Cached result should not trigger SMTP probe"

        # 3rd call: expired cache entry (>24h) -> triggers fresh probe
        cache_data = op.load_verified_emails_cache(str(cache_file))
        old_time = (op.datetime.now(op.timezone.utc) - op.timedelta(hours=25)).isoformat()
        cache_data["cached_user@target.com"]["timestamp"] = old_time
        op.save_verified_emails_cache(cache_data, str(cache_file))

        res3 = op.verify_email_mailbox_live("cached_user@target.com", cache_file=str(cache_file), min_interval=0)
        assert res3.is_valid
        assert probe_call_count == 2, "Expired cache entry should trigger fresh probe"

    def test_mailbox_probe_rate_limiting(self, monkeypatch, tmp_path):
        """Test probes enforce minimum interval between live network requests."""
        cache_file = tmp_path / "probe_cache.json"
        monkeypatch.setattr(op, "get_mx_hosts", lambda dom, timeout=7: ["mx.target.com"])

        class MockSMTPSimple:
            def __init__(self, host, port, timeout=7):
                pass
            def ehlo(self, name):
                pass
            def mail(self, sender):
                pass
            def rcpt(self, recipient):
                return 250, b"Recipient OK"
            def quit(self):
                pass
            def close(self):
                pass

        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTPSimple)

        sleep_calls = []
        monkeypatch.setattr(op.time, "sleep", lambda secs: sleep_calls.append(secs))

        # Set last probe time to 1 second ago
        op._LAST_MAILBOX_PROBE_TIME = op.time.time() - 1.0
        op.verify_email_mailbox_live("user1@target.com", cache_file=str(cache_file), min_interval=5.0)

        assert len(sleep_calls) == 1
        assert 3.5 <= sleep_calls[0] <= 4.1

    def test_delivery_delay_strict_dsn_markers(self):
        """Test delivery_delay matches only strict DSN markers and rejects bare 'delayed' text."""
        # 1. DSN marker in subject
        cat1, _ = op.classify_inbound_message(
            subject="Delivery Status Notification (Delay)",
            body="Message delivery has encountered a temporary problem.",
            from_addr="mailer-daemon@googlemail.com"
        )
        assert cat1 == "delivery_delay"

        # 2. Status: 4.x.x marker
        cat2, _ = op.classify_inbound_message(
            subject="Mail Delivery Problem",
            body="Action: failed\r\nStatus: 4.4.7 (delivery expired)",
            from_addr="mailer-daemon@mail.server.net"
        )
        assert cat2 == "delivery_delay"

        # 3. 'will keep trying' marker
        cat3, _ = op.classify_inbound_message(
            subject="Delivery problem",
            body="The server will keep trying to deliver your message for another 48 hours.",
            from_addr="postmaster@outbound.net"
        )
        assert cat3 == "delivery_delay"

        # 4. 'temporary failure' marker
        cat4, _ = op.classify_inbound_message(
            subject="Delivery report",
            body="Encountered temporary failure connecting to recipient MTA.",
            from_addr="mailer-daemon@mta.com"
        )
        assert cat4 == "delivery_delay"

        # 5. Bare 'delayed' in normal email must NOT classify as delivery_delay
        cat5, _ = op.classify_inbound_message(
            subject="Re: Dashboard Proposal",
            body="Sorry my reply was delayed. We are interested, what are your fees?",
            from_addr="ceo@prospectclinic.com"
        )
        assert cat5 != "delivery_delay"
        assert cat5 in ["interested", "pricing"]

    def test_out_of_office_classified_as_auto_reply(self):
        """Test out of office text always classifies as auto_reply even from noreply senders."""
        # OOO in subject
        cat1, _ = op.classify_inbound_message(
            subject="Automatic reply: Out of office until next week",
            body="I am away from my desk on annual leave. Contact support@company.com.",
            from_addr="noreply@company.com"
        )
        assert cat1 == "auto_reply"

        # OOO in body
        cat2, _ = op.classify_inbound_message(
            subject="Re: Quick question",
            body="Thank you for your message. I am currently out of the office with limited access to email.",
            from_addr="doctor@clinic.in"
        )
        assert cat2 == "auto_reply"

    def test_recheck_delays_command(self, tmp_path):
        """Test recheck_delivery_delays lists delay notices older than 72h with no subsequent resolution."""
        log_file = tmp_path / "outreach_log_delays.csv"
        now_dt = op.get_ist_now()

        old_unresolved_time = (now_dt - op.timedelta(hours=85)).isoformat()
        old_resolved_time = (now_dt - op.timedelta(hours=80)).isoformat()
        resolved_after_time = (now_dt - op.timedelta(hours=60)).isoformat()
        recent_time = (now_dt - op.timedelta(hours=20)).isoformat()

        with open(log_file, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.OUTREACH_LOG_FIELDS)
            writer.writeheader()
            # 1. Delay notice older than 72h with no subsequent event -> should be listed
            writer.writerow({
                "timestamp": old_unresolved_time,
                "recipient_email": "pending_delay@test.com",
                "business_name": "Pending Clinic",
                "segment": "clinics",
                "email_type": "inbox_sync:delivery_delay",
                "subject": "Delivery Status Notification (Delay)",
                "status": "delivery_delay",
                "error_message": "[other] transient failure: 4.4.1",
            })
            # 2. Delay notice older than 72h with subsequent resolution (bounced) -> should be excluded
            writer.writerow({
                "timestamp": old_resolved_time,
                "recipient_email": "resolved_delay@test.com",
                "business_name": "Resolved Agency",
                "segment": "agencies",
                "email_type": "inbox_sync:delivery_delay",
                "subject": "Delivery Status Notification (Delay)",
                "status": "delivery_delay",
                "error_message": "[other] transient failure: 4.4.1",
            })
            writer.writerow({
                "timestamp": resolved_after_time,
                "recipient_email": "resolved_delay@test.com",
                "business_name": "Resolved Agency",
                "segment": "agencies",
                "email_type": "inbox_sync:bounce_permanent",
                "subject": "Undeliverable Mail",
                "status": "bounced",
                "error_message": "[invalid mailbox] 550 5.1.1 user unknown",
            })
            # 3. Delay notice younger than 72h (< 72h) -> should be excluded
            writer.writerow({
                "timestamp": recent_time,
                "recipient_email": "recent_delay@test.com",
                "business_name": "Recent Clinic",
                "segment": "clinics",
                "email_type": "inbox_sync:delivery_delay",
                "subject": "Delivery Status Notification (Delay)",
                "status": "delivery_delay",
                "error_message": "[other] will keep trying",
            })

        unresolved = op.recheck_delivery_delays(log_filepath=str(log_file), max_age_hours=72.0)
        assert len(unresolved) == 1
        assert unresolved[0]["recipient_email"] == "pending_delay@test.com"
        assert unresolved[0]["business_name"] == "Pending Clinic"
        assert unresolved[0]["age_hours"] >= 72.0


class TestPhase4dHousekeeping:
    """Tests for Phase 4d: manual-update command, join against outreach_log, and root cache isolation."""

    def test_root_cache_isolation(self, tmp_path, monkeypatch):
        """Confirm that tests never write to the real verified_emails_cache.json in the project root."""
        root_cache = "verified_emails_cache.json"
        initial_hash = None
        if os.path.exists(root_cache):
            with open(root_cache, "rb") as f:
                initial_hash = op.hashlib.sha256(f.read()).hexdigest()

        # Monkeypatch MX lookup
        monkeypatch.setattr(op, "get_mx_hosts", lambda dom, **kwargs: ["mx.isolate.com"])

        class MockSMTP:
            def __init__(self, host, port, timeout=7): pass
            def ehlo(self, name): pass
            def mail(self, sender): pass
            def rcpt(self, recipient): return 250, b"OK"
            def quit(self): pass
            def close(self): pass

        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTP)

        # Call verify_email_mailbox_live with default arguments (no explicit cache_file)
        res = op.verify_email_mailbox_live("isolation_test@isolate.com", min_interval=0)
        assert res.is_valid

        # Verify that op.VERIFIED_EMAILS_CACHE points inside tmp_path
        assert str(tmp_path) in op.VERIFIED_EMAILS_CACHE

        # Verify root_cache file hash is identical (or does not exist)
        if initial_hash:
            with open(root_cache, "rb") as f:
                final_hash = op.hashlib.sha256(f.read()).hexdigest()
            assert final_hash == initial_hash, "Real project root verified_emails_cache.json was modified!"

    def test_update_manual_outreach_joined_fields(self, tmp_path):
        """Test joining manual_outreach.csv against outreach_log.csv produces accurate counts and fields."""
        manual_file = tmp_path / "manual_outreach.csv"
        log_file = tmp_path / "outreach_log.csv"

        with open(manual_file, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.MANUAL_OUTREACH_FIELDS)
            writer.writeheader()
            writer.writerow({
                "business_name": "Emailed Clinic",
                "segment_guess": "clinics",
                "email": "emailed@clinic.com",
            })
            writer.writerow({
                "business_name": "Bounced Agency",
                "segment_guess": "agencies",
                "email": "bounced@agency.com",
            })
            writer.writerow({
                "business_name": "Fresh Studio",
                "segment_guess": "clinics",
                "email": "fresh@studio.com",
            })

        with open(log_file, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.OUTREACH_LOG_FIELDS)
            writer.writeheader()
            writer.writerow({
                "timestamp": "2026-10-01T10:00:00+05:30",
                "recipient_email": "emailed@clinic.com",
                "email_type": "initial",
                "status": "sent",
            })
            writer.writerow({
                "timestamp": "2026-10-01T10:05:00+05:30",
                "recipient_email": "bounced@agency.com",
                "email_type": "initial",
                "status": "bounced",
            })

        total, emailed_cnt, bounced_cnt, fresh_cnt = op.update_manual_outreach_joined_fields(
            manual_filepath=str(manual_file),
            log_filepath=str(log_file)
        )

        assert total == 3
        assert emailed_cnt == 2
        assert bounced_cnt == 1
        assert fresh_cnt == 1

        with open(manual_file, "r", encoding="utf-8") as f:
            rows = list(op.csv.DictReader(f))

        row_map = {r["email"]: r for r in rows}
        assert row_map["emailed@clinic.com"]["already_emailed"] == "yes"
        assert row_map["emailed@clinic.com"]["bounced"] == "no"
        assert row_map["emailed@clinic.com"]["last_contacted"] == "2026-10-01T10:00:00+05:30"

        assert row_map["bounced@agency.com"]["already_emailed"] == "yes"
        assert row_map["bounced@agency.com"]["bounced"] == "yes"
        assert row_map["bounced@agency.com"]["last_contacted"] == "2026-10-01T10:05:00+05:30"

        assert row_map["fresh@studio.com"]["already_emailed"] == "no"
        assert row_map["fresh@studio.com"]["bounced"] == "no"
        assert row_map["fresh@studio.com"]["last_contacted"] == ""

    def test_update_manual_lead_command(self, tmp_path):
        """Test update_manual_lead modifies only specified fields for targeted row."""
        manual_file = tmp_path / "manual_outreach.csv"

        with open(manual_file, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.MANUAL_OUTREACH_FIELDS)
            writer.writeheader()
            writer.writerow({
                "business_name": "Alpha Clinic",
                "segment_guess": "clinics",
                "email": "alpha@clinic.com",
                "phone": "",
                "whatsapp": "",
                "channel": "",
                "manual_status": "",
                "why_it_fits": "Dental care",
            })
            writer.writerow({
                "business_name": "Beta Agency",
                "segment_guess": "agencies",
                "email": "beta@agency.com",
                "phone": "99999",
                "whatsapp": "",
                "channel": "",
                "manual_status": "",
                "why_it_fits": "SEO agency",
            })

        # Update Alpha Clinic with valid status
        ok = op.update_manual_lead(
            email="alpha@clinic.com",
            channel="whatsapp",
            status="call_booked",
            phone="+919876543210",
            note="Spoke with Dr. Sharma",
            manual_filepath=str(manual_file)
        )
        assert ok

        # Reject invalid status
        bad_ok = op.update_manual_lead(
            email="alpha@clinic.com",
            channel="whatsapp",
            status="random_bad_status",
            manual_filepath=str(manual_file)
        )
        assert not bad_ok

        with open(manual_file, "r", encoding="utf-8") as f:
            rows = list(op.csv.DictReader(f))

        row_alpha = next(r for r in rows if r["email"] == "alpha@clinic.com")
        assert row_alpha["channel"] == "whatsapp"
        assert row_alpha["phone"] == "+919876543210"
        assert row_alpha["whatsapp"] == "+919876543210"
        assert row_alpha["manual_status"] == "call_booked"
        assert row_alpha["note"] == "Spoke with Dr. Sharma"
        assert row_alpha["why_it_fits"] == "Dental care"

        # Ensure Beta Agency is untouched
        row_beta = next(r for r in rows if r["email"] == "beta@agency.com")
        assert row_beta["phone"] == "99999"
        assert row_beta["channel"] == ""
        assert row_beta["manual_status"] == ""


class TestPhase4eManualOutreach:
    """Tests for Phase 4e: manual-add duplicate checks, manual_status whitelist, and manual-report."""

    def test_manual_status_whitelist_validation(self, tmp_path):
        """Test that manual_status strictly enforces the 10 allowed values and --note writes only to note."""
        manual_file = tmp_path / "manual_outreach.csv"
        with open(manual_file, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.MANUAL_OUTREACH_FIELDS)
            writer.writeheader()
            writer.writerow({
                "business_name": "Test Biz",
                "segment_guess": "agencies",
                "email": "test@biz.com",
                "channel": "",
                "manual_status": "new",
                "note": "",
            })

        for valid_st in op.VALID_MANUAL_STATUSES:
            res = op.update_manual_lead(
                email="test@biz.com",
                channel="email",
                status=valid_st,
                note=f"Note for {valid_st}",
                manual_filepath=str(manual_file)
            )
            assert res
            with open(manual_file, "r", encoding="utf-8") as f:
                row = next(r for r in op.csv.DictReader(f) if r["email"] == "test@biz.com")
            assert row["manual_status"] == valid_st
            assert row["note"] == f"Note for {valid_st}"

        # Test rejected statuses
        for invalid_st in ["in_progress", "unknown", "flagged", "closed_won"]:
            res = op.update_manual_lead(
                email="test@biz.com",
                channel="email",
                status=invalid_st,
                manual_filepath=str(manual_file)
            )
            assert not res

    def test_manual_add_duplicate_and_dnc_rejection(self, tmp_path):
        """Test manual-add duplicate checks against outreach_log, leads*.csv, and DNC suppression lists."""
        manual_file = tmp_path / "manual_outreach.csv"
        log_file = tmp_path / "outreach_log.csv"
        lead_file = tmp_path / "leads_custom.csv"

        # Create log file with existing send and opt-out
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.OUTREACH_LOG_FIELDS)
            writer.writeheader()
            writer.writerow({
                "timestamp": "2026-10-01T10:00:00+05:30",
                "recipient_email": "logged@client.com",
                "email_type": "initial",
                "status": "sent",
            })
            writer.writerow({
                "timestamp": "2026-10-02T10:00:00+05:30",
                "recipient_email": "optout@client.com",
                "email_type": "inbox_sync:unsubscribe",
                "status": "unsubscribed",
            })

        # Create leads file with existing lead
        with open(lead_file, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            writer.writeheader()
            writer.writerow({
                "business_name": "Custom Lead",
                "segment": "clinics",
                "website": "https://leadexists.com",
                "email": "lead@leadexists.com",
                "status": "contacted_1",
            })

        # 1. Success case: new unique lead
        ok = op.add_manual_lead(
            business="Fresh Dental Care",
            segment="clinics",
            website="https://freshdentalblr.com",
            phone="+91 98888 77777",
            whatsapp="+91 98888 77777",
            email="info@freshdentalblr.com",
            source="manual_referral",
            manual_filepath=str(manual_file),
            log_filepath=str(log_file),
            leads_files=[str(lead_file)]
        )
        assert ok

        with open(manual_file, "r", encoding="utf-8") as f:
            rows = list(op.csv.DictReader(f))
        assert len(rows) == 1
        r = rows[0]
        assert r["business_name"] == "Fresh Dental Care"
        assert r["segment_guess"] == "clinics"
        assert r["email"] == "info@freshdentalblr.com"
        assert r["phone"] == "+919888877777"
        assert r["whatsapp"] == "+919888877777"
        assert r["already_emailed"] == "no"
        assert r["bounced"] == "no"
        assert r["manual_status"] == "new"

        # 2. Reject duplicate email in outreach_log
        rej1 = op.add_manual_lead(
            business="Duplicate Email",
            segment="clinics",
            website="https://otherdomain.com",
            email="logged@client.com",
            manual_filepath=str(manual_file),
            log_filepath=str(log_file),
            leads_files=[str(lead_file)]
        )
        assert not rej1

        # 3. Reject duplicate domain in leads file
        rej2 = op.add_manual_lead(
            business="Duplicate Domain",
            segment="clinics",
            website="https://leadexists.com/contact",
            email="newemail@leadexists.com",
            manual_filepath=str(manual_file),
            log_filepath=str(log_file),
            leads_files=[str(lead_file)]
        )
        assert not rej2

        # 4. Reject DNC opt-out email
        rej3 = op.add_manual_lead(
            business="Suppressed Lead",
            segment="gyms",
            website="https://optout.com",
            email="optout@client.com",
            manual_filepath=str(manual_file),
            log_filepath=str(log_file),
            leads_files=[str(lead_file)]
        )
        assert not rej3

        # 5. Reject duplicate in manual_outreach.csv itself
        rej4 = op.add_manual_lead(
            business="Fresh Dental Again",
            segment="clinics",
            website="https://freshdentalblr.com",
            manual_filepath=str(manual_file),
            log_filepath=str(log_file),
            leads_files=[str(lead_file)]
        )
        assert not rej4

    def test_manual_report_counts(self, tmp_path, capsys):
        """Test generate_manual_report tallies statuses, segments, channels and contacts without printing addresses."""
        manual_file = tmp_path / "manual_outreach.csv"
        with open(manual_file, "w", newline="", encoding="utf-8") as f:
            writer = op.csv.DictWriter(f, fieldnames=op.MANUAL_OUTREACH_FIELDS)
            writer.writeheader()
            writer.writerow({
                "business_name": "Biz 1",
                "segment_guess": "agencies",
                "email": "biz1@test.com",
                "phone": "+919999999999",
                "channel": "whatsapp",
                "manual_status": "contacted",
            })
            writer.writerow({
                "business_name": "Biz 2",
                "segment_guess": "clinics",
                "email": "biz2@test.com",
                "phone": "",
                "channel": "call",
                "manual_status": "call_booked",
            })
            writer.writerow({
                "business_name": "Biz 3",
                "segment_guess": "clinics",
                "email": "biz3@test.com",
                "phone": "",
                "channel": "",
                "manual_status": "new",
            })

        rep = op.generate_manual_report(manual_filepath=str(manual_file))
        assert rep["total"] == 3
        assert rep["by_status"]["contacted"] == 1
        assert rep["by_status"]["call_booked"] == 1
        assert rep["by_status"]["new"] == 1
        assert rep["by_segment"]["clinics"] == 2
        assert rep["by_segment"]["agencies"] == 1
        assert rep["by_channel"]["whatsapp"] == 1
        assert rep["by_channel"]["call"] == 1
        assert rep["with_phone_or_whatsapp"] == 1

        out = capsys.readouterr().out
        assert "biz1@test.com" not in out
        assert "+919999999999" not in out
        assert "Total Prospects: 3" in out


class TestPhase4fVerificationAndDedupe:
    """Tests for Phase 4f deduplication rules (a)-(d), Gmail edge cases, leads_phone_only exemption, and reporting."""

    def test_manual_add_rule_a_email_rejection(self, tmp_path, capsys):
        manual_file = tmp_path / "manual_outreach.csv"
        log_file = tmp_path / "outreach_log.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=op.OUTREACH_LOG_FIELDS)
            w.writeheader()
            w.writerow({"recipient_email": "dup@target.com", "business_name": "Dup Co", "status": "sent", "email_type": "initial"})

        ok = op.add_manual_lead(
            business="New Biz",
            segment="agencies",
            website="https://newbiz.com",
            email="dup@target.com",
            manual_filepath=str(manual_file),
            log_filepath=str(log_file),
            leads_files=[]
        )
        assert not ok
        out = capsys.readouterr().out
        assert "Rejected by rule (a) email" in out
        assert "outreach_log.csv" in out

    def test_manual_add_rule_b_phone_rejection(self, tmp_path, capsys):
        manual_file = tmp_path / "manual_outreach.csv"
        leads_file = tmp_path / "leads_test.csv"
        log_file = tmp_path / "outreach_log.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=op.OUTREACH_LOG_FIELDS)
            w.writeheader()
        with open(leads_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            w.writeheader()
            w.writerow({"business_name": "Phone Lead", "phone": "+91 98888 12345", "website": "https://lead1.com"})

        ok = op.add_manual_lead(
            business="Another Biz",
            segment="gyms",
            website="https://anotherbiz.com",
            phone="09888812345",  # Same last 10 digits: 9888812345
            manual_filepath=str(manual_file),
            log_filepath=str(log_file),
            leads_files=[str(leads_file)]
        )
        assert not ok
        out = capsys.readouterr().out
        assert "Rejected by rule (b) phone" in out
        assert "leads_test.csv" in out

    def test_manual_add_rule_c_website_domain_rejection(self, tmp_path, capsys):
        manual_file = tmp_path / "manual_outreach.csv"
        log_file = tmp_path / "outreach_log.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=op.OUTREACH_LOG_FIELDS)
            w.writeheader()
            w.writerow({"recipient_email": "contact@apexpartners.com", "business_name": "Apex", "status": "sent", "email_type": "initial"})

        ok = op.add_manual_lead(
            business="Apex Growth",
            segment="agencies",
            website="https://apexpartners.com/about",  # Domain matches email domain in outreach_log
            email="someone_else@somewhere.com",
            manual_filepath=str(manual_file),
            log_filepath=str(log_file),
            leads_files=[]
        )
        assert not ok
        out = capsys.readouterr().out
        assert "Rejected by rule (c) website domain" in out
        assert "outreach_log.csv" in out

    def test_manual_add_rule_d_business_name_similarity_rejection(self, tmp_path, capsys):
        manual_file = tmp_path / "manual_outreach.csv"
        leads_file = tmp_path / "leads_custom.csv"
        log_file = tmp_path / "outreach_log.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=op.OUTREACH_LOG_FIELDS)
            w.writeheader()
        with open(leads_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            w.writeheader()
            w.writerow({"business_name": "Dr C Jagadeesh's Dental Clinic, The Center for Smile Correction", "website": "https://jagadeesh.com"})

        # Normalization strips Dr, Dental, Clinic, The, Center, etc.
        ok = op.add_manual_lead(
            business="Jagadeesh Dental Clinic",
            segment="clinics",
            website="https://differentdomain123.com",
            email="completely_unique@testdomain.com",
            manual_filepath=str(manual_file),
            log_filepath=str(log_file),
            leads_files=[str(leads_file)]
        )
        assert not ok
        out = capsys.readouterr().out
        assert "Rejected by rule (d) business name" in out
        assert "leads_custom.csv" in out

    def test_gmail_addressed_business_already_emailed_under_another_address(self, tmp_path, capsys):
        manual_file = tmp_path / "manual_outreach.csv"
        log_file = tmp_path / "outreach_log.csv"
        with open(log_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=op.OUTREACH_LOG_FIELDS)
            w.writeheader()
            # Originally emailed under custom domain
            w.writerow({
                "recipient_email": "director@summithealthcare.in",
                "business_name": "Summit Healthcare Clinic",
                "status": "sent",
                "email_type": "initial"
            })

        # Prospect tries to be added with a brand new Gmail address and website
        ok = op.add_manual_lead(
            business="Summit Healthcare",
            segment="clinics",
            website="https://summithealthcare.in",
            email="summithealth.blr@gmail.com",
            manual_filepath=str(manual_file),
            log_filepath=str(log_file),
            leads_files=[]
        )
        assert not ok
        out = capsys.readouterr().out
        assert "Rejected by rule (c) website domain" in out or "Rejected by rule (d) business name" in out
        assert "outreach_log.csv" in out

    def test_leads_phone_only_exemption_rule(self, tmp_path, capsys):
        manual_file = tmp_path / "manual_outreach.csv"
        phone_file = tmp_path / "leads_phone_only.csv"
        log_file = tmp_path / "outreach_log.csv"

        # Create phone-only file with a prospect that has NOT been emailed in outreach_log
        with open(phone_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=["business_name", "email", "business_type", "contact_name", "phone", "context_notes", "contact_method"])
            w.writeheader()
            w.writerow({
                "business_name": "Fresh Studio Gym",
                "email": "",
                "business_type": "gym",
                "phone": "+91 99999 88888",
                "context_notes": "No website listed"
            })

        with open(log_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=op.OUTREACH_LOG_FIELDS)
            w.writeheader()

        # Case A: Not in outreach_log -> leads_phone_only.csv does NOT block manual-add!
        ok = op.add_manual_lead(
            business="Fresh Studio Gym",
            segment="gyms",
            website="https://freshgymblr.com",
            phone="+91 99999 88888",
            manual_filepath=str(manual_file),
            log_filepath=str(log_file),
            leads_files=[str(phone_file)]
        )
        assert ok
        out = capsys.readouterr().out
        assert "Successfully added prospect 'Fresh Studio Gym'" in out

        # Case B: If outreach_log.csv has recorded a send for this prospect, it DOES block!
        with open(log_file, "a", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=op.OUTREACH_LOG_FIELDS)
            w.writerow({
                "recipient_email": "gym@freshgymblr.com",
                "business_name": "Fresh Studio Gym",
                "status": "sent",
                "email_type": "initial"
            })

        manual_file2 = tmp_path / "manual_outreach2.csv"
        ok_blocked = op.add_manual_lead(
            business="Fresh Studio Gym",
            segment="gyms",
            website="https://freshgymblr.com",
            phone="+91 99999 88888",
            manual_filepath=str(manual_file2),
            log_filepath=str(log_file),
            leads_files=[str(phone_file)]
        )
        assert not ok_blocked
        out_blocked = capsys.readouterr().out
        assert "outreach_log.csv" in out_blocked

    def test_report_phone_leads_output_and_counts(self, tmp_path, capsys):
        phone_file = tmp_path / "leads_phone_only.csv"
        log_file = tmp_path / "outreach_log.csv"

        with open(phone_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=["business_name", "email", "business_type", "contact_name", "phone", "context_notes", "contact_method"])
            w.writeheader()
            w.writerow({"business_name": "Blr Gym", "phone": "080 2345 6789", "business_type": "gym"})
            w.writerow({"business_name": "US Dental", "phone": "+1-512-444-5555", "business_type": "dentists"})
            w.writerow({"business_name": "No Phone Clinic", "phone": "", "business_type": "clinic"})

        with open(log_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=op.OUTREACH_LOG_FIELDS)
            w.writeheader()
            w.writerow({"business_name": "Blr Gym", "recipient_email": "blr@gym.com", "status": "sent", "email_type": "initial"})

        rep = op.report_phone_leads(phone_leads_filepath=str(phone_file), log_filepath=str(log_file))
        assert rep["total"] == 3
        assert rep["with_phone"] == 2
        assert rep["indicates_bengaluru"] == 1
        assert rep["by_segment"]["gym"] == 1
        assert rep["by_segment"]["dentists"] == 1
        assert rep["by_segment"]["clinic"] == 1
        assert rep["in_outreach_log"] == 1

        out = capsys.readouterr().out
        assert "Total Rows:                                 3" in out
        assert "Rows with Phone Number:                     2" in out
        assert "Rows whose Stored Data Indicates Bengaluru: 1" in out
        assert "Already in outreach_log.csv:                1 / 3 (33.3%)" in out
        # Assert no phone numbers or prospect names leaked in output
        assert "080 2345 6789" not in out
        assert "+1-512-444-5555" not in out
        assert "Blr Gym" not in out


class TestPhase4gLeadVerificationAndSuppression:
    """Tests for Phase 4g lead verification, RCPT TO handshake, and permanent suppression list."""

    def test_verification_field_in_leads_fields(self):
        assert "verification" in op.LEADS_FIELDS

    def test_bounced_suppression_list_configured(self):
        expected_bounces = {
            "hello@emergedentalstudio.com",
            "info@saartha.com",
            "nidhin@growthhackers.digital",
            "hello@foxymoron.in",
            "info@sankalpnethralaya.com",
            "hello@attnagency.com",
        }
        for email in expected_bounces:
            assert email in op.BOUNCED_SUPPRESSION_EMAILS
            # Verify included in get_global_suppressed_emails
            suppressed = op.get_global_suppressed_emails()
            assert email in suppressed

    def test_verify_single_lead_email_invalid_syntax(self):
        status, reason = op.verify_single_lead_email("not-an-email")
        assert status == "invalid"
        assert "syntax" in reason.lower()

    def test_verify_single_lead_email_no_mx(self, monkeypatch):
        monkeypatch.setattr(op, "get_mx_hosts", lambda domain, timeout=5: [])
        status, reason = op.verify_single_lead_email("contact@nonexistentdomain12345.in")
        assert status == "invalid"
        assert "no dns mx" in reason.lower()

    def test_verify_single_lead_email_550_rcpt_treated_as_invalid(self, monkeypatch):
        class MockSMTP:
            def __init__(self, host, port, timeout=7):
                pass
            def ehlo(self, name):
                return (250, b"OK")
            def mail(self, sender):
                return (250, b"OK")
            def rcpt(self, recipient):
                return (550, b"5.1.1 User unknown NoSuchUser")
            def quit(self):
                pass
            def close(self):
                pass

        monkeypatch.setattr(op, "get_mx_hosts", lambda domain, timeout=5: ["mx.healthycare.in"])
        monkeypatch.setattr(op, "_resolve_mx_host_with_retry", lambda host, timeout=5, retries=1: (True, None))
        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTP)
        status, reason = op.verify_single_lead_email("unknownuser@healthycare.in")
        assert status == "invalid"
        assert "rejected" in reason.lower()

    def test_verify_single_lead_email_timeout_treated_as_unknown(self, monkeypatch):
        def mock_smtp(host, port, timeout=7):
            raise TimeoutError("Connection timed out")

        monkeypatch.setattr(op, "get_mx_hosts", lambda domain, timeout=5: ["mx.healthycare.in"])
        monkeypatch.setattr(op, "_resolve_mx_host_with_retry", lambda host, timeout=5, retries=1: (True, None))
        monkeypatch.setattr(op.smtplib, "SMTP", mock_smtp)
        status, reason = op.verify_single_lead_email("doctor@healthycare.in")
        assert status == "unknown"
        assert "timed out" in reason.lower()

    def test_verify_single_lead_email_greylisting_4xx_treated_as_unknown(self, monkeypatch):
        class MockSMTP:
            def __init__(self, host, port, timeout=7):
                pass
            def ehlo(self, name):
                return (250, b"OK")
            def mail(self, sender):
                return (250, b"OK")
            def rcpt(self, recipient):
                return (450, b"4.2.0 Greylisting active, try again later")
            def quit(self):
                pass
            def close(self):
                pass

        monkeypatch.setattr(op, "get_mx_hosts", lambda domain, timeout=5: ["mx.healthycare.in"])
        monkeypatch.setattr(op, "_resolve_mx_host_with_retry", lambda host, timeout=5, retries=1: (True, None))
        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTP)
        status, reason = op.verify_single_lead_email("greylistuser@healthycare.in")
        assert status == "unknown"
        assert "greylisting" in reason.lower()

    def test_verify_single_lead_email_250_non_catch_all_treated_as_valid(self, monkeypatch):
        op._CATCH_ALL_CACHE.clear()
        class MockSMTP:
            def __init__(self, host, port, timeout=7):
                pass
            def ehlo(self, name):
                return (250, b"OK")
            def mail(self, sender):
                return (250, b"OK")
            def rcpt(self, recipient):
                if "zz_probe_" in recipient:
                    return (550, b"5.1.1 NoSuchUser")
                return (250, b"2.1.5 Recipient OK")
            def quit(self):
                pass
            def close(self):
                pass

        monkeypatch.setattr(op, "get_mx_hosts", lambda domain, timeout=5: ["mx.healthycare.in"])
        monkeypatch.setattr(op, "_resolve_mx_host_with_retry", lambda host, timeout=5, retries=1: (True, None))
        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTP)
        status, reason = op.verify_single_lead_email("frontdesk@healthycare.in")
        assert status == "valid"
        assert "250 ok" in reason.lower()

    def test_verify_single_lead_email_catch_all_returns_unknown(self, monkeypatch):
        op._CATCH_ALL_CACHE.clear()
        class MockSMTPCatchAll:
            def __init__(self, host, port, timeout=7):
                pass
            def ehlo(self, name):
                return (250, b"OK")
            def mail(self, sender):
                return (250, b"OK")
            def rcpt(self, recipient):
                # Accepts all recipients
                return (250, b"2.1.5 Recipient OK")
            def quit(self):
                pass
            def close(self):
                pass

        monkeypatch.setattr(op, "get_mx_hosts", lambda domain, timeout=5: ["mx.catchallbiz.in"])
        monkeypatch.setattr(op, "_resolve_mx_host_with_retry", lambda host, timeout=5, retries=1: (True, None))
        monkeypatch.setattr(op.smtplib, "SMTP", MockSMTPCatchAll)
        status, reason = op.verify_single_lead_email("sales@catchallbiz.in")
        assert status == "unknown"
        assert "catch_all" in reason.lower()
        # Ensure cached for domain
        assert op._CATCH_ALL_CACHE.get("catchallbiz.in") is True

    def test_verify_single_lead_email_unresolvable_mx_returns_invalid(self, monkeypatch):
        monkeypatch.setattr(op, "get_mx_hosts", lambda domain, timeout=5: ["unresolvable-mx.bogusdomain.in"])
        monkeypatch.setattr(op, "_resolve_mx_host_with_retry", lambda host, timeout=5, retries=1: (False, "[Errno 11001] getaddrinfo failed"))
        monkeypatch.setattr(op, "_check_local_dns_health", lambda: True)
        status, reason = op.verify_single_lead_email("info@bogusdomain.in")
        assert status == "invalid"
        assert reason == "no resolvable MX host"

    def test_verify_single_lead_email_transient_dns_failure_returns_unknown(self, monkeypatch):
        monkeypatch.setattr(op, "get_mx_hosts", lambda domain, timeout=5: ["transient-mx.slowdns.in"])
        monkeypatch.setattr(op, "_resolve_mx_host_with_retry", lambda host, timeout=5, retries=1: (None, "dns_timeout"))
        status, reason = op.verify_single_lead_email("info@slowdns.in")
        assert status == "unknown"
        assert "transient" in reason.lower()

    def test_get_eligible_leads_require_verified_filter(self):
        leads = [
            {"business_name": "Valid Lead", "email": "valid@lead.com", "segment": "clinics", "status": "new", "website": "https://lead.com", "verification": "valid"},
            {"business_name": "Invalid Lead", "email": "invalid@lead.com", "segment": "clinics", "status": "new", "website": "https://lead.com", "verification": "invalid"},
            {"business_name": "Unknown Lead", "email": "unknown@lead.com", "segment": "clinics", "status": "new", "website": "https://lead.com", "verification": "unknown"},
            {"business_name": "Unverified Lead", "email": "unverif@lead.com", "segment": "clinics", "status": "new", "website": "https://lead.com", "verification": ""},
        ]
        # require_verified=False allows all 4 (subject to other standard checks)
        # require_verified=True only allows verification == 'valid'
        eligible_all = op.get_eligible_leads(leads, allowed_cities=[], require_verified=False)
        assert len(eligible_all) == 4

        eligible_valid_only = op.get_eligible_leads(leads, allowed_cities=[], require_verified=True)
        assert len(eligible_valid_only) == 1
        assert eligible_valid_only[0]["business_name"] == "Valid Lead"

    def test_verify_leads_command_does_not_change_status(self, tmp_path, monkeypatch):
        dummy_leads_file = tmp_path / "leads.csv"
        leads_data = [
            {"business_name": "Good Biz", "email": "good@biz.com", "segment": "clinics", "status": "new", "website": "https://good.com"},
            {"business_name": "Bad Biz", "email": "bad@biz.com", "segment": "clinics", "status": "new", "website": "https://bad.com"},
        ]
        with open(dummy_leads_file, "w", newline="", encoding="utf-8") as f:
            w = op.csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            w.writeheader()
            for r in leads_data:
                w.writerow(r)

        def mock_verify(email, timeout=7):
            if "good" in email:
                return "valid", "250 OK"
            return "invalid", "550 NoSuchUser"

        monkeypatch.setattr(op, "verify_single_lead_email", mock_verify)
        results = op.verify_leads_command(filepath=str(dummy_leads_file))

        # Check in-memory results
        assert len(results["valid"]) == 1
        assert len(results["invalid"]) == 1

        # Check persisted file
        reloaded = op.load_leads(str(dummy_leads_file))
        assert len(reloaded) == 2
        for r in reloaded:
            # STATUS MUST REMAIN 'new'
            assert r["status"] == "new"

        good_lead = next(r for r in reloaded if r["business_name"] == "Good Biz")
        bad_lead = next(r for r in reloaded if r["business_name"] == "Bad Biz")
        assert good_lead["verification"] == "valid"
        assert bad_lead["verification"] == "invalid"


class TestPhase4hNewTemplates:
    """Tests for updated initial-email templates (manufacturers, retail, agencies)."""

    def test_subjects_lowercase_under_7_words_and_no_pitch_words(self):
        forbidden_pitch = ["stop", "automate", "fewer", "cut"]
        for seg in ["manufacturers", "retail", "agencies"]:
            variants = op.SUBJECT_VARIANTS[seg]
            for v in variants:
                assert v == v.lower(), f"Subject '{v}' is not lowercase"
                assert op.count_words(v) < 7, f"Subject '{v}' is not under 7 words ({op.count_words(v)} words)"
                v_words = [w.strip("?,.:;!") for w in v.lower().split()]
                for bad in forbidden_pitch:
                    assert bad not in v_words, f"Subject '{v}' contains forbidden pitch word '{bad}'"

    def test_greeting_first_name_and_fallback(self):
        # Lead with contact name
        lead1 = {"business_name": "TTP Tech", "contact_name": "Deepak Sharma", "segment": "manufacturers"}
        assert op.get_initial_greeting(lead1) == "Hi Deepak,"

        # Lead with first_name
        lead2 = {"business_name": "TTP Tech", "first_name": "karan", "segment": "manufacturers"}
        assert op.get_initial_greeting(lead2) == "Hi Karan,"

        # Lead without contact name
        lead3 = {"business_name": "TTP Tech", "segment": "manufacturers"}
        assert op.get_initial_greeting(lead3) == "Hi,"

    def test_credibility_line_in_intro_sentence(self, monkeypatch):
        # Default empty CREDIBILITY_LINE
        monkeypatch.setattr(op, "CREDIBILITY_LINE", "")
        assert op.get_intro_sentence() == "I'm Karan, a freelance data analyst."

        # Filled in CREDIBILITY_LINE
        monkeypatch.setattr(op, "CREDIBILITY_LINE", "helping growing operations cut down spreadsheet hours")
        assert op.get_intro_sentence() == "I'm Karan, a freelance data analyst helping growing operations cut down spreadsheet hours."

        monkeypatch.setattr(op, "CREDIBILITY_LINE", "I've built reporting systems for high-growth operations.")
        assert op.get_intro_sentence() == "I'm Karan, a freelance data analyst—I've built reporting systems for high-growth operations."

    def test_email_body_under_90_words_and_no_demo_link(self, monkeypatch):
        monkeypatch.setenv("SAMPLE_DASHBOARD_URL", "https://sheetboltanalytics.netlify.app/#top")
        monkeypatch.setenv("SITE_URL", "https://sheetboltanalytics.netlify.app")
        monkeypatch.setenv("OUTREACH_SUPPORT_EMAIL", "sheetbolt.analytics@gmail.com")

        for seg in ["manufacturers", "retail", "agencies"]:
            lead = {"business_name": "Acme Co", "segment": seg, "email": "info@acme.co"}
            subj, body = op.generate_email(lead, email_type="initial")

            body_only = body.split("Best,\n")[0].strip()
            assert op.count_words(body_only) < 90
            assert op.count_words(subj) < 7

            # Demo link must NOT be in body
            assert "https://sheetboltanalytics.netlify.app/#top" not in body
            assert "Here's an example of what I build" not in body

            # Website must be in signature only
            assert "https://sheetboltanalytics.netlify.app" in body
            assert "Reply STOP and I won't email again." in body

            # Offer text present
            assert "I'd love to build a free sample tracker using one of your current sheets" in body
            assert "feel free to remove any sensitive columns" in body

    def test_ad_reporting_only_in_agencies(self):
        for seg in ["manufacturers", "retail", "agencies"]:
            lead = {"business_name": "Acme", "segment": seg, "email": "info@acme.com"}
            _, body = op.generate_email(lead, email_type="initial")
            if seg == "agencies":
                assert "ad" in body.lower()
            else:
                assert "ad " not in body.lower()
                assert "roas" not in body.lower()
                assert "campaign" not in body.lower()


class TestPhase4iExcludedEducationSegments:
    """Tests for segment allowlist and exclusion of education/school leads."""

    def test_allowed_target_segments_allowlist(self):
        assert "coaching" not in op.ALLOWED_TARGET_SEGMENTS
        assert "education" not in op.ALLOWED_TARGET_SEGMENTS
        for expected in ["manufacturers", "retail", "agencies", "accounting", "gyms", "clinics"]:
            assert expected in op.ALLOWED_TARGET_SEGMENTS

    def test_is_educational_domain(self):
        # Educational domains (.edu.in, .ac.in, .edu, .ac.*)
        assert op.is_educational_domain("sjcc.edu.in") is True
        assert op.is_educational_domain("info@sjcc.edu.in") is True
        assert op.is_educational_domain("iisc.ac.in") is True
        assert op.is_educational_domain("oxford.ac.uk") is True
        assert op.is_educational_domain("tokyo.ac.jp") is True
        assert op.is_educational_domain("harvard.edu") is True
        assert op.is_educational_domain("http://shghs.edu.in/home") is True

        # Non-educational domains
        assert op.is_educational_domain("hansagreen.com") is False
        assert op.is_educational_domain("theregistryofsarees.com") is False
        assert op.is_educational_domain("ttpradiators.com") is False
        assert op.is_educational_domain("acme.co.in") is False
        assert op.is_educational_domain("actech.com") is False

    def test_is_educational_lead(self):
        # Lead in excluded segment
        lead_coach = {"business_name": "Test Academy", "segment": "coaching", "email": "test@test.com", "website": "http://test.com"}
        is_blocked, reason = op.is_educational_lead(lead_coach)
        assert is_blocked is True
        assert "coaching" in reason

        # Lead with .edu.in domain
        lead_edu = {"business_name": "Test Agency", "segment": "agencies", "email": "info@test.edu.in", "website": "http://test.com"}
        is_blocked, reason = op.is_educational_lead(lead_edu)
        assert is_blocked is True
        assert ".edu.in" in reason

        # Lead with .ac.uk domain
        lead_ac = {"business_name": "Test Shop", "segment": "retail", "email": "shop@test.ac.uk", "website": "http://test.ac.uk"}
        is_blocked, reason = op.is_educational_lead(lead_ac)
        assert is_blocked is True
        assert ".ac." in reason

        # Lead with school in name
        lead_school = {"business_name": "National Public School", "segment": "manufacturers", "email": "office@nps.com", "website": "http://nps.com"}
        is_blocked, reason = op.is_educational_lead(lead_school)
        assert is_blocked is True
        assert "school" in reason.lower()

        # Legitimate private business lead
        lead_legit = {"business_name": "TTP Tech", "segment": "manufacturers", "email": "sales@ttp.com", "website": "http://ttp.com"}
        is_blocked, reason = op.is_educational_lead(lead_legit)
        assert is_blocked is False
        assert reason == ""

    def test_get_eligible_leads_blocks_excluded_segments_and_edu_domains(self, monkeypatch):
        leads = [
            {"business_name": "St. Joseph's", "segment": "coaching", "email": "info@sjcc.edu.in", "status": "new", "website": "http://sjcc.edu.in", "verification": "valid"},
            {"business_name": "Christ Univ", "segment": "coaching", "email": "mail@christ.in", "status": "new", "website": "http://christ.in", "verification": "valid"},
            {"business_name": "Good Retail", "segment": "retail", "email": "contact@goodretail.com", "status": "new", "website": "http://goodretail.com", "verification": "valid"},
        ]
        monkeypatch.setattr(op, "get_global_suppressed_emails", lambda *args, **kwargs: set())
        monkeypatch.setattr(op, "verify_lead_location", lambda *args, **kwargs: (True, "Location OK"))
        monkeypatch.setattr(op, "check_lead_domain_match", lambda *args, **kwargs: (False, "Match OK"))
        monkeypatch.setattr(op, "check_lead_name_vs_domain", lambda *args, **kwargs: (False, "Match OK"))
        monkeypatch.setattr(op, "verify_email_mailbox_live", lambda *args, **kwargs: (True, "Live OK"))

        eligible = op.get_eligible_leads(leads, require_verified=True)
        emails = [l["email"] for l in eligible]
        assert "info@sjcc.edu.in" not in emails
        assert "mail@christ.in" not in emails
        assert "contact@goodretail.com" in emails

    def test_send_smtp_email_raises_on_educational_lead(self, monkeypatch):
        monkeypatch.setattr(op, "verify_sender_safety", lambda *args, **kwargs: None)
        monkeypatch.setenv("SMTP_PASS", "mock_pass")

        lead = {"business_name": "St Josephs", "email": "info@sjcc.edu.in", "segment": "coaching"}
        import pytest
        with pytest.raises(ValueError, match="Send blocked"):
            op.send_smtp_email("info@sjcc.edu.in", "subject", "body", lead=lead)

    def test_find_leads_rejects_excluded_segment(self):
        import pytest
        with pytest.raises(ValueError, match="is excluded"):
            op.find_leads_for_segment("coaching")

    def test_import_leads_skips_educational_and_school_leads(self, tmp_path):
        import csv
        src_file = tmp_path / "imported.csv"
        target_file = tmp_path / "leads_target.csv"

        leads_to_import = [
            {"business_name": "St Josephs College", "segment": "coaching", "website": "http://sjcc.edu.in", "email": "info@sjcc.edu.in", "status": "new"},
            {"business_name": "Oxford University", "segment": "retail", "website": "http://ox.ac.uk", "email": "info@ox.ac.uk", "status": "new"},
            {"business_name": "Clean Manufacturer", "segment": "manufacturers", "website": "http://cleanmfg.com", "email": "sales@cleanmfg.com", "status": "new"},
        ]
        with open(src_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            writer.writeheader()
            for r in leads_to_import:
                writer.writerow({k: r.get(k, "") for k in op.LEADS_FIELDS})

        # Initialize empty target file
        with open(target_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=op.LEADS_FIELDS)
            writer.writeheader()

        imported_count = op.import_leads_command(str(src_file), target_filepath=str(target_file))
        assert imported_count == 1

        final_rows = op.load_leads(str(target_file))
        assert len(final_rows) == 1
        assert final_rows[0]["business_name"] == "Clean Manufacturer"
        assert final_rows[0]["email"] == "sales@cleanmfg.com"











