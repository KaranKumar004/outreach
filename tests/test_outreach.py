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
        assert cap3 == 25


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

            assert "Hi Zenith team," in body
            assert op.SEGMENT_COPY[seg]["problem"] in body
            assert op.SEGMENT_COPY[seg]["offer"] in body
            assert expected_sample in body
            assert expected_cta in body
            assert "Sheetbolt · Automate the mess" in body

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
        assert c4 == "bounce_notice"

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
        res2 = op.sync_inbox(log_filepath=str(dummy_log), imap_conn=MockIMAP())
        assert res2["skipped_already_synced"] == 1
        assert res2["unsubscribes"] == 0





