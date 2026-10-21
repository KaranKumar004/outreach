"""
tests/test_website_outreach.py — Comprehensive test suite for Website Creation Outreach Setup.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Add website_outreach folder to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "website_outreach")))

from whatsapp_templates import (
    normalize_phone_number,
    clean_business_name_for_msg,
    get_whatsapp_message,
    generate_wa_link,
    WHATSAPP_PITCHES,
)
from web_lead_finder import (
    validate_email,
    get_lead_id,
    BUSINESS_TAG_MAP,
)
from web_outreach_pipeline import (
    clean_business_name,
    generate_email_content,
    pick_subject,
    EMAIL_TEMPLATES,
    get_daily_send_cap,
)


class TestPhoneNormalization:
    def test_indian_10_digit_phone(self):
        result = normalize_phone_number("9876543210", default_country="IN")
        assert result == "919876543210"

    def test_indian_phone_with_leading_zero(self):
        result = normalize_phone_number("09876543210", default_country="IN")
        assert result == "919876543210"

    def test_indian_phone_with_plus_91_and_spaces(self):
        result = normalize_phone_number("+91 98765 43210", default_country="IN")
        assert result == "919876543210"

    def test_us_phone_normalization(self):
        result = normalize_phone_number("(512) 555-0123", default_country="US")
        assert result == "15125550123"

    def test_empty_or_invalid_phone(self):
        assert normalize_phone_number("") == ""
        assert normalize_phone_number("abc-def") == ""

    def test_multiple_phone_numbers_separated_by_semicolon_or_slash(self):
        result = normalize_phone_number("+917786009595;+917786009696", default_country="IN")
        assert result == "917786009595"
        result2 = normalize_phone_number("9876543210 / 9123456780", default_country="IN")
        assert result2 == "919876543210"


class TestWhatsAppGeneration:
    def test_clean_business_name_strips_legal_suffixes(self):
        assert clean_business_name_for_msg("Nexus Media Pvt Ltd") == "Nexus Media"
        assert clean_business_name_for_msg("Apex Solutions LLP") == "Apex Solutions"
        assert clean_business_name_for_msg("Zenith Fitness LLC") == "Zenith Fitness"

    def test_whatsapp_message_contains_business_name(self):
        msg = get_whatsapp_message("Blue Peak Studio", segment="agency")
        assert "Blue Peak Studio" in msg
        assert "website" in msg.lower()

    def test_generate_wa_link(self):
        msg = "Hi Blue Peak Studio team!"
        link = generate_wa_link("9876543210", msg, default_country="IN")
        assert link.startswith("https://wa.me/919876543210?text=")
        assert "Blue%20Peak" in link

    def test_all_whatsapp_segments_have_valid_pitches(self):
        segments = ["agency", "clinic", "gym", "salon", "restaurant", "accounting", "retail", "general"]
        for seg in segments:
            assert seg in WHATSAPP_PITCHES
            msg = get_whatsapp_message("Test Co", segment=seg)
            assert len(msg) > 30


class TestEmailTemplatesAndConstraints:
    def test_all_subjects_under_8_words(self):
        for segment, config in EMAIL_TEMPLATES.items():
            for subject_pattern in config["subjects"]:
                rendered = subject_pattern.format(clean_name="Acme Agency")
                word_count = len(rendered.split())
                assert word_count < 8, f"Subject too long ({word_count} words): '{rendered}' in segment '{segment}'"

    def test_all_email_bodies_under_90_words(self):
        for segment, config in EMAIL_TEMPLATES.items():
            rendered = config["body"].format(
                clean_name="Acme Agency",
                sender_name="Karan",
                portfolio_url="https://example.com"
            )
            word_count = len(rendered.split())
            assert word_count < 90, f"Body too long ({word_count} words) in segment '{segment}':\n{rendered}"

    def test_no_spam_keywords_in_subjects(self):
        spam_triggers = ["free", "$$$", "guaranteed", "urgent", "act now", "100%", "risk-free", "winner"]
        for segment, config in EMAIL_TEMPLATES.items():
            for subject_pattern in config["subjects"]:
                subject_lower = subject_pattern.lower()
                for trigger in spam_triggers:
                    assert trigger not in subject_lower, f"Spam trigger '{trigger}' found in subject: '{subject_pattern}'"

    def test_generate_email_content_returns_valid_triple(self):
        lead = {
            "business_name": "Vertex Digital Agency",
            "segment": "agency",
            "email": "contact@vertexdigital.com"
        }
        subj, txt, html = generate_email_content(lead)
        assert len(subj.split()) < 8
        assert len(txt.split()) < 90
        assert "<html" in html
        assert "Vertex Digital Agency" in txt or "Vertex Digital" in txt


class TestEmailValidation:
    def test_valid_emails(self):
        assert validate_email("contact@acmestudio.in") is True
        assert validate_email("info.support@healthcare-center.com") is True
        assert validate_email("hello@agency.co.uk") is True

    def test_invalid_emails(self):
        assert validate_email("") is False
        assert validate_email("plainaddress") is False
        assert validate_email("@missingusername.com") is False
        assert validate_email("cdn@unpkg.com/library.js") is False
        assert validate_email("user@example.com") is False
        assert validate_email("user@1.2.3") is False


class TestLeadIdentification:
    def test_lead_id_by_email(self):
        lead_id = get_lead_id("Test Business", email="hello@testbiz.com")
        assert lead_id == "email-hello@testbiz.com"

    def test_lead_id_by_phone(self):
        lead_id = get_lead_id("Test Business", phone="+91 (987) 654-3210")
        assert lead_id == "phone-919876543210"

    def test_lead_id_by_name_fallback(self):
        lead_id = get_lead_id("Awesome Clinic")
        assert lead_id.startswith("hash-")


class TestWarmupSchedule:
    def test_warmup_cap_week1(self):
        logs = []
        cap = get_daily_send_cap(logs)
        assert cap == 5

    def test_warmup_cap_week2(self):
        logs = [
            {"timestamp": "2026-10-10T00:00:00Z", "mode": "live", "status": "sent"}
        ]
        # 11 days ago -> Week 2 -> 10 sends/day
        with patch("web_outreach_pipeline.datetime") as mock_dt:
            from datetime import datetime, timezone
            mock_dt.now.return_value = datetime(2026, 10, 21, 0, 0, 0, tzinfo=timezone.utc)
            mock_dt.fromisoformat = datetime.fromisoformat
            cap = get_daily_send_cap(logs)
            assert cap == 10
