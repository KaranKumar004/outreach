"""
test_leadcore.py — Unit tests for LocalLeads Kit Core Engine.
"""

import os
import sys
import pytest
import requests
from unittest.mock import patch, MagicMock

# Ensure parent directory is in path so we can import leadcore and config
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import leadcore
import config


# =====================================================================
# 1. Email Validator Tests (Task 3)
# =====================================================================

def test_email_validator_required_rejections():
    """Tests that all required bad email patterns are rejected."""
    rejected = [
        "user@example.com",
        "test@test.com",
        "abc@sentry.wixpress.com",
        "icon@fontawesome.woff",
        "hero-banner@xyz.jpg",
        "logo@2x.png",
        "font@icons.woff2",
        "style@bundle.css",
        "script@app.js",
        "doc@download.pdf",
        "noreply@salonbliss.in",
        "no-reply@store.com",
        "donotreply@domain.org",
        "mailer-daemon@relay.net",
        "splide@3.2.2",
        "user@1.2.3",
        "admin@yourdomain.com",
    ]
    for em in rejected:
        assert not leadcore.validate_email(em), f"Expected {em} to be rejected"


def test_email_validator_required_acceptances():
    """Tests that valid local business emails are accepted."""
    accepted = [
        "info@salonbliss.in",
        "contact@austindentist.com",
        "hello@localgym.co.uk",
        "support@texashvac.org",
        "sales@cleaners.com.au",
    ]
    for em in accepted:
        assert leadcore.validate_email(em), f"Expected {em} to be accepted"


def test_select_best_email():
    """Prefers domain-matched and contact-style emails."""
    candidates = [
        "random_employee@otherdomain.com",
        "admin@gmail.com",
        "info@austindentist.com",
        "billing@austindentist.com",
    ]
    best = leadcore.select_best_email(candidates, "https://www.austindentist.com")
    assert best == "info@austindentist.com"


# =====================================================================
# 2. Phone Extraction & Normalization Tests (Task 4)
# =====================================================================

def test_phone_normalization_required_passes():
    """Tests all required phone strings parse and format properly."""
    cases = [
        ("+91 98450 12345", None, "+919845012345"),
        ("98450 12345", "IN", "+919845012345"),
        ("+91-9845012345", None, "+919845012345"),
        ("098450 12345", "IN", "+919845012345"),
        ("080 4123 4567", "IN", "+918041234567"),
        ("+91 80 4123 4567", None, "+918041234567"),
        ("(512) 555-0134", "US", "+15125550134"),
        ("+1 512 555 0134", None, "+15125550134"),
        ("+44 20 7946 0958", None, "+442079460958"),
        ("020 7946 0958", "GB", "+442079460958"),
    ]
    for raw, region, expected_e164 in cases:
        disp, e164 = leadcore.normalize_phone(raw, region)
        assert bool(disp), f"Failed to get display phone for: {raw} (region={region})"
        assert e164 == expected_e164, f"Expected {expected_e164}, got {e164} for {raw}"


def test_phone_normalization_required_rejections():
    """Tests that timestamps, GA codes, pincodes, and dates are rejected."""
    invalid_cases = [
        ("1690000000123", "IN"),
        ("UA-1234567890", "US"),
        ("560038", "IN"),
        ("2024-05-12", "IN"),
        ("2024/05/12", "US"),
    ]
    for raw, region in invalid_cases:
        disp, e164 = leadcore.normalize_phone(raw, region)
        assert disp == "", f"Expected rejection for: {raw}, but got {disp}"
        assert e164 == "", f"Expected rejection for: {raw}, but got {e164}"


# =====================================================================
# 3. Directory Domains & Search Fallbacks (Task 2)
# =====================================================================

def test_directory_domain_detection():
    """Directory domains are recognized and never treated as business websites."""
    assert leadcore.is_directory_domain("https://www.justdial.com/Bangalore/Salons")
    assert leadcore.is_directory_domain("http://in.linkedin.com/company/sample")
    assert leadcore.is_directory_domain("https://www.facebook.com/mybusiness")
    assert leadcore.is_directory_domain("https://yelp.com/biz/salon-austin")
    assert leadcore.is_directory_domain("https://www.zomato.com/bangalore/restaurants")

    # Real local business domains must NOT be flagged
    assert not leadcore.is_directory_domain("https://www.salonbliss.in")
    assert not leadcore.is_directory_domain("https://austindentalspa.com")


def test_brave_email_snippet_requires_domain_match():
    """Brave email fallback discards emails that do not match the business website domain."""
    # 1. Matching domain -> accepted
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Contact Austin Dentist directly at info@austindentist.com for appointments."
        mock_get.return_value = mock_resp

        email = leadcore.search_email_via_brave(
            "Austin Dentist", "Austin, Texas", "https://www.austindentist.com"
        )
        assert email == "info@austindentist.com"

    # 2. Mismatched domain (e.g. directory or blog email) -> rejected
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Reviewed by reviewer@travelguide.com on local directory."
        mock_get.return_value = mock_resp

        email = leadcore.search_email_via_brave(
            "Austin Dentist", "Austin, Texas", "https://www.austindentist.com"
        )
        assert email == ""


