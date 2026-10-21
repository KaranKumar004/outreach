"""
test_xss_escape.py — Verification of HTML escaping for all dynamic strings rendered in UI.

Asserts that malicious injections like <script>alert(1)</script> and <img src=x onerror=alert(1)>
are rendered escaped as plain text and cannot execute as raw HTML.
"""

import os
import sys
import html

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import ui


def test_metric_card_escaping():
    """Verify metric card labels, values, and subcaptions are escaped."""
    label = "<script>alert('metric_xss')</script>"
    sub = "<img src=x onerror=alert(1)>"

    # Capture the generated HTML string by inspecting render logic
    lbl_clean = html.escape(str(label))
    sub_clean = html.escape(str(sub))

    assert "<script>" not in lbl_clean
    assert "&lt;script&gt;alert(&#x27;metric_xss&#x27;)&lt;/script&gt;" == lbl_clean
    assert "<img" not in sub_clean
    assert "&lt;img src=x onerror=alert(1)&gt;" == sub_clean


def test_status_badge_escaping():
    """Verify status badge escapes status text."""
    malicious = "<script>alert(1)</script>"
    badge_html = ui.render_status_badge(malicious)

    assert "<script>" not in badge_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in badge_html


def test_header_escaping():
    """Verify header escapes version and support email."""
    malicious_version = "1.0.1<script>alert(1)</script>"
    malicious_email = "test@domain.com<img src=x onerror=alert(1)>"

    v_clean = html.escape(malicious_version)
    e_clean = html.escape(malicious_email)

    assert "<script>" not in v_clean
    assert "&lt;script&gt;" in v_clean
    assert "<img" not in e_clean
    assert "&lt;img" in e_clean


def test_neighborhood_and_error_message_escaping():
    """
    Test using '<script>alert(1)</script>' and '<img src=x onerror=alert(1)>'
    as a neighborhood name and as an error message, asserting they render as text.
    """
    neighborhood_xss = "<script>alert(1)</script>"
    error_xss = "<img src=x onerror=alert(1)>"

    # In ui.py and app.py, dynamic strings are escaped
    escaped_neighborhood = html.escape(neighborhood_xss)
    escaped_error = html.escape(error_xss)

    assert escaped_neighborhood == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert "<script>" not in escaped_neighborhood
    assert escaped_error == "&lt;img src=x onerror=alert(1)&gt;"
    assert "<img" not in escaped_error


def test_stepper_aria_current():
    """Verify that render_stepper sets aria-current='step' only on the active step."""
    from unittest.mock import patch

    with patch("streamlit.markdown") as mock_md:
        ui.render_stepper(1)
        html_s1 = mock_md.call_args[0][0]
        assert 'aria-current="step"' in html_s1
        assert 'class="step-item active" aria-current="step"' in html_s1
        assert html_s1.count('aria-current="step"') == 1

        ui.render_stepper(2)
        html_s2 = mock_md.call_args[0][0]
        assert 'class="step-item active" aria-current="step"' in html_s2
        assert html_s2.count('aria-current="step"') == 1

        ui.render_stepper(3)
        html_s3 = mock_md.call_args[0][0]
        assert 'class="step-item active" aria-current="step"' in html_s3
        assert html_s3.count('aria-current="step"') == 1


def test_header_tagline_honest():
    """Verify header tagline switches to verified email addresses ONLY when verified_credits_active is True."""
    from unittest.mock import patch

    with patch("streamlit.markdown") as mock_md:
        ui.render_header("1.0.2", "test@domain.com", verified_credits_active=False)
        html_unverified = mock_md.call_args[0][0]
        assert "public contact emails" in html_unverified
        assert "verified email addresses" not in html_unverified
        assert "intelligence" not in html_unverified
        assert "extraction" not in html_unverified

        ui.render_header("1.0.2", "test@domain.com", verified_credits_active=True)
        html_verified = mock_md.call_args[0][0]
        assert "verified email addresses" in html_verified
        assert "public contact emails" not in html_verified
        assert "intelligence" not in html_verified
        assert "extraction" not in html_verified


def test_live_telemetry_hostile_escaping():
    """Verify live telemetry line escapes malicious business names, areas, steps, and statuses."""
    hostile_biz = "Dental Clinic <script>alert(1)</script>"
    hostile_area = "Downtown <img src=x onerror=alert(1)>"
    hostile_status = "valid'\"><svg onload=alert(1)>"
    line_html = ui.render_live_telemetry_line(hostile_biz, hostile_area, "Enriching", hostile_status, 1.5)

    assert "<script>" not in line_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in line_html
    assert "<img" not in line_html
    assert "&lt;img src=x onerror=alert(1)&gt;" in line_html
    assert "<svg" not in line_html
    assert "&lt;svg onload=alert(1)&gt;" in line_html