# =====================================================================
# 4. Status Taxonomy & Segregation (Task 1)
# =====================================================================

def test_export_leads_ready_for_email_strictly_valid():
    """Only 'valid' deliverable emails enter leads_ready_for_email.csv."""
    leads = [
        {"business_name": "Biz 1", "email": "valid1@biz.com", "verification_status": "valid"},
        {"business_name": "Biz 2", "email": "valid2@biz.com", "verification_status": "valid"},
        {"business_name": "Biz 3", "email": "unverified@biz.com", "verification_status": "unverified"},
        {"business_name": "Biz 4", "email": "info@guessed.com", "verification_status": "guessed"},
        {"business_name": "Biz 5", "email": "risky@biz.com", "verification_status": "risky"},
        {"business_name": "Biz 6", "email": "invalid@biz.com", "verification_status": "invalid"},
        {"business_name": "Biz 7", "email": "unknown@biz.com", "verification_status": "unknown"},
    ]
    ready = leadcore.export_leads_ready_for_email(leads)
    assert len(ready) == 2
    assert all(r["verification_status"] == "valid" for r in ready)
    assert {r["email"] for r in ready} == {"valid1@biz.com", "valid2@biz.com"}


def test_export_leads_unverified():
    """Unverified emails and guessed emails appear in unverified export."""
    leads = [
        {"business_name": "Biz 1", "email": "valid1@biz.com", "verification_status": "valid"},
        {"business_name": "Biz 2", "email": "unverified@biz.com", "verification_status": "unverified"},
        {"business_name": "Biz 3", "email": "info@guessed.com", "verification_status": "guessed"},
    ]
    unverified = leadcore.export_leads_unverified(leads)
    assert len(unverified) == 2
    assert {r["email"] for r in unverified} == {"unverified@biz.com", "info@guessed.com"}


def test_legacy_status_migration():
    """Old CSV statuses migrate properly with no_email and unknown rules."""
    assert leadcore.migrate_lead_status("unverified (format valid)", email="test@biz.com") == "unverified"
    assert leadcore.migrate_lead_status("format valid", email="test@biz.com") == "unverified"
    assert leadcore.migrate_lead_status("unverified", email="test@biz.com") == "unverified"
    assert leadcore.migrate_lead_status("valid", email="test@biz.com") == "valid"
    assert leadcore.migrate_lead_status("risky", email="test@biz.com") == "risky"
    assert leadcore.migrate_lead_status("catch-all", email="test@biz.com") == "risky"
    assert leadcore.migrate_lead_status("invalid", email="test@biz.com") == "invalid"
    # unknown with email means ZeroBounce returned no verdict
    assert leadcore.migrate_lead_status("unknown", email="test@biz.com") == "unknown"
    # rows with no email MUST be 'no_email', never 'unknown'
    assert leadcore.migrate_lead_status("unknown", email="") == "no_email"
    assert leadcore.migrate_lead_status("no_email", email="") == "no_email"
    assert leadcore.migrate_lead_status("", email="") == "no_email"
    assert leadcore.migrate_lead_status("none", email="") == "no_email"
    assert leadcore.migrate_lead_status("any", context_notes="[Domain placeholder (info@)]", email="info@domain.com") == "guessed"


# =====================================================================
# 5. Deduplication & Shared Email Logic (Task 6)
# =====================================================================

def test_shared_email_kept_in_all_leads_deduped_in_ready_export():
    """
    Two leads sharing the same email are NOT dropped from all leads,
    but only 1 instance is kept in ready_for_email.csv.
    """
    lead_a = {
        "osm_type": "node",
        "osm_id": 101,
        "business_name": "Downtown Branch",
        "email": "shared@chain.com",
        "verification_status": "valid",
        "shared_email": False
    }
    lead_b = {
        "osm_type": "node",
        "osm_id": 102,
        "business_name": "Uptown Branch",
        "email": "shared@chain.com",
        "verification_status": "valid",
        "shared_email": True
    }
    all_leads = [lead_a, lead_b]
    assert len(all_leads) == 2

    # In ready-for-email, email is deduped
    ready = leadcore.export_leads_ready_for_email(all_leads)
    assert len(ready) == 1
    assert ready[0]["business_name"] == "Downtown Branch"


# =====================================================================
# 6. Formula Injection Safety (Task 12)
# =====================================================================

def test_formula_injection_sanitization():
    """Prefixes ' on values starting with =, +, -, @, \\t, \\r."""
    assert leadcore.sanitize_csv_value("=1+1") == "'=1+1"
    assert leadcore.sanitize_csv_value("+44 12345") == "'+44 12345"
    assert leadcore.sanitize_csv_value("-100") == "'-100"
    assert leadcore.sanitize_csv_value("@SUM(A1:B2)") == "'@SUM(A1:B2)"
    assert leadcore.sanitize_csv_value("\tcmd") == "'\tcmd"
    assert leadcore.sanitize_csv_value("Austin Dental") == "Austin Dental"
    assert leadcore.sanitize_csv_value("") == ""
    assert leadcore.sanitize_csv_value(None) == ""


# =====================================================================
# 7. ZeroBounce Halt & Cache Safety (Task 9)
# =====================================================================

def test_zerobounce_halt_on_invalid_key_or_no_credits():
    """ZeroBounce raises ZeroBounceHaltException on 401 or no credits."""
    cache = {}

    # Mock 401 Unauthorized
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp

        with pytest.raises(leadcore.ZeroBounceHaltException):
            leadcore.verify_email_zerobounce("test@austindentist.com", "bad_key", cache)

    # Mock zero credits error response
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"error": "Zero credits remaining"}
        mock_get.return_value = mock_resp

        with pytest.raises(leadcore.ZeroBounceHaltException):
            leadcore.verify_email_zerobounce("test@austindentist.com", "no_credit_key", cache)


def test_zerobounce_does_not_cache_unknown():
    """Unknown or transient API errors are never saved to cache."""
    cache = {}
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "unknown"}
        mock_get.return_value = mock_resp

        status, is_cached = leadcore.verify_email_zerobounce("test@austindentist.com", "valid_key", cache)
        assert status == "unknown"
        assert not is_cached
        assert "test@austindentist.com" not in cache


# =====================================================================
# 8. Cloudflare Decoding & Email De-obfuscation
# =====================================================================

def test_cloudflare_data_cfemail_decoding():
    """Cloudflare data-cfemail XOR strings are decoded into valid emails."""
    # Encode "office@austindental.com" with key 0x42
    target_email = "office@austindental.com"
    key = 0x42
    cf_hex = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in target_email)
    
    decoded = leadcore.decode_cfemail(cf_hex)
    assert decoded == target_email

    # Test extracting from HTML element and raw string
    html = f"""
    <html>
        <body>
            <p>Contact us: <a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="{cf_hex}">[email&#160;protected]</a></p>
        </body>
    </html>
    """
    emails, _, _, _ = leadcore.extract_contacts_from_html(html, "https://austindental.com")
    assert target_email in emails


def test_at_and_dot_email_deobfuscation():
    """Obfuscated emails like user [at] domain [dot] com are extracted."""
    html = """
    <html>
        <body>
            <p>Send appointment inquiries to: contact [at] austindental [dot] com</p>
            <p>Emergency inquiries: drsmith(at)smileaustin.org</p>
            <p>Front desk: frontdesk AT myclinic DOT net</p>
        </body>
    </html>
    """
    emails, _, _, _ = leadcore.extract_contacts_from_html(html, "https://smileaustin.org")
    assert "contact@austindental.com" in emails
    assert "drsmith@smileaustin.org" in emails
    assert "frontdesk@myclinic.net" in emails


def test_crawl_diagnostics_classification():
    """Crawl diagnostics correctly identify blocked, fetch failed, contact-form only, and no email."""
    # 1. Contact form only
    html_form = """
    <html>
        <body>
            <h1>Get In Touch</h1>
            <form action="/submit-contact" method="POST">
                <input type="text" name="name" placeholder="Name" />
                <textarea name="message"></textarea>
                <button type="submit">Send</button>
            </form>
        </body>
    </html>
    """
    with patch("requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.text = html_form
        mock_get.return_value = resp

        em, _, _, diag = leadcore.crawl_website_contacts("https://formonlyclinic.com")
        assert em == ""
        assert diag == "contact-form only"

    # 2. Blocked
    with patch("requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 403
        resp.text = "Forbidden"
        mock_get.return_value = resp

        em, _, _, diag = leadcore.crawl_website_contacts("https://blockedclinic.com")
        assert em == ""
        assert diag == "blocked"

    # 3. Fetch failed
    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.ConnectionError("DNS failure")

        em, _, _, diag = leadcore.crawl_website_contacts("https://deadclinic.com")
        assert em == ""
        assert diag == "fetch failed"

    # 4. No email on page
    html_plain = "<html><body><h1>About Us</h1><p>We are a dental clinic in Austin, Texas.</p></body></html>"
    with patch("requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.text = html_plain
        mock_get.return_value = resp

        em, _, _, diag = leadcore.crawl_website_contacts("https://plainclinic.com")
        assert em == ""
        assert diag == "no email on page"


def test_no_email_status_assignment():
    """enrich_single_lead assigns 'no_email' when no email is found, never 'unknown'."""
    raw_biz = {
        "osm_type": "node",
        "osm_id": 999,
        "business_name": "No Email Dental",
        "phone": "+1 512-555-0199",
        "website": "https://noemaildental.com",
        "email": ""
    }
    with patch("leadcore.crawl_website_contacts") as mock_crawl:
        mock_crawl.return_value = ("", "+1 512-555-0199", "+15125550199", "no email on page")
        lead = leadcore.enrich_single_lead(raw_biz, "Austin, Texas", default_region="US", web_fallback=False, include_guessed=False)
        assert lead["email"] == ""
        assert lead["verification_status"] == "no_email"
        assert lead["verification_status"] != "unknown"
        assert lead["crawl_diagnostic"] == "no email on page"


def test_crawl_worst_case_time_bound():
    """Verify that crawl_website_contacts strictly enforces total_deadline."""
    import time
    
    def slow_fetch(url, *args, **kwargs):
        time.sleep(0.6)
        raise requests.exceptions.ConnectTimeout("Mock slow connect")

    with patch("requests.get", side_effect=slow_fetch):
        t0 = time.perf_counter()
        em, ph_d, ph_e, diag = leadcore.crawl_website_contacts(
            "https://slowhangingsite.com", total_deadline=1.2
        )
        elapsed = time.perf_counter() - t0
        assert elapsed <= 2.2, f"Expected crawler to finish within bounded deadline, took {elapsed:.2f}s"
        assert em == ""
        assert diag == "fetch failed"


def test_registrable_domain_matching():
    """Verify get_registrable_domain treats www/subdomains as the same site and flags external domains."""
    assert leadcore.get_registrable_domain("https://www.example.com") == "example.com"
    assert leadcore.get_registrable_domain("https://sub.blog.example.com") == "example.com"
    assert leadcore.get_registrable_domain("https://austindentist.co.uk") == "austindentist.co.uk"
    assert leadcore.get_registrable_domain("https://sub.austindentist.co.uk") == "austindentist.co.uk"

    # Same registrable domain redirect is allowed
    html_with_email = "<html><body>Contact us: contact@austindentalsite.com</body></html>"
    with patch("requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.url = "https://subdomain.austindentalsite.com/about"
        resp.text = html_with_email
        resp.history = []
        mock_get.return_value = resp

        em, _, _, diag = leadcore.crawl_website_contacts("https://austindentalsite.com")
        assert em == "contact@austindentalsite.com"
        assert diag == "email found"

    # Cross registrable domain redirect is flagged and content not attributed
    with patch("requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.url = "https://clerk.accounts.dev/sign-in"
        resp.text = "<html><body>Help: admin@accounts.dev</body></html>"
        resp.history = []
        mock_get.return_value = resp

        res = leadcore.crawl_website_contacts("https://kunikorthodontics.com")
        assert res.email == ""
        assert "redirected to external domain" in res.diagnostic


def test_cross_domain_redirect_chain_kunik():
    """Verify Kunik multi-hop redirect chain across domains rejects external emails and reports diagnostic."""
    hop1 = MagicMock()
    hop1.url = "https://kunikorthodontics.com/"
    hop1.status_code = 301

    hop2 = MagicMock()
    hop2.url = "https://portal.kunikorthodontics.com/auth"
    hop2.status_code = 302

    final_resp = MagicMock()
    final_resp.status_code = 200
    final_resp.url = "https://clerk.accounts.dev/sign-in"
    final_resp.history = [hop1, hop2]
    final_resp.text = "<html><body>Portal Login. Contact: admin@accounts.dev</body></html>"

    with patch("requests.get", return_value=final_resp):
        res = leadcore.crawl_website_contacts("https://kunikorthodontics.com")
        assert res.email == ""
        assert "redirected to external domain" in res.diagnostic
        assert "accounts.dev" in res.diagnostic


def test_cross_domain_redirect_chain_gordon():
    """Verify Gordon Dental redirect to external booking portal rejects third-party portal emails."""
    hop = MagicMock()
    hop.url = "https://gordondental.com/"
    hop.status_code = 302

    final_resp = MagicMock()
    final_resp.status_code = 200
    final_resp.url = "https://www.zocdoc.com/practice/gordon-dental"
    final_resp.history = [hop]
    final_resp.text = "<html><body>Book Gordon Dental. Questions: support@zocdoc.com</body></html>"

    with patch("requests.get", return_value=final_resp):
        res = leadcore.crawl_website_contacts("https://gordondental.com")
        assert res.email == ""
        assert "redirected to external domain" in res.diagnostic
        assert "zocdoc.com" in res.diagnostic


def test_cross_domain_subpage_rejection_union_dental():
    """Verify Union Dental Salon subpage redirecting to external booking platform is skipped."""
    homepage_html = """
    <html><body>
        <h1>Union Dental Salon</h1>
        <a href="/contact">Contact</a>
    </body></html>
    """
    home_resp = MagicMock()
    home_resp.status_code = 200
    home_resp.url = "https://uniondentalsalon.com/"
    home_resp.history = []
    home_resp.text = homepage_html

    # Subpage /contact redirects to external platform squareup.com
    sub_resp = MagicMock()
    sub_resp.status_code = 200
    sub_resp.url = "https://squareup.com/appointments/book/uniondentalsalon"
    sub_resp.history = [MagicMock(url="https://uniondentalsalon.com/contact")]
    sub_resp.text = "<html><body>Payment support: support@squareup.com</body></html>"

    def mock_get(url, *args, **kwargs):
        if "contact" in url:
            return sub_resp
        return home_resp

    with patch("requests.get", side_effect=mock_get):
        res = leadcore.crawl_website_contacts("https://uniondentalsalon.com")
        # Subpage redirected to squareup.com was skipped, so external email support@squareup.com is NOT attributed
        assert res.email == ""
        assert res.diagnostic == "no email on page"



def test_robots_txt_disallow_skipped():
    """Verify that robots.txt disallowed contact paths are skipped and noted in diagnostic."""
    homepage_html = '<html><body><h1>Clinic</h1><a href="/contact">Contact</a></body></html>'
    robots_disallow_txt = "User-agent: *\nDisallow: /contact\n"

    def mock_requests(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.history = []
        if "robots.txt" in url:
            resp.text = robots_disallow_txt
        elif "/contact" in url:
            pytest.fail("Crawler should not fetch /contact when disallowed by robots.txt!")
        else:
            resp.url = url
            resp.text = homepage_html
        return resp

    # Clear cache
    leadcore._robots_cache.clear()

    with patch("requests.get", side_effect=mock_requests):
        em, ph_d, ph_e, diag = leadcore.crawl_website_contacts("https://robotclinic.com")
        assert em == ""
        assert diag == "contact page disallowed by robots.txt"


def test_variant_only_on_dns_connect_ssl_errors():
    """Verify that www/non-www variant is tried on Connect/SSL/DNS errors, but NOT on ReadTimeout or HTTP 404."""
    called_urls = []

    def mock_read_timeout(url, *args, **kwargs):
        called_urls.append(url)
        raise requests.exceptions.ReadTimeout("Mock read timeout")

    with patch("requests.get", side_effect=mock_read_timeout):
        called_urls.clear()
        em, _, _, diag = leadcore.crawl_website_contacts("https://timeoutclinic.com")
        # Should NOT try www.timeoutclinic.com variant on ReadTimeout
        assert len(set(called_urls)) == 1
        assert "www.timeoutclinic.com" not in called_urls
        assert diag == "fetch failed"

    def mock_connect_timeout(url, *args, **kwargs):
        called_urls.append(url)
        raise requests.exceptions.ConnectTimeout("Mock connect timeout")

    with patch("requests.get", side_effect=mock_connect_timeout):
        called_urls.clear()
        em, _, _, diag = leadcore.crawl_website_contacts("https://connecterrclinic.com")
        # Should try www.connecterrclinic.com variant on ConnectTimeout
        assert "https://www.connecterrclinic.com" in called_urls


def test_skip_contact_pages_if_homepage_failed():
    """Verify that contact page subpage crawl is skipped if homepage returns non-200."""
    subpage_fetched = False

    def mock_fail(url, *args, **kwargs):
        nonlocal subpage_fetched
        if "contact" in url:
            subpage_fetched = True
        resp = MagicMock()
        resp.status_code = 500
        resp.history = []
        resp.text = "Internal Server Error"
        return resp

    with patch("requests.get", side_effect=mock_fail):
        em, _, _, diag = leadcore.crawl_website_contacts("https://servererrorclinic.com")
        assert not subpage_fetched
        assert diag == "fetch failed"


def test_phone_and_email_source_tracking():
    """Verify that OSM tag sources and Website crawl sources are accurately distinguished."""
    raw_lead = {
        "osm_type": "node",
        "osm_id": 12345,
        "business_name": "Source Test Dental",
        "phone": "+1 512-555-0100",
        "phone_source": "OSM tag",
        "email": "",
        "email_source": "",
        "website": "https://reallocallead.com"
    }

    html = "<html><body>Email us: info@reallocallead.com</body></html>"
    with patch("requests.get") as mock_get:
        resp = MagicMock()
        resp.status_code = 200
        resp.url = "https://reallocallead.com"
        resp.text = html
        resp.history = []
        mock_get.return_value = resp

        enriched = leadcore.enrich_single_lead(
            raw_lead, "Austin, Texas", default_region="US", web_fallback=False, include_guessed=False
        )
        assert enriched["email"] == "info@reallocallead.com"
        assert enriched["email_source"] == "website_crawl"
        assert enriched["phone"] == "+1 512-555-0100"
        assert enriched["phone_source"] == "osm_tag"
        assert enriched["source_url"] == "https://reallocallead.com"


def test_nan_and_float_resilience():
    """Verify that all export handlers, validators and status logic gracefully handle float('nan') values."""
    nan_val = float("nan")

    # 1. safe_clean_str
    assert leadcore.safe_clean_str(None) == ""
    assert leadcore.safe_clean_str(nan_val) == ""
    assert leadcore.safe_clean_str(float("inf")) == ""
    assert leadcore.safe_clean_str("nan") == ""
    assert leadcore.safe_clean_str("  NaN  ") == ""
    assert leadcore.safe_clean_str(" hello ") == "hello"

    # 2. validate_email & normalize_phone
    assert leadcore.validate_email(nan_val) is False
    assert leadcore.normalize_phone(nan_val) == ("", "")

    # 3. sanitize_csv_value
    assert leadcore.sanitize_csv_value(nan_val) == ""

    # 4. migrate_lead_status
    assert leadcore.migrate_lead_status(nan_val, email=nan_val) == "no_email"
    assert leadcore.migrate_lead_status("unknown", email=nan_val) == "no_email"
    assert leadcore.migrate_lead_status("valid", email="valid@biz.com") == "valid"

    # 5. Export handlers with NaN values from pandas DataFrame
    nan_rows = [
        {"business_name": "NaN Biz 1", "email": nan_val, "phone": nan_val, "verification_status": nan_val},
        {"business_name": "NaN Biz 2", "email": nan_val, "phone": "+1 512 555 0100", "verification_status": "no_email"},
        {"business_name": "Valid Biz", "email": "valid@biz.com", "phone": nan_val, "verification_status": "valid"},
        {"business_name": "Unverified Biz", "email": "unverified@biz.com", "phone": nan_val, "verification_status": "unverified"},
        {"business_name": "Guessed Biz", "email": "info@guessedbiz.com", "phone": nan_val, "verification_status": "guessed"},
        {"business_name": "Risky Biz", "email": "catchall@biz.com", "phone": nan_val, "verification_status": "risky"},
        {"business_name": "Ghost Unverified", "email": nan_val, "phone": nan_val, "verification_status": "unverified"},
    ]

    # Ready for email must only return Valid Biz (no crash on float strip)
    ready = leadcore.export_leads_ready_for_email(nan_rows)
    assert len(ready) == 1
    assert ready[0]["business_name"] == "Valid Biz"

    # Phones must only return NaN Biz 2 (nan_val in phone must NOT be counted as valid phone)
    phones = leadcore.export_leads_phones(nan_rows)
    assert len(phones) == 1
    assert phones[0]["business_name"] == "NaN Biz 2"

    # Unverified must return Unverified Biz and Guessed Biz, but not Ghost Unverified (email is NaN)
    unverified = leadcore.export_leads_unverified(nan_rows)
    assert len(unverified) == 2
    assert {r["business_name"] for r in unverified} == {"Unverified Biz", "Guessed Biz"}

    # Risky must return Risky Biz
    risky = leadcore.export_leads_risky(nan_rows)
    assert len(risky) == 1
    assert risky[0]["business_name"] == "Risky Biz"


def test_maps_url_encoding():
    """Verify Google Maps search URL scheme with &, spaces, quotes, and non-Latin names."""
    # 1. Ampersands and quotes in business name
    url_quotes = leadcore.build_google_maps_url('Smith & "Sons" Dental', "100 Main St, Austin")
    assert "https://www.google.com/maps/search/?api=1&query=" in url_quotes
    assert "Smith+%26+%22Sons%22+Dental%2C+100+Main+St%2C+Austin" in url_quotes

    # 2. Non-Latin names (Hindi)
    url_hindi = leadcore.build_google_maps_url("श्री गणेश रेस्टोरेंट", "मुंबई, महाराष्ट्र")
    assert "%E0%A4%B6%E0%A5%8D%E0%A4%B0%E0%A5%80" in url_hindi

    # 3. Non-Latin names (Japanese)
    url_japanese = leadcore.build_google_maps_url("東京タワー サロン", "港区, 芝公園")
    assert "%E6%9D%B1%E4%BA%AC" in url_japanese

    # 4. Fallback to lat,lon coordinates when name/address are missing
    url_fallback = leadcore.build_google_maps_url("", "", lat=30.2672, lon=-97.7431)
    assert url_fallback == "https://www.google.com/maps/search/?api=1&query=30.2672%2C-97.7431"

    # 5. Empty inputs return empty string
    assert leadcore.build_google_maps_url("", "", lat=None, lon=None) == ""


def test_source_machine_values_and_migration():
    """Verify standard machine source values and legacy string migration."""
    assert leadcore.normalize_source_value("osm_tag") == "osm_tag"
    assert leadcore.normalize_source_value("OSM tags") == "osm_tag"
    assert leadcore.normalize_source_value("OSM tag") == "osm_tag"
    assert leadcore.normalize_source_value("Website crawl") == "website_crawl"
    assert leadcore.normalize_source_value("website_crawl") == "website_crawl"
    assert leadcore.normalize_source_value("Search snippet (domain matched)") == "search_snippet"
    assert leadcore.normalize_source_value("Domain placeholder (info@)") == "guessed_domain"
    assert leadcore.normalize_source_value("") == ""
    assert leadcore.normalize_source_value(None) == ""


def test_schema_migration_resilience(tmp_path):
    """
    Verify that CSV and history files from older versions (missing new columns,
    containing blank/NaN cells) load and save without DictWriter field mismatches.
    """
    old_csv_row = {
        "business_name": "Legacy Clinic",
        "email": "legacy@clinic.com",
        "business_type": "Clinic",
        "phone": "+1 512-555-0199",
        "verification_status": "valid",
        "latitude": 30.2672,
        "longitude": -97.7431,
        "context_notes": "[OSM tag] Verified",
    }

    migrated = leadcore.migrate_lead_record(old_csv_row)
    # Check that all 20 canonical fields exist
    for field in leadcore.CSV_FIELDS:
        assert field in migrated

    assert migrated["email_source"] == "osm_tag"
    assert migrated["phone_source"] == "osm_tag"
    assert "https://www.google.com/maps/search/?api=1&query=" in migrated["maps_url"]

    # Test saving through save_csv_atomic without DictWriter field mismatch errors
    test_csv_path = str(tmp_path / "migration_export.csv")
    leadcore.save_csv_atomic(test_csv_path, leadcore.CSV_FIELDS, [old_csv_row, {"business_name": "Blank Row"}, {}])

    import csv
    with open(test_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        saved_rows = list(reader)
        assert len(saved_rows) == 3
        assert saved_rows[0]["business_name"] == "Legacy Clinic"
        assert saved_rows[0]["email"] == "legacy@clinic.com"
        assert saved_rows[0]["email_source"] == "osm_tag"
        assert saved_rows[1]["business_name"] == "Blank Row"
        assert "query=Blank+Row" in saved_rows[1]["maps_url"]
        assert saved_rows[2]["business_name"] == ""
        assert saved_rows[2]["maps_url"] == ""


def test_custom_tag_validation():
    """Verify custom OSM tag validation, length caps, and injection defense."""
    # Valid tags
    ok, _ = leadcore.validate_custom_osm_tag("amenity=dentist")
    assert ok is True
    ok, _ = leadcore.validate_custom_osm_tag("craft=electrician")
    assert ok is True
    ok, _ = leadcore.validate_custom_osm_tag("healthcare:speciality=dentist")
    assert ok is True

    # Empty tag
    ok, err = leadcore.validate_custom_osm_tag("")
    assert ok is False
    assert "cannot be empty" in err

    # Length exceeded (>64 chars)
    long_tag = "amenity=" + "x" * 60
    ok, err = leadcore.validate_custom_osm_tag(long_tag)
    assert ok is False
    assert "exceeds maximum length of 64" in err

    # Injection attempts
    ok, err = leadcore.validate_custom_osm_tag("amenity=dentist; drop nodes")
    assert ok is False
    assert "invalid character" in err

    ok, err = leadcore.validate_custom_osm_tag('amenity="dentist"')
    assert ok is False
    assert "invalid character" in err

    ok, err = leadcore.validate_custom_osm_tag("amenity=dentist\\test")
    assert ok is False
    assert "invalid character" in err


def test_compound_overpass_query_builder():
    """Verify build_overpass_query formats compound and bracketed filters correctly."""
    tags = [
        "leisure=fitness_centre",
        'leisure=sports_centre["sport"~"fitness|yoga|pilates|crossfit|gym",i]',
    ]
    query = leadcore.build_overpass_query(tags, 13.0142, 77.6519, 2500)
    assert 'node(around:2500,13.0142,77.6519)["leisure"="fitness_centre"];' in query
    assert 'way(around:2500,13.0142,77.6519)["leisure"="fitness_centre"];' in query
    assert 'node(around:2500,13.0142,77.6519)["leisure"="sports_centre"]["sport"~"fitness|yoga|pilates|crossfit|gym",i];' in query
    assert 'way(around:2500,13.0142,77.6519)["leisure"="sports_centre"]["sport"~"fitness|yoga|pilates|crossfit|gym",i];' in query


def test_format_osm_address():
    """Verify clean address formatting from OSM address tags."""
    tags = {
        "addr:housenumber": "100",
        "addr:street": "Congress Ave",
        "addr:suburb": "Downtown",
        "addr:city": "Austin",
        "addr:postcode": "78701",
    }
    addr = leadcore.format_osm_address(tags)
    assert addr == "100 Congress Ave, Downtown, Austin, 78701"

    # Partial address
    partial = {"addr:street": "Main St", "addr:city": "Austin"}
    assert leadcore.format_osm_address(partial) == "Main St, Austin"

    # addr:full fallback
    full_fallback = {"addr:full": "123 Custom Road, Somewhere"}
    assert leadcore.format_osm_address(full_fallback) == "123 Custom Road, Somewhere"

    # Empty
    assert leadcore.format_osm_address({}) == ""


def test_crawl_result_backwards_compatibility():
    """Verify CrawlResult unpacks as 4-tuple and provides source_url property and 5th index."""
    res = leadcore.CrawlResult(
        "info@testbiz.com", "+1 512-555-0100", "+15125550100", "email found", "https://testbiz.com/contact"
    )
    # 1. 4-tuple unpacking
    em, ph, e164, diag = res
    assert em == "info@testbiz.com"
    assert ph == "+1 512-555-0100"
    assert e164 == "+15125550100"
    assert diag == "email found"
    assert len(res) == 4

    # 2. source_url attribute and index 4
    assert res.source_url == "https://testbiz.com/contact"
    assert res[4] == "https://testbiz.com/contact"


def test_non_html_url_detection():
    """Verify is_non_html_url detects document, archive, and media extensions."""
    assert leadcore.is_non_html_url("http://nb.bsf.gov.in/CGHS%20DIspenseries.pdf") is True
    assert leadcore.is_non_html_url("https://example.com/files/brochure.DOCX") is True
    assert leadcore.is_non_html_url("https://example.com/archive.zip") is True
    assert leadcore.is_non_html_url("https://example.com/data.csv") is True
    assert leadcore.is_non_html_url("https://example.com/image.png") is True
    assert leadcore.is_non_html_url("https://example.com/about") is False
    assert leadcore.is_non_html_url("https://example.com/contact.html") is False
    assert leadcore.is_non_html_url("https://example.com/pricing.php") is False
    assert leadcore.is_non_html_url("") is False


def test_crawl_skips_non_html_cghs_pdf():
    """Verify crawl_website_contacts skips CGHS PDF URL without making network requests."""
    with patch("requests.get") as mock_get:
        res = leadcore.crawl_website_contacts("http://nb.bsf.gov.in/CGHS%20DIspenseries.pdf")
        assert not mock_get.called
        assert res.email == ""
        assert res.phone == ""
        assert res.diagnostic == "linked file, not a website"
        assert res.source_url == ""


def test_enrich_single_lead_cghs_pdf_status_no_email():
    """Verify enrich_single_lead handles CGHS PDF URL with 'linked file, not a website' and no_email status."""
    raw_cghs = {
        "osm_type": "node",
        "osm_id": 4446306461,
        "business_name": "CGHS Dispensary No.1",
        "address": "111 3rd floor, Ganesh Towers, Infantry Road, Shivajinagar, Bengaluru Urban, Bangalore, 560001",
        "phone": "+91 80 2558 9225",
        "phone_source": "osm_tag",
        "website": "http://nb.bsf.gov.in/CGHS%20DIspenseries.pdf",
    }
    with patch("requests.get") as mock_get:
        enriched = leadcore.enrich_single_lead(
            raw_cghs,
            city_name="Bengaluru",
            default_region="IN",
            web_fallback=False,
            include_guessed=True,
        )
        assert not mock_get.called
        assert enriched["email"] == ""
        assert enriched["verification_status"] == "no_email"
        assert enriched["crawl_diagnostic"] == "linked file, not a website"
        assert enriched["phone"] == "+91 80 2558 9225"
        assert enriched["contact_method"] == "phone"


def test_https_to_http_fallback_apollo_white_dental():
    """Verify HTTPS SSLError falls back to HTTP and detects cross-domain migration redirect."""
    redirect_hop = MagicMock()
    redirect_hop.url = "http://apollowhitedental.com/"
    redirect_hop.status_code = 301

    final_resp = MagicMock()
    final_resp.status_code = 200
    final_resp.url = "https://apollodental.in/"
    final_resp.history = [redirect_hop]
    final_resp.text = "<html><body>Apollo Dental Online Booking</body></html>"

    def mock_get(url, *args, **kwargs):
        if url.startswith("https://"):
            raise requests.exceptions.SSLError("certificate has expired")
        if url.startswith("http://"):
            return final_resp
        raise requests.exceptions.RequestException("unexpected URL")

    with patch("requests.get", side_effect=mock_get):
        res = leadcore.crawl_website_contacts("https://apollowhitedental.com/")
        assert res.email == ""
        assert res.diagnostic == "redirected to external domain: apollodental.in"


def test_https_to_http_fallback_same_domain_success():
    """Verify HTTPS SSLError falls back to HTTP on same domain and extracts contacts."""
    http_resp = MagicMock()
    http_resp.status_code = 200
    http_resp.url = "http://myclinic.com/"
    http_resp.history = []
    http_resp.text = "<html><body>Contact us at contact@myclinic.com or call +1 512-555-0123</body></html>"

    def mock_get(url, *args, **kwargs):
        if url.startswith("https://"):
            raise requests.exceptions.SSLError("certificate has expired")
        return http_resp

    with patch("requests.get", side_effect=mock_get):
        res = leadcore.crawl_website_contacts("https://myclinic.com/")
        assert res.email == "contact@myclinic.com"
        assert res.diagnostic == "email found"



