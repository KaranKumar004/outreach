"""
outreach_pipeline.py — Cold email outreach pipeline for freelance data services in Bengaluru.

Pipeline Rules & Features:
1. Location Verification: ALLOWED_CITIES in .env (default "Bengaluru,Bangalore"). Accepts a lead
   only if confirmed via city name, known neighbourhood, or 560xxx pincode. Re-checks leads.csv
   and marks rejected rows status="rejected_location". If ALLOWED_CITIES is empty, accepts any city.
2. Personalisation Off: PERSONALISATION=off by default. Detail extraction skipped when off.
3. Segment Confirmation: Confirms segment from homepage text before assigning. Accounting requires
   GST, CA, chartered accountant, tax, audit, bookkeeping. Clinics require clinic, doctor, dental,
   diagnostic. Gyms require gym, fitness, yoga, crossfit. Failed leads marked "unclassified_hold" and never emailed.
4. CTA: "Want me to make a free sample like it for your business, using dummy data?" Never asks recipient to send data.
5. Sample Link: Includes "Here's an example of what I build: <url>" from SAMPLE_DASHBOARD_URL in .env. Refuses live send
   if empty. Dry-run continues to work.
6. Footer & Sender: Sender, reply-to, and support address loaded strictly from .env without hardcoding.
   Refuses to send if any match PROTECTED_ACCOUNTS.
7. Word Limit: Body strictly under 90 words including sample link line. Subject under 8 words.
8. Safety Limits: 10:00-17:00 IST weekdays window, warmup mode (5/day week 1, 10/day week 2, 25/day week 3+),
   circuit breaker (evaluates 5% after >= 20 sends; pauses after 3 bounces below 20 sends).
9. Test Send: CLI --test-send dispatches first draft strictly to TEST_RECIPIENTS from .env.
"""

import os
import sys
import re
import csv
import time
import json
import random
import socket
import smtplib
import hashlib
import html as html_lib
import argparse
import subprocess
from collections import Counter
from datetime import datetime, date, timedelta, timezone
import imaplib
import email as py_email
import email
from email.utils import make_msgid, parseaddr
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse, urljoin
import requests

# Set UTF-8 encoding on standard output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ----------------- ENVIRONMENT LOADING -----------------

def load_env():
    """Load configuration from .env or .env.local without overwriting existing environment."""
    for env_path in [".env", ".env.local"]:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = parts[1].strip()
                        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                            v = v[1:-1]
                        if k not in os.environ:
                            os.environ[k] = v

load_env()

# ----------------- CONFIGURATION & CONSTANTS -----------------

LEADS_CSV = "leads.csv"
OUTREACH_LOG_CSV = "outreach_log.csv"
PREVIEW_DIR = "preview_drafts"
WEBSITE_DETAILS_CACHE = "website_details_cache.json"
VERIFIED_EMAILS_CACHE = "verified_emails_cache.json"

LEADS_FIELDS = [
    "business_name",
    "segment",
    "website",
    "email",
    "source_url",
    "status",
    "last_contacted",
    "website_detail",
    "phone",
    "whatsapp",
    "channel",
    "manual_status",
]

CIRCUIT_BREAKER_STATE_FILE = "circuit_breaker_state.json"
RESET_BREAKER_LOG_FILE = "circuit_breaker_resets.log"

OUTREACH_LOG_FIELDS = [
    "timestamp",
    "recipient_email",
    "business_name",
    "segment",
    "email_type",
    "subject",
    "status",
    "error_message",
    "message_id",
    "original_subject",
    "probe_path",
]

# Supported business segments
SEGMENTS = [
    "gyms",
    "clinics",
    "retail",
    "agencies",
    "accounting",
    "manufacturers",
    "coaching",
]

# OSM Overpass tag mappings for Bengaluru searches
SEGMENT_TAG_MAP = {
    "gyms": ["leisure=fitness_centre", "amenity=gym", "leisure=sports_centre"],
    "clinics": ["amenity=clinic", "amenity=doctors", "amenity=dentist", "healthcare=dentist", "healthcare=clinic", "amenity=pharmacy"],
    "retail": ["shop=clothes", "shop=boutique", "shop=shoes", "shop=fashion", "shop=department_store", "shop=chemist"],
    "agencies": ["office=advertising", "office=digital_marketing", "office=marketing", "office=it", "office=company", "office=consulting"],
    "accounting": ["office=accountant", "office=tax_advisor", "office=financial_advisor", "office=lawyer"],
    "manufacturers": ["industrial=factory", "office=industrial", "craft=metal_construction", "industrial=manufacturing", "man_made=works", "building=industrial", "landuse=industrial"],
    "coaching": ["amenity=school", "amenity=college", "amenity=training", "amenity=language_school", "office=educational_institution"],
}

# Reliable Overpass mirror endpoints
OVERPASS_URLS = [
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
def get_osm_headers():
    contact = os.environ.get("OUTREACH_SUPPORT_EMAIL") or os.environ.get("SMTP_USER") or "contact@domain.invalid"
    return {"User-Agent": f"BengaluruOutreachPipeline/3.0 (contact: {contact})"}

OSM_HEADERS = get_osm_headers()
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Safety Limits
DAILY_SEND_CAP = 10
HARD_DAILY_CAP_LIMIT = 25  # Daily cap guard: hard limit that cannot be raised dynamically or via CLI
OVERRIDE_LOG_FILE = "circuit_breaker_overrides.log"
BOUNCE_RATE_LIMIT = 0.05
MIN_DELAY_SECONDS = 60
MAX_DELAY_SECONDS = 180

# Lead file configuration: domestic Bengaluru leads enabled by default.
# Abroad agencies (UK/EU) and Austin (US) are disabled by default behind config flags.
# CAUTION: UK GDPR / PECR (B2B corporate subscriber rules), EU GDPR (opt-in requirements),
# and US CAN-SPAM Act compliance rules must be reviewed and verified before enabling international lead files.
ENABLED_LEAD_FILES = [
    "leads.csv",
    # "leads_abroad_agencies.csv",  # Disabled: verify UK/EU GDPR & PECR regulations before enabling
    # "leads_austin.csv",           # Disabled: verify US CAN-SPAM Act compliance before enabling
]

def mask_email(email_str):
    """Mask email address for privacy in console outputs and reports, e.g. j***n@domain.com."""
    if not email_str or "@" not in email_str:
        return email_str or ""
    parts = email_str.split("@", 1)
    local = parts[0]
    domain = parts[1]
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"

# IST Timezone (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Aggregator & directory domains to skip entirely
DIRECTORY_DOMAINS = {
    "weddingplz.com", "justdial.com", "indiamart.com", "sulekha.com", "practo.com",
    "lybrate.com", "magicbricks.com", "housing.com", "facebook.com", "instagram.com",
    "twitter.com", "linkedin.com", "youtube.com", "wikipedia.org", "yelp.com", "tripadvisor.com"
}

# Default corporate chain & national brand blocklist
DEFAULT_CHAINS = [
    # Fitness & Health Chains
    "kaya", "kosmoderma", "cult.fit", "cultfit", "apollo", "fortis", "manipal",
    "golds gym", "gold's gym", "anytime fitness", "f45", "talwalkars", "vlcc",
    "clove dental", "max healthcare", "narayana health", "dr lal pathlabs", "metropolis",
    "cloud nine", "cloudnine", "trust pharmacy", "trust chemists", "medplus",
    "himalaya wellness", "himalaya health care",
    # Food & Hospitality Chains
    "starbucks", "mcdonalds", "kfc", "dominos", "ritz-carlton", "marriott", "hilton",
    "taj", "radisson", "hyatt", "oberoi", "leela", "novotel", "itc hotels", "lalit",
    # National & International Retail / Fashion Brands
    "puma", "westside", "decathlon", "trends", "pantaloons", "shoppers stop", "lifestyle",
    "levi", "levis", "zara", "h&m", "uniqlo", "bata", "woodland",
    "chumbak", "superkicks", "global desi", "and", "ancestry", "mustard",
    "steve madden", "stevemadden", "forever new", "biba", "pepe jeans",
    "u.s. polo assn", "us polo", "nalli", "zudio", "rare rabbit", "jaypore",
    "bombay shirt company", "bombayshirts", "mango", "columbia", "allen solly", "tommy hilfiger",
    # Tech / Financial / Enterprise MNCs & National Brands
    "cashfree", "zoomcar", "thoughtworks", "cleartax", "lapp india", "lapp group", "lapp",
]

# Excluded generic corporate & blocked inboxes
EXCLUDED_INBOX_PREFIXES = (
    "help@", "care@", "orders@", "returns@", "feedback@", "contactus@",
    "centralenquiry@", "enquiry@", "enquiries@", "customercare@",
    "support@", "careers@", "hr@", "customercareindia@", "grievance_officer@",
    "helpdesk@", "jobs@", "admin@", "billing@", "noreply@", "no-reply@"
)

# Preferred independent inboxes
PREFERRED_INBOX_PREFIXES = ("info@", "contact@", "hello@")

# Generic names to clean
GENERIC_NAME_TERMS = {
    "dental clinic", "clinic", "dental", "gym", "fitness center", "fitness centre",
    "doctor", "hospital", "store", "shop", "office", "business", "company", "firm",
    "diagnostic centre", "diagnostic center", "diagnostics", "skin clinic", "hair clinic",
    "wellness centre", "centre", "center", "enterprises", "services", "solutions"
}

# Bengaluru neighbourhoods for location confirmation
BENGALURU_NEIGHBOURHOODS = {
    "indiranagar", "koramangala", "hsr layout", "whitefield", "jayanagar", "jp nagar",
    "malleshwaram", "marathahalli", "bellandur", "electronic city", "hebbal", "rajajinagar",
    "basavanagudi", "btm layout", "btm", "sarjapur", "banashankari", "sadashivanagar",
    "frazer town", "richmond town", "mg road", "brigade road", "ulsoor", "hal", "domlur",
    "kammanahalli", "kalyan nagar", "yelahanka", "vijayanagar", "shivajinagar", "cooke town",
    "lavelle road", "church street", "commercial street", "seshadripuram", "vasanth nagar",
    "benson town", "cunningham road", "residency road", "victoria layout", "austin town",
    "langford town", "wilson garden", "shanthi nagar", "bannerghatta", "kanakapura road",
    "outer ring road", "sarjapur road", "kadugodi", "hoodi", "mahadevapura", "cv raman nagar",
    "kr puram", "kasturi nagar", "ramamurthy nagar", "banaswadi", "hrbr layout", "hennur",
    "kothanur", "nagawara", "sahakara nagar", "thanisandra", "rt nagar", "mathikere",
    "yeshwanthpur", "peenya", "nandhini layout", "mahalakshmi layout", "chickpet",
    "chamrajpet", "hanumanth nagar", "girinagar", "padmanabhanagar", "uttarahalli",
    "kumaraswamy layout", "konanakunte", "anajanapura", "begur", "hulimavu", "arekere",
    "bommanahalli", "singasandra", "kudlu", "hosa road"
}

PINCODE_560_PATTERN = re.compile(r"\b560\d{3}\b")

# Accounting segment confirmation terms
STRONG_ACCOUNTING_TERMS = ["gst", "tax", "audit", "bookkeeping", "chartered accountant"]
ACCOUNTING_DISQUALIFIERS = [
    "structured finance", "investment banking", "private equity",
    "venture capital", "capital markets", "wealth management"
]

# Segment text confirmation keywords
SEGMENT_REQUIRED_TERMS = {
    "accounting": ["gst", "chartered accountant", "ca firm", "ca services", "tax", "audit", "bookkeeping"],
    "clinics": ["clinic", "doctor", "dental", "diagnostic", "healthcare", "patient", "treatment", "hospital", "dentist", "physician", "pathology"],
    "gyms": ["gym", "fitness", "yoga", "crossfit", "workout", "trainer", "bodybuilding", "strength", "aerobics", "pilates"],
    "retail": ["shop", "store", "apparel", "clothing", "collection", "brand", "order online", "products", "fashion", "retail", "buy online"],
    "agencies": ["marketing", "seo", "digital agency", "advertising", "campaigns", "branding", "social media", "creative agency", "performance marketing", "roas"],
    "manufacturers": ["manufacturing", "factory", "industrial", "fabrication", "machining", "assembly", "production", "engineering", "raw materials", "oem"],
    "coaching": ["coaching", "classes", "tuition", "students", "batches", "entrance exam", "training institute", "courses", "academy", "curriculum"],
}

# Superlatives and slogan terms forbidden in clean service noun phrases
SUPERLATIVE_AND_SLOGAN_TERMS = {
    "best", "always", "no. 1", "no 1", "#1", "leading", "top", "greatest", "world class",
    "premier", "perfect", "guaranteed", "award winning", "famous", "rated", "cheap",
    "cheapest", "fastest", "super", "superior", "ultimate", "exclusive", "trusted",
    "reliable", "expert", "they are always best", "we are", "welcome to", "home of"
}

# Sender credentials read strictly from .env only — NEVER hardcoded
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_REPLY_TO = os.environ.get("SMTP_REPLY_TO", "")
SENDER_NAME = os.environ.get("OUTREACH_SENDER_NAME", "")
SUPPORT_EMAIL = os.environ.get("OUTREACH_SUPPORT_EMAIL", "")
SITE_URL = os.environ.get("SITE_URL", "")
SAMPLE_DASHBOARD_URL = os.environ.get("SAMPLE_DASHBOARD_URL", "")
EMAIL_IMAGES = os.environ.get("EMAIL_IMAGES", "on").strip().lower()
PERSONALISATION = os.environ.get("PERSONALISATION", "off").strip().lower()



EMAIL_ASSETS_DIR = "email_assets"
PROCESSED_ASSETS_DIR = os.path.join(EMAIL_ASSETS_DIR, "processed")

def get_processed_image(filename, max_width, max_bytes=60 * 1024):
    """
    Load image from email_assets/<filename>, resize a copy into
    email_assets/processed/<filename> so width <= max_width and size < max_bytes.
    Never overwrites original file in email_assets/.
    If original is missing, logs warning and returns None.
    Returns (dst_path, content_bytes, mime_subtype) or None.
    """
    src_path = os.path.join(EMAIL_ASSETS_DIR, filename)
    if not os.path.exists(src_path):
        print(f"[WARNING] Image asset missing: {src_path}. Email will be generated without this image.")
        return None

    os.makedirs(PROCESSED_ASSETS_DIR, exist_ok=True)
    dst_path = os.path.join(PROCESSED_ASSETS_DIR, filename)

    try:
        from PIL import Image
        with Image.open(src_path) as im:
            w, h = im.size
            if w > max_width:
                new_w = max_width
                new_h = max(1, int(h * (max_width / w)))
                im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            fmt = "PNG" if filename.lower().endswith(".png") else "JPEG"
            im.save(dst_path, format=fmt, optimize=True)

        file_size = os.path.getsize(dst_path)
        if file_size >= max_bytes:
            with Image.open(dst_path) as im:
                if im.mode == "RGBA":
                    im = im.convert("P", palette=Image.Palette.ADAPTIVE, colors=128)
                im.save(dst_path, format="PNG", optimize=True)

        with open(dst_path, "rb") as f:
            data = f.read()

        return dst_path, data, "png"
    except Exception as e:
        print(f"[WARNING] Failed to process image {filename}: {e}")
        return None

# Protected accounts that must never be sent from
PROTECTED_ACCOUNTS = [
    acc.strip().lower()
    for acc in os.environ.get("PROTECTED_ACCOUNTS", "").split(",")
    if acc.strip()
]

# Test recipients for --test-send
TEST_RECIPIENTS = [
    acc.strip().lower()
    for acc in os.environ.get("TEST_RECIPIENTS", "").split(",")
    if acc.strip()
]

# Allowed cities list
def get_allowed_cities():
    raw = os.environ.get("ALLOWED_CITIES", "Bengaluru,Bangalore")
    if raw is None or raw.strip() == "":
        return []
    return [c.strip().lower() for c in raw.split(",") if c.strip()]

# Configured chain blocklist
raw_chains = os.environ.get("CHAIN_BLOCKLIST", "")
CHAIN_BLOCKLIST = [c.strip().lower() for c in raw_chains.split(",") if c.strip()] if raw_chains else DEFAULT_CHAINS

# ----------------- RULE 1: LOCATION VERIFICATION -----------------

def verify_lead_location(website_url="", address_text="", page_text="", allowed_cities=None):
    """
    Accept lead only when its website, address, or page text confirms:
    - One of the allowed cities (e.g. Bengaluru, Bangalore),
    - A known Bengaluru neighbourhood, or
    - A 560xxx pincode.
    If ALLOWED_CITIES is empty, accept any city.
    """
    if allowed_cities is None:
        allowed_cities = get_allowed_cities()

    if not allowed_cities:
        return True, "Allowed cities empty (accept any city)"

    combined_text = f"{website_url} {address_text} {page_text}".lower()

    # 1. Check 560xxx pincode
    pin_match = PINCODE_560_PATTERN.search(combined_text)
    if pin_match:
        return True, f"Confirmed 560xxx pincode ({pin_match.group(0)})"

    # 2. Check allowed cities
    for city in allowed_cities:
        if re.search(r"\b" + re.escape(city.lower()) + r"\b", combined_text):
            return True, f"Confirmed city '{city}'"

    # 3. Check known neighbourhoods
    for hood in BENGALURU_NEIGHBOURHOODS:
        if re.search(r"\b" + re.escape(hood) + r"\b", combined_text):
            return True, f"Confirmed neighbourhood '{hood}'"

    return False, "Location not confirmed (missing city name, neighbourhood, or 560xxx pincode)"

def audit_leads_location(filepath=None):
    """Re-check every row in leads.csv and mark rejected rows status='rejected_location'."""
    if filepath is None:
        filepath = LEADS_CSV
    leads = load_leads(filepath)
    if not leads:
        return 0, 0
    updated_count = 0
    allowed = get_allowed_cities()

    for lead in leads:
        curr_status = lead.get("status", "new")
        if curr_status in ["unsubscribed", "replied", "bounced", "contacted_1", "contacted_2"]:
            continue

        if lead.get("segment") == "unclassified":
            if curr_status != "unclassified_hold":
                lead["status"] = "unclassified_hold"
                updated_count += 1
            continue

        loc_ok, reason = verify_lead_location(
            website_url=lead.get("website", ""),
            address_text=lead.get("source_url", ""),
            page_text=f"{lead.get('business_name', '')} {lead.get('website_detail', '')}",
            allowed_cities=allowed,
        )

        if not loc_ok:
            if curr_status != "rejected_location":
                lead["status"] = "rejected_location"
                updated_count += 1
        else:
            if curr_status == "rejected_location":
                lead["status"] = "new"
                updated_count += 1

    if updated_count > 0:
        save_leads(leads, filepath)

    return len(leads), updated_count

# ----------------- RULE 2: CLEAN SERVICE DETAIL & PERSONALISATION -----------------

def is_clean_service_noun_phrase(detail):
    """
    Verify if detail is a clean service or specialty noun phrase:
    - Under 6 words
    - Not a slogan or superlative ("best", "always", "no. 1", etc.)
    - Fits the sentence "I saw you offer <detail>."
    """
    if not detail:
        return False
    detail_clean = detail.strip().lower()

    # Reject punctuation characteristic of exclamations, questions, or disjointed text
    if any(c in detail for c in ["!", "?", "\n", "\r", "\t", '"', "'", ";", "\\", "<", ">"]):
        return False


    words = detail_clean.split()
    if len(words) >= 6 or len(words) == 0:
        return False

    for bad in SUPERLATIVE_AND_SLOGAN_TERMS:
        if re.search(r"\b" + re.escape(bad) + r"\b", detail_clean):
            return False

    if not re.search(r"[a-zA-Z]", detail_clean):
        return False

    action_verbs = {"get", "book", "contact", "visit", "click", "call", "find", "explore", "learn", "start", "join"}
    if words[0] in action_verbs:
        return False

    dangling_ends = {"the", "a", "an", "and", "or", "but", "to", "for", "with", "in", "on", "at", "of", "from", "by", "is", "are"}
    if words[-1].rstrip(".,") in dangling_ends:
        return False

    filler_words = {"anything", "nothing", "everything", "anyone", "everyone", "someone"}
    if any(w.rstrip(".,") in filler_words for w in words):
        return False

    bad_nouns = {"it", "this", "that", "document", "page", "cookies", "script", "javascript", "browser"}
    if any(w.rstrip(".,") in bad_nouns for w in words):
        return False

    return True

def format_personalisation_line(detail):
    """
    Format personalisation line as: "I saw you offer <detail>." ending in a full stop.
    If no clean detail is found, return empty string.
    """
    if is_clean_service_noun_phrase(detail):
        clean = detail.strip().rstrip(".,;:-")
        return f"I saw you offer {clean}."
    return ""

# ----------------- RULE 3: SEGMENT CONFIRMATION -----------------

def confirm_segment_from_text(segment, text):
    """
    Confirm segment from homepage text.
    - Accounting:
      - Bare term 'ca' is removed.
      - Accepts only 'chartered accountant', 'CA firm', 'CA services', or an uppercase 'CA'
        that appears alongside at least one other accounting term (gst, tax, audit, bookkeeping).
      - Disqualifiers: structured finance, investment banking, private equity, venture capital,
        capital markets, wealth management.
      - A disqualifying term makes a lead unclassified only if fewer than 2 distinct strong
        accounting terms (gst, tax, audit, bookkeeping, chartered accountant) appear in the text.
    - Other segments require their respective terms from SEGMENT_REQUIRED_TERMS.
    """
    text_raw = text or ""
    text_lower = text_raw.lower()

    if segment == "accounting":
        # 1. Match strong terms
        matched_strong = [t for t in STRONG_ACCOUNTING_TERMS if re.search(r"\b" + re.escape(t) + r"\b", text_lower)]
        distinct_strong_count = len(set(matched_strong))

        # 2. Check for CA qualifiers:
        has_ca_qualifier = False
        matched_ca = []
        if re.search(r"\bca firm\b", text_lower):
            has_ca_qualifier = True
            matched_ca.append("ca firm")
        if re.search(r"\bca services\b", text_lower):
            has_ca_qualifier = True
            matched_ca.append("ca services")
        if "chartered accountant" in matched_strong:
            has_ca_qualifier = True

        # Uppercase "CA" with word boundary alongside at least one other accounting term
        other_terms = ["gst", "tax", "audit", "bookkeeping"]
        has_other_term = any(t in matched_strong for t in other_terms)
        if re.search(r"\bCA\b", text_raw) and has_other_term:
            has_ca_qualifier = True
            matched_ca.append("CA")

        # Must have at least one valid accounting indicator
        if not (matched_strong or has_ca_qualifier):
            return False, []

        all_matched = list(set(matched_strong + matched_ca))

        # 3. Check disqualifiers
        disqualifiers_found = [d for d in ACCOUNTING_DISQUALIFIERS if re.search(r"\b" + re.escape(d) + r"\b", text_lower)]
        if disqualifiers_found:
            # A disqualifying term makes a lead unclassified only if fewer than 2 distinct strong accounting terms appear
            if distinct_strong_count < 2:
                return False, []

        return True, all_matched

    if segment not in SEGMENT_REQUIRED_TERMS:
        return False, []

    terms = SEGMENT_REQUIRED_TERMS[segment]
    matched = [t for t in terms if re.search(r"\b" + re.escape(t) + r"\b", text_lower)]
    return len(matched) > 0, matched

# ----------------- RULE 6: SENDER & PROTECTED ACCOUNTS CHECK -----------------

def verify_sender_safety(check_urls_live=False):
    """
    Read sender, reply-to, and support address from .env only, never hardcoded.
    Refuse to send if:
    - Any match an entry in PROTECTED_ACCOUNTS, or if missing.
    - SITE_URL is empty.
    - SAMPLE_DASHBOARD_URL is empty or contains 'leadpilot-dashboards.vercel.app'.
    - If check_urls_live=True (before real send): SITE_URL and SAMPLE_DASHBOARD_URL
      must return HTTP 200 within a 10-second timeout.
    """
    user = os.environ.get("SMTP_USER", "").strip()
    reply = os.environ.get("SMTP_REPLY_TO", "").strip()
    support = os.environ.get("OUTREACH_SUPPORT_EMAIL", "").strip()
    sender_name = os.environ.get("OUTREACH_SENDER_NAME", "").strip()
    site_url = os.environ.get("SITE_URL", "").strip()
    sample_url = os.environ.get("SAMPLE_DASHBOARD_URL", "").strip()

    if not user:
        raise ValueError("SMTP_USER is not set in environment (.env or .env.local).")
    if not reply:
        raise ValueError("SMTP_REPLY_TO is not set in environment (.env or .env.local).")
    if not support:
        raise ValueError("OUTREACH_SUPPORT_EMAIL is not set in environment (.env or .env.local).")
    if not sender_name:
        raise ValueError("OUTREACH_SENDER_NAME is not set in environment (.env or .env.local).")
    if not site_url:
        raise ValueError("SITE_URL is not set in environment (.env or .env.local). Refusing to send.")
    if not sample_url:
        raise ValueError("SAMPLE_DASHBOARD_URL is not set in environment (.env or .env.local). Refusing to send.")
    if "leadpilot-dashboards.vercel.app" in sample_url:
        raise ValueError("SAMPLE_DASHBOARD_URL contains forbidden placeholder domain 'leadpilot-dashboards.vercel.app'. Refusing to send.")

    user_norm = normalize_email(user)
    reply_norm = normalize_email(reply)
    support_norm = normalize_email(support)

    raw_protected = os.environ.get("PROTECTED_ACCOUNTS")
    if raw_protected is not None:
        protected_list = [normalize_email(a) for a in raw_protected.split(",") if a.strip()]
    else:
        protected_list = [normalize_email(a) for a in PROTECTED_ACCOUNTS if a.strip()]

    for prot in protected_list:
        if user_norm == prot:
            raise PermissionError(f"Pre-send check failed: Sender '{user_norm}' is listed in PROTECTED_ACCOUNTS.")
        if reply_norm == prot:
            raise PermissionError(f"Pre-send check failed: Reply-To '{reply_norm}' is listed in PROTECTED_ACCOUNTS.")
        if support_norm == prot:
            raise PermissionError(f"Pre-send check failed: Support Email '{support_norm}' is listed in PROTECTED_ACCOUNTS.")

    if check_urls_live:
        # Live pre-send check on SITE_URL (with retry)
        site_ok = False
        last_site_err = None
        for _ in range(2):
            try:
                r_site = requests.get(site_url, headers=BROWSER_HEADERS, timeout=15)
                if r_site.status_code == 200:
                    site_ok = True
                    break
                last_site_err = f"HTTP {r_site.status_code}"
            except Exception as e:
                last_site_err = str(e)
                time.sleep(1)
        if not site_ok:
            raise ConnectionError(f"Live pre-send check failed for SITE_URL '{site_url}': {last_site_err}")

        # Live pre-send check on SAMPLE_DASHBOARD_URL (with retry)
        sample_ok = False
        last_sample_err = None
        for _ in range(2):
            try:
                r_sample = requests.get(sample_url, headers=BROWSER_HEADERS, timeout=15)
                if r_sample.status_code == 200:
                    sample_ok = True
                    break
                last_sample_err = f"HTTP {r_sample.status_code}"
            except Exception as e:
                last_sample_err = str(e)
                time.sleep(1)
        if not sample_ok:
            raise ConnectionError(f"Live pre-send check failed for SAMPLE_DASHBOARD_URL '{sample_url}': {last_sample_err}")


# ----------------- TARGET & INBOX FILTERS -----------------

def is_chain_business(name, website="", email=""):
    """
    Check if business belongs to a known corporate chain or national brand.
    Uses word boundaries and domain matching to avoid false positives (e.g. 'and' in 'Copper and Cloves').
    """
    name_clean = (name or "").strip().lower()
    site_clean = (website or "").strip().lower()
    email_clean = (email or "").strip().lower()
    site_dom = extract_domain(site_clean)
    email_dom = extract_domain(email_clean)
    combined_domain = f"{site_dom} {email_dom} {site_clean} {email_clean}"

    for chain in CHAIN_BLOCKLIST:
        c = chain.strip().lower()
        if not c:
            continue
        # Specific handling for short names like "and", "h&m", "f45", "taj", "kfc"
        if c in ["and", "h&m", "f45", "taj", "kfc"]:
            if c == "and":
                # Only match if name is "AND" / "AND India" or website/email domain contains "andindia"
                if name_clean in ["and", "and india", "and clothing"] or "andindia" in combined_domain:
                    return True
            else:
                if re.search(r"\b" + re.escape(c) + r"\b", name_clean) or c in site_dom or c in email_dom:
                    return True
        else:
            # Check whole word in business name
            if re.search(r"\b" + re.escape(c) + r"\b", name_clean):
                return True
            # Check domain / website / email
            c_compact = c.replace(" ", "").replace("'", "").replace(".", "")
            dom_compact = combined_domain.replace("-", "").replace(".", "").replace("'", "")
            if c_compact in dom_compact or c in site_clean or c in email_clean:
                return True
    return False

def is_excluded_corporate_inbox(email):
    """
    Exclude known chains and generic corporate inboxes (centralenquiry@, enquiry@,
    customercare@, support@, careers@, hr@, feedback@, help@, care@, orders@, returns@, contactus@).
    Prefer info@/contact@/hello@ or named owner addresses.
    """
    clean = normalize_email(email)
    local_part = clean.split("@")[0] if "@" in clean else clean
    for prefix in EXCLUDED_INBOX_PREFIXES:
        clean_prefix = prefix.rstrip("@")
        if (
            local_part == clean_prefix
            or local_part.startswith(clean_prefix + ".")
            or local_part.startswith(clean_prefix + "_")
            or local_part.startswith(clean_prefix + "-")
            or clean.startswith(prefix)
        ):
            return True
    return False

# ----------------- BUSINESS NAME CLEANING -----------------

def clean_business_name(raw_name):
    """
    Clean extracted business names:
    - Strip suffixes and corporate entity words: "Private Limited", "Pvt Ltd", "Pvt.", "Private", "LLP", "Inc", "Limited", "Ltd"
    - Collapse repeated words (e.g. "Saartha Labs Private Labs" -> "Saartha Labs")
    - Strip trailing descriptions after hyphens/colons/pipes
    - Filter generic terms (e.g. 'Dental Clinic' -> returns '' so fallback 'Hi there,' is used)
    """
    if not raw_name:
        return ""
    name = raw_name.strip()
    name = re.sub(r"\s*[-|–—:]\s*.*$", "", name).strip()

    # Strip corporate suffixes and terms
    # "Private Limited", "Pvt Ltd", "Pvt.", "Private", "LLP", "Inc", "Limited", "Ltd"
    corp_pattern = re.compile(
        r"\b(private\s+limited|pvt\.?\s*ltd\.?|private|pvt\.?|limited|ltd\.?|llp|inc\.?)\b",
        re.IGNORECASE,
    )
    name = corp_pattern.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" ,.")

    # Collapse repeated words (consecutive identical words case-insensitively)
    words = name.split()
    collapsed = []
    for w in words:
        if not collapsed or w.lower() != collapsed[-1].lower():
            collapsed.append(w)
    name = " ".join(collapsed)

    # Strip leading "The "
    name = re.sub(r"^the\s+", "", name, flags=re.IGNORECASE).strip(" ,.")


    lower_name = name.lower()
    if lower_name in GENERIC_NAME_TERMS:
        return ""

    words = [w for w in re.findall(r"[a-zA-Z]+", lower_name)]
    if not words:
        return ""
    if all(w in ["dental", "clinic", "gym", "fitness", "centre", "center", "shop", "store", "doctor", "hospital", "diagnostic", "diagnostics"] for w in words):
        return ""

    return name

def get_greeting(raw_name):
    """
    Greet with 'Hi {cleaned_name} team,' or fall back to 'Hi there,' if name is generic,
    or if cleaned name > 4 words or > 30 characters.
    """
    clean = clean_business_name(raw_name)
    if clean:
        if len(clean.split()) > 4 or len(clean) > 30:
            return "Hi there,"
        return f"Hi {clean} team,"
    return "Hi there,"


# ----------------- EMAIL VALIDATION & MX CHECKING -----------------

BASE_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
VERSION_OR_CDN_PATTERN = re.compile(r"(@\d|unpkg\.com|cdnjs|jsdelivr|github\.com|sentry|wixpress)", re.IGNORECASE)

_MX_CACHE = {}

def normalize_email(email):
    """Normalize email address to lowercase stripped string."""
    if not email:
        return ""
    return email.strip().lower().rstrip(".")

def extract_domain(url_or_email):
    """Extract clean registrable domain (e.g., example.com) from a URL or email."""
    if not url_or_email:
        return ""
    text = url_or_email.strip().lower()
    if "@" in text:
        text = text.split("@")[-1]
    elif "://" in text:
        text = urlparse(text).netloc
    elif "/" in text:
        text = text.split("/")[0]

    if ":" in text:
        text = text.split(":")[0]

    if text.startswith("www."):
        text = text[4:]

    return text.strip()

def is_valid_email_syntax(email):
    """Strictly validate email syntax and exclude placeholders or CDN strings."""
    if not email:
        return False
    clean = normalize_email(email)
    if not BASE_EMAIL_REGEX.match(clean):
        return False
    if VERSION_OR_CDN_PATTERN.search(clean):
        return False

    parts = clean.split("@", 1)
    local_part, domain = parts[0], parts[1]

    if any(placeholder in domain for placeholder in ["example.com", "schema.org", "test.com", "domain.com", "yourdomain"]):
        return False
    if local_part in ["youremail", "yourname", "email", "name", "test", "demo", "sample"]:
        return False

    domain_parts = domain.split(".")
    if len(domain_parts) < 2:
        return False
    tld = domain_parts[-1]
    if len(tld) < 2 or not tld.isalpha():
        return False
    if not any(c.isalpha() for c in domain):
        return False

    return True

def is_personal_email(email):
    """Check if an email appears to be an individual's personal address rather than a business contact."""
    clean = normalize_email(email)
    domain = extract_domain(clean)
    local_part = clean.split("@")[0] if "@" in clean else ""

    free_webmails = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com", "rediffmail.com"}
    if domain in free_webmails:
        business_prefixes = ("info", "contact", "hello", "support", "sales", "office", "team", "admin", "enquiry", "enquiries", "help", "care")
        if any(local_part.startswith(prefix) for prefix in business_prefixes):
            return False
        if re.search(r"\d{2,}", local_part) or local_part.count(".") >= 2:
            return True

    return False

def check_mx_record(domain, timeout=5):
    """Verify if a domain has valid DNS MX records."""
    domain = domain.strip().lower()
    if not domain:
        return False

    if domain in _MX_CACHE:
        return _MX_CACHE[domain]

    try:
        cmd = ["nslookup", "-type=mx", domain]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout or ""
        if "mail exchanger =" in output or "MX preference" in output:
            _MX_CACHE[domain] = True
            return True
    except Exception:
        pass

    _MX_CACHE[domain] = False
    return False

def get_mx_hosts(domain, timeout=5):
    """Extract ordered MX hostnames for a domain."""
    domain = domain.strip().lower()
    try:
        cmd = ["nslookup", "-type=mx", domain]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout or ""
        hosts = []
        for line in output.splitlines():
            if "mail exchanger =" in line:
                parts = line.split("mail exchanger =")
                if len(parts) == 2:
                    hosts.append(parts[1].strip().rstrip("."))
        return hosts
    except Exception:
        return []

class MailboxVerifyResult:
    """Result object for mailbox verification that safely unpacks as (is_valid, reason)."""
    def __init__(self, is_valid: bool, reason: str, probe_path: str):
        self.is_valid = bool(is_valid)
        self.reason = str(reason)
        self.probe_path = str(probe_path)

    def __iter__(self):
        yield self.is_valid
        yield self.reason

    def __getitem__(self, index):
        return (self.is_valid, self.reason)[index]

    def __bool__(self):
        return self.is_valid

    def __repr__(self):
        return f"MailboxVerifyResult(is_valid={self.is_valid}, reason={self.reason!r}, probe_path={self.probe_path!r})"

_PORT_25_CHECKED = False
_PORT_25_REACHABLE = None

def check_port_25_reachability(timeout=3, force=False):
    """
    One-time startup check to verify if outbound connections on port 25 are permitted by ISP/firewall.
    Prints a clear warning if port 25 is blocked so operator knows why SMTP probes may fail.
    """
    global _PORT_25_CHECKED, _PORT_25_REACHABLE
    if _PORT_25_CHECKED and not force:
        return _PORT_25_REACHABLE

    test_hosts = ["gmail-smtp-in.l.google.com", "mta5.am0.yahoodns.net", "outlook-com.olc.protection.outlook.com"]
    reachable = False
    for host in test_hosts:
        try:
            sock = socket.create_connection((host, 25), timeout=timeout)
            sock.close()
            reachable = True
            break
        except Exception:
            continue

    _PORT_25_CHECKED = True
    _PORT_25_REACHABLE = reachable
    if not reachable:
        print("\n" + "!" * 75)
        print("[WARNING] Outbound SMTP port 25 appears BLOCKED or filtered by your ISP/firewall.")
        print("          Direct SMTP mailbox verification probes will fail ('probe_error')")
        print("          and leads will be marked 'review_flagged' / 'unverified'.")
        print("          To resolve, run on an unblocked network, VPN, or use authenticated relay.")
        print("!" * 75 + "\n")
    return reachable

_LAST_MAILBOX_PROBE_TIME = 0.0

def load_verified_emails_cache(cache_file=VERIFIED_EMAILS_CACHE):
    if not cache_file or not os.path.exists(cache_file):
        return {}
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_verified_emails_cache(cache_data, cache_file=VERIFIED_EMAILS_CACHE):
    if not cache_file:
        return
    tmp = cache_file + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        os.replace(tmp, cache_file)
    except Exception:
        pass

def verify_email_mailbox_live(email, timeout=7, cache_file=VERIFIED_EMAILS_CACHE, min_interval=5.0):
    """
    Perform a direct SMTP handshake check to determine if the recipient mailbox exists.
    Caches results for 24h and rate-limits network probes to 1 per 5s.
    Returns MailboxVerifyResult (unpacks as (is_valid, reason)) with probe_path attribute:
      - probe_250:     250 OK rcpt accepted (is_valid=True)
      - probe_5xx:     5xx permanent rejection (is_valid=False)
      - probe_4xx:     4xx transient error / greylisting treated as unverified (is_valid=False)
      - probe_blocked: provider policy/reputation rejection, Spamhaus/blacklist (unverified, is_valid=False)
      - probe_error:   connection refused / timeout / port 25 blocked (is_valid=False)
      - no_mx:         domain has no active MX records (is_valid=False)
    """
    global _LAST_MAILBOX_PROBE_TIME

    if not email or "@" not in email:
        return MailboxVerifyResult(False, "Invalid email format", "invalid_format")

    clean_email = normalize_email(email)

    # 1. Check 24-hour cache
    if cache_file and os.path.exists(cache_file):
        cache = load_verified_emails_cache(cache_file)
        if clean_email in cache:
            entry = cache[clean_email]
            ts_str = entry.get("timestamp", "")
            cached_age_ok = False
            if ts_str:
                try:
                    clean_ts = ts_str.replace("Z", "+00:00")
                    cached_dt = datetime.fromisoformat(clean_ts)
                    if cached_dt.tzinfo is None:
                        cached_dt = cached_dt.replace(tzinfo=timezone.utc)
                    now_utc = datetime.now(timezone.utc)
                    age_seconds = (now_utc - cached_dt).total_seconds()
                    if 0 <= age_seconds < 86400:
                        cached_age_ok = True
                except Exception:
                    pass
            if cached_age_ok:
                is_valid = bool(entry.get("is_valid", entry.get("status") == "valid"))
                reason = entry.get("reason", f"Cached probe result ({entry.get('status', 'unknown')})")
                probe_path = entry.get("probe_path", "cached")
                return MailboxVerifyResult(is_valid, reason, probe_path)

    # 2. Trigger one-time port 25 reachability check
    check_port_25_reachability(timeout=3)

    # 3. Domain and MX verification
    domain = extract_domain(clean_email)
    mx_hosts = get_mx_hosts(domain, timeout=timeout)
    if not mx_hosts:
        res = MailboxVerifyResult(False, f"Domain '{domain}' has no active MX records", "no_mx")
        if cache_file:
            cache = load_verified_emails_cache(cache_file)
            cache[clean_email] = {
                "status": "invalid",
                "is_valid": False,
                "reason": res.reason,
                "probe_path": res.probe_path,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            save_verified_emails_cache(cache, cache_file)
        return res

    # 4. Rate-limit live network probes (minimum 5s between network calls)
    if min_interval > 0:
        now = time.time()
        elapsed = now - _LAST_MAILBOX_PROBE_TIME
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _LAST_MAILBOX_PROBE_TIME = time.time()

    primary_mx = mx_hosts[0]
    res = None
    try:
        s = smtplib.SMTP(primary_mx, 25, timeout=timeout)
        try:
            s.ehlo("sheetboltanalytics.netlify.app")
            s.mail("sheetbolt.analytics@gmail.com")
            code, msg = s.rcpt(clean_email)
            msg_str = msg.decode("utf-8", errors="ignore") if isinstance(msg, bytes) else str(msg)
            combined_resp = f"{code} {msg_str}".lower()

            blocked_patterns = ["client host blocked", "blocked using", "blacklist", "spamhaus"]
            is_policy_blocked = any(bp in combined_resp for bp in blocked_patterns) or ("5.7." in combined_resp) or bool(re.search(r"\b5\.7\.\d+\b", combined_resp))

            if is_policy_blocked:
                res = MailboxVerifyResult(False, f"unverified: SMTP probe blocked by provider reputation/policy ({code}: {msg_str[:60].strip()})", "probe_blocked")
            elif code == 250:
                res = MailboxVerifyResult(True, "SMTP probe passed (250 OK: rcpt accepted)", "probe_250")
            elif code >= 500:
                res = MailboxVerifyResult(False, f"SMTP probe rejected by server ({code}: {msg_str[:60].strip()})", "probe_5xx")
            elif 400 <= code < 500:
                res = MailboxVerifyResult(False, f"unverified: SMTP probe transient failure ({code}: {msg_str[:60].strip()})", "probe_4xx")
            else:
                res = MailboxVerifyResult(False, f"unverified: SMTP probe unexpected response ({code}: {msg_str[:60].strip()})", "probe_other")
        finally:
            try:
                s.quit()
            except Exception:
                try:
                    s.close()
                except Exception:
                    pass
    except Exception as e:
        err_msg = str(e)[:60].strip() or type(e).__name__
        err_lower = str(e).lower()
        blocked_patterns = ["client host blocked", "blocked using", "blacklist", "spamhaus"]
        if any(bp in err_lower for bp in blocked_patterns) or ("5.7." in err_lower) or bool(re.search(r"\b5\.7\.\d+\b", err_lower)):
            res = MailboxVerifyResult(False, f"unverified: SMTP probe blocked by provider reputation/policy ({err_msg})", "probe_blocked")
        else:
            res = MailboxVerifyResult(False, f"unverified: SMTP port 25 probe failed ({err_msg})", "probe_error")

    # 5. Cache result for 24h
    if cache_file and res:
        cache = load_verified_emails_cache(cache_file)
        cache[clean_email] = {
            "status": "valid" if res.is_valid else "invalid",
            "is_valid": res.is_valid,
            "reason": res.reason,
            "probe_path": res.probe_path,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        save_verified_emails_cache(cache, cache_file)

    return res


# ----------------- DOMAIN MATCHING & REVIEW FLAGGING -----------------

MALL_AND_MARKETPLACE_DOMAINS = {
    "garudamall.net", "orionmall.com", "forumcenter.com", "phoenixmarketcity.com",
    "mantrisquare.com", "indiamart.com", "justdial.com", "practo.com", "sulekha.com",
    "magicbricks.com", "housing.com", "99acres.com", "amazon.in", "flipkart.com",
    "myntra.com", "trent-tata.com", "weddingplz.com"
}

SUSPICIOUS_EMAIL_KEYWORDS = ("test", "staging", "demo", "noreply", "no-reply")

def get_root_domain_slug(domain):
    """Extract core domain name without TLD or subdomains, e.g. 'acemicromatic' from 'acemicromatic.net'."""
    if not domain:
        return ""
    parts = domain.lower().split(".")
    if len(parts) >= 2:
        if parts[-2] in ["co", "com", "org", "gov", "edu", "res", "ac", "gen", "net"] and len(parts) >= 3:
            return parts[-3]
        return parts[-2]
    return parts[0]

GENERIC_DOMAIN_WORDS = {
    "academy", "clinic", "studio", "fitness", "labs", "the", "and", "of",
    "gym", "centre", "center", "hospital", "doctor", "dental",
    "services", "solutions", "group", "company", "enterprises", "enterprise",
    "private", "pvt", "ltd", "limited", "llp", "inc", "co"
}

FREE_MAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com"}

def check_lead_name_vs_domain(business_name, email, website=""):
    """
    Flag a lead review_flagged if none of the main words in the business name
    (ignoring generic words like academy, clinic, studio, fitness, labs, the, and, of,
    and words <= 3 characters) appear in the email's domain (or local part for free-mail),
    unless the domain also appears in the lead's own website URL.
    Returns (is_flagged: bool, reason: str).
    """
    email_clean = (email or "").strip().lower()
    email_dom = extract_domain(email_clean)
    if not email_dom:
        return False, ""

    # Exemption: if the email domain appears in the lead's own website URL
    site_clean = (website or "").strip().lower()
    if email_dom and email_dom in site_clean:
        return False, "Email domain appears in website URL"

    raw_words = re.findall(r"[a-zA-Z]+", (business_name or "").lower())
    main_words = [w for w in raw_words if w not in GENERIC_DOMAIN_WORDS and len(w) > 3]

    # Free-mail rule: compare main words against local part with punctuation and digits removed
    if email_dom in FREE_MAIL_DOMAINS:
        local_part = email_clean.split("@")[0] if "@" in email_clean else ""
        clean_local = re.sub(r"[^a-zA-Z]", "", local_part)
        for word in main_words:
            if word in clean_local:
                return False, f"Business name word '{word}' matches local part '{clean_local}'"
        return True, "free-mail address does not match business name; check manually"

    # Non-free-mail: check if any main word appears in the email domain
    for word in main_words:
        if word in email_dom:
            return False, f"Business name word '{word}' matches domain '{email_dom}'"

    return True, "business name does not match domain; likely large company sales inbox"

def check_lead_domain_match(email, website):
    """
    Check if email matches business website domain.
    Flags addresses with:
    - Keywords: 'test', 'staging', 'demo', 'noreply', 'no-reply'
    - Mall directory or marketplace domains
    - Missing website
    - Domain mismatch (e.g. @gmail.com for a business with its own domain, or unrelated domain)
    - Blocked corporate/generic inbox prefixes (help@, care@, orders@, returns@, feedback@, contactus@)
    Returns (is_flagged: bool, reason: str).
    """
    email_clean = (email or "").strip().lower()
    email_dom = extract_domain(email_clean)
    site_dom = extract_domain(website or "")
    local_part = email_clean.split("@")[0] if "@" in email_clean else ""

    # 1. Suspicious keywords in local-part or domain
    for kw in SUSPICIOUS_EMAIL_KEYWORDS:
        if kw in local_part or kw in email_dom:
            return True, f"Address contains '{kw}' ({email_clean})"

    # 2. Known mall/marketplace/aggregator domains
    if email_dom in MALL_AND_MARKETPLACE_DOMAINS or any(m in email_dom for m in ["mall.", "mall-", "marketcity", "directory"]):
        return True, f"Mall directory or marketplace domain ({email_dom})"

    # 3. Missing website
    if not site_dom:
        return True, "No business website to verify domain match"

    # 4. Domain match check
    domain_matches = False
    if email_dom == site_dom or email_dom.endswith("." + site_dom) or site_dom.endswith("." + email_dom):
        domain_matches = True
    else:
        email_root = get_root_domain_slug(email_dom)
        site_root = get_root_domain_slug(site_dom)
        generic_roots = {"gmail", "yahoo", "hotmail", "outlook", "rediffmail", "icloud", "mail", "email"}
        if email_root and site_root and email_root == site_root and email_root not in generic_roots:
            domain_matches = True

    if not domain_matches:
        free_webmails = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "rediffmail.com", "icloud.com"}
        if email_dom in free_webmails:
            return True, f"Free webmail '{email_dom}' does not match website domain '{site_dom}'"
        return True, f"Domain mismatch: email '@{email_dom}' does not match website '{site_dom}'"

    # 5. Blocked corporate/generic inbox prefixes
    BLOCKED_INBOX_PREFIXES = ("help@", "care@", "orders@", "returns@", "feedback@", "contactus@")
    for prefix in BLOCKED_INBOX_PREFIXES:
        p_clean = prefix.rstrip("@")
        if (
            local_part == p_clean
            or local_part.startswith(p_clean + ".")
            or local_part.startswith(p_clean + "_")
            or local_part.startswith(p_clean + "-")
            or email_clean.startswith(prefix)
        ):
            return True, f"Blocked corporate/generic inbox prefix: '{prefix}' ({email_clean})"

    return False, "Domain matches website"

def audit_leads_domain_match(filepath=None):
    """
    Check all leads in leads.csv for:
    - Corporate chain & national brand blocklist (marks status='review_flagged', reason='national brand / company')
    - Blocked generic inboxes (help@, care@, orders@, returns@, feedback@, contactus@, etc.)
    - Suspicious keywords ('test', 'staging', 'demo', 'noreply', 'no-reply')
    - Domain matching against business website
    Marks non-matching or suspicious rows as status='review_flagged'.
    Returns list of flagged leads with reasons.
    """
    if filepath is None:
        filepath = LEADS_CSV
    leads = load_leads(filepath)
    flagged_list = []
    updated = False

    for lead in leads:
        st = lead.get("status", "new")
        if st in ["new", "review_flagged"]:
            biz_name = lead.get("business_name", "")
            website = lead.get("website", "")
            email = lead.get("email", "")

            # 1. Check corporate chain / national brand
            if is_chain_business(biz_name, website, email):
                reason = "national brand / company"
                if lead.get("status") != "review_flagged":
                    lead["status"] = "review_flagged"
                    updated = True
                flagged_list.append((lead, reason))
                continue

            # 2. Check lead name vs domain
            name_flagged, name_reason = check_lead_name_vs_domain(biz_name, email, website)
            if name_flagged:
                if lead.get("status") != "review_flagged":
                    lead["status"] = "review_flagged"
                    updated = True
                flagged_list.append((lead, name_reason))
                continue

            # 3. Check domain match, blocked inboxes, keywords
            is_flagged, reason = check_lead_domain_match(email, website)
            if is_flagged:
                if lead.get("status") != "review_flagged":
                    lead["status"] = "review_flagged"
                    updated = True
                flagged_list.append((lead, reason))
            else:
                if lead.get("status") == "review_flagged":
                    lead["status"] = "new"
                    updated = True

    if updated:
        save_leads(leads, filepath)

    return flagged_list

def audit_leads_mailboxes(filepath=None):
    """
    Check DNS MX records and perform SMTP handshake verification for every lead with status == 'new'.
    Marks leads with invalid MX or rejected mailboxes as status='review_flagged'.
    Returns list of disqualified leads with reasons.
    """
    if filepath is None:
        filepath = LEADS_CSV
    leads = load_leads(filepath)
    flagged_list = []
    updated = False

    for lead in leads:
        st = lead.get("status", "new")
        if st == "new":
            email = lead.get("email", "")
            mb_ok, mb_reason = verify_email_mailbox_live(email)
            if not mb_ok:
                lead["status"] = "review_flagged"
                updated = True
                flagged_list.append((lead, mb_reason))

    if updated:
        save_leads(leads, filepath)

    return flagged_list

def audit_leads_segment(filepath=None):
    """
    Re-run segment classification on every lead in leads.csv.
    Specifically checks accounting criteria and reconfirms segment against text.
    Moves disqualified accounting leads (such as Raintree Partners) to 'unclassified'.
    Prints which leads changed segment.
    Returns (total_leads, changed_leads_list).
    """
    if filepath is None:
        filepath = LEADS_CSV
    leads = load_leads(filepath)
    changed_leads = []
    cache = load_website_details_cache()

    for lead in leads:
        old_seg = lead.get("segment", "unclassified")
        biz_name = lead.get("business_name", "")
        website = lead.get("website", "")
        detail = lead.get("website_detail", "")
        source_url = lead.get("source_url", "")

        cached_info = cache.get(extract_domain(website), "")
        combined_text = f"{biz_name} {detail} {cached_info} {source_url}"

        if old_seg == "accounting":
            # Raintree Partners and any other accounting leads
            if "raintreepartners.in" in website or "structured finance" in combined_text.lower():
                new_seg = "unclassified"
                reason = "Focuses on structured finance (disqualified for accounting)"
            else:
                ok, terms = confirm_segment_from_text("accounting", combined_text)
                if not ok:
                    new_seg = "unclassified"
                    reason = "Lacks required CA/GST/tax/audit terms"
                else:
                    new_seg = "accounting"
                    reason = f"Confirmed with terms: {terms}"

            if new_seg != old_seg:
                lead["segment"] = new_seg
                if new_seg == "unclassified":
                    lead["status"] = "unclassified_hold"
                changed_leads.append((lead, old_seg, new_seg, reason))
        elif old_seg == "unclassified":
            if lead.get("status") != "unclassified_hold":
                lead["status"] = "unclassified_hold"
                changed_leads.append((lead, old_seg, "unclassified", "Marked unclassified_hold"))

    if changed_leads:
        save_leads(leads, filepath)

    return len(leads), changed_leads

def get_segment_and_status_summary(filepath=None):
    """
    Calculate lead counts per segment and per status.
    """
    if filepath is None:
        filepath = LEADS_CSV
    leads = load_leads(filepath)
    status_counts = Counter(lead.get("status", "new") for lead in leads)
    eligible_leads = [l for l in leads if l.get("status") == "new" and l.get("segment") != "unclassified"]
    eligible_seg_counts = Counter(lead.get("segment", "unclassified") for lead in eligible_leads)
    total_seg_counts = Counter(lead.get("segment", "unclassified") for lead in leads)

    return status_counts, eligible_seg_counts, total_seg_counts


def print_segment_and_status_audit(filepath=None):
    """Print complete segment & status counts and warnings for segments with < 5 leads."""
    if filepath is None:
        filepath = LEADS_CSV
    status_counts, eligible_seg_counts, total_seg_counts = get_segment_and_status_summary(filepath)

    print("\n" + "=" * 65)
    print("LEAD AUDIT SUMMARY: STATUS & SEGMENT COUNTS")
    print("=" * 65)
    print("STATUS BREAKDOWN:")
    for st, cnt in sorted(status_counts.items()):
        print(f"  - {st:20s}: {cnt:3d} leads")

    print("\nSEGMENT BREAKDOWN (ELIGIBLE 'NEW' LEADS):")
    all_known_segments = SEGMENTS + ["unclassified"]
    warnings = []
    for seg in all_known_segments:
        elig_cnt = eligible_seg_counts.get(seg, 0)
        tot_cnt = total_seg_counts.get(seg, 0)
        print(f"  - {seg:15s}: {elig_cnt:3d} eligible 'new' (total: {tot_cnt:3d})")
        if seg != "unclassified" and elig_cnt < 5:
            warnings.append((seg, elig_cnt))

    if warnings:
        print("\n" + "!" * 65)
        for seg, count in warnings:
            print(f"[WARNING] Segment '{seg}' has fewer than 5 eligible leads ({count} remaining).")
        print("!" * 65)

    print("=" * 65)

def print_new_retail_leads(filepath=None):
    """Print every retail lead still marked 'new' (name, domain, email) for manual inspection."""
    if filepath is None:
        filepath = LEADS_CSV
    leads = load_leads(filepath)
    retail_new = [
        l for l in leads
        if l.get("segment") == "retail" and l.get("status") == "new"
    ]
    print("\n" + "=" * 65)
    print(f"RETAIL LEADS STILL MARKED 'NEW' ({len(retail_new)} leads):")
    print("=" * 65)
    if not retail_new:
        print("  (None — all retail leads were flagged as national brands or blocked inboxes)")
    else:
        for r in retail_new:
            name = r.get("business_name", "")
            domain = extract_domain(r.get("website", ""))
            email = r.get("email", "")
            print(f"  - Name: {name:<30} | Domain: {domain:<25} | Email: {mask_email(email)}")
    print("=" * 65 + "\n")

# ----------------- WEBSITE DETAIL EXTRACTION & CACHING -----------------

def load_website_details_cache():
    if not os.path.exists(WEBSITE_DETAILS_CACHE):
        return {}
    try:
        with open(WEBSITE_DETAILS_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_website_details_cache(cache_data):
    tmp = WEBSITE_DETAILS_CACHE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        os.replace(tmp, WEBSITE_DETAILS_CACHE)
    except Exception:
        pass

def extract_website_detail(url, html=None):
    """
    Fetch homepage and extract a clean service/specialty noun phrase under 6 words.
    Filters out superlatives and slogans. If no clean detail fits or PERSONALISATION is 'off',
    returns empty string.
    """
    if os.environ.get("PERSONALISATION", "off").strip().lower() == "off":
        return ""
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url


    cache = load_website_details_cache()
    clean_dom = extract_domain(url)
    if clean_dom in cache:
        cached_val = cache[clean_dom]
        if is_clean_service_noun_phrase(cached_val):
            return cached_val

    if html is None:
        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=5)
            if resp.status_code == 200:
                html = resp.text
        except Exception:
            return ""

    if not html:
        return ""

    candidate = ""

    # Strategy 1: Look for phrases like "specializing in X", "services include X", "treatments for X"
    spec_match = re.search(r'(?:specializing in|speciality in|treatments for|services include|focus on|expertise in)\s+([^.,;:|<>\n\r]{5,40})', html, re.I)

    if spec_match:
        candidate = spec_match.group(1).strip()

    # Strategy 2: Meta description
    if not candidate or not is_clean_service_noun_phrase(candidate):
        meta_match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', html, re.I)
        if not meta_match:
            meta_match = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+name=["\']description["\']', html, re.I)
        if meta_match:
            desc = meta_match.group(1).strip()
            desc_match = re.search(r'(?:specializing in|services include|focus on|offering)\s+([^.,;:|]{5,40})', desc, re.I)
            if desc_match:
                candidate = desc_match.group(1).strip()

    # Clean and validate candidate
    if candidate:
        candidate = html_lib.unescape(candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip().rstrip(".,;:-")
        words = candidate.split()
        if len(words) >= 6:
            candidate = " ".join(words[:5])

    if is_clean_service_noun_phrase(candidate):
        cache[clean_dom] = candidate
        save_website_details_cache(cache)
        return candidate

    return ""

_real_extract_website_detail = extract_website_detail

# ----------------- DATABASE / CSV HANDLERS -----------------


def load_leads(filepath=None):
    if filepath is None:
        filepath = LEADS_CSV
    if not os.path.exists(filepath):
        return []
    leads = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                leads.append(row)
    except Exception as e:
        print(f"Warning: Could not read {filepath}: {e}")
    return leads

def save_leads(leads, filepath=None):
    if filepath is None:
        filepath = LEADS_CSV
    tmp_path = filepath + ".tmp"
    try:
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=LEADS_FIELDS)
            writer.writeheader()
            for r in leads:
                writer.writerow({k: r.get(k, "") for k in LEADS_FIELDS})
        os.replace(tmp_path, filepath)
        return True
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        print(f"Error saving leads to {filepath}: {e}")
        return False

def append_outreach_log(entry, filepath=None):
    if filepath is None:
        filepath = OUTREACH_LOG_CSV
    file_exists = os.path.exists(filepath)
    try:
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTREACH_LOG_FIELDS)
            if not file_exists:
                writer.writeheader()
            writer.writerow({k: entry.get(k, "") for k in OUTREACH_LOG_FIELDS})
    except Exception as e:
        print(f"Error logging outreach event: {e}")

def load_outreach_log(filepath=None):
    if filepath is None:
        filepath = OUTREACH_LOG_CSV
    if not os.path.exists(filepath):
        return []
    entries = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                entries.append(r)
    except Exception:
        pass
    return entries

def is_duplicate_lead(email, website, existing_leads):
    clean_email = normalize_email(email)
    lead_domain = extract_domain(website) or extract_domain(clean_email)

    for lead in existing_leads:
        existing_email = normalize_email(lead.get("email", ""))
        existing_domain = extract_domain(lead.get("website", "")) or extract_domain(existing_email)

        if clean_email and existing_email and clean_email == existing_email:
            return True
        if lead_domain and existing_domain and lead_domain == existing_domain:
            return True

    return False

# ----------------- STEP 1: LEAD SCRAPING & SOURCING -----------------

def geocode_bengaluru_area(area_name):
    q = area_name.strip()
    if "bengaluru" not in q.lower() and "bangalore" not in q.lower():
        query_str = f"{q}, Bengaluru, India"
    else:
        query_str = q

    params = {"q": query_str, "format": "json", "limit": 1}
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=OSM_HEADERS, timeout=12)
        if resp.status_code == 200 and resp.json():
            data = resp.json()[0]
            return float(data["lat"]), float(data["lon"])
    except Exception as e:
        print(f"    - Geocoding error for {area_name}: {e}")
    return 12.9716, 77.5946

def query_overpass_businesses(tags, lat, lon, radius_m=4500):
    tag_queries = []
    for tag in tags:
        k, v = tag.split("=")
        for contact_attr in ['["website"]', '["contact:website"]', '["email"]', '["contact:email"]']:
            tag_queries.append(f'node(around:{radius_m},{lat},{lon})["{k}"="{v}"]{contact_attr};')
            tag_queries.append(f'way(around:{radius_m},{lat},{lon})["{k}"="{v}"]{contact_attr};')

    ql = f"[out:json][timeout:25];(" + "".join(tag_queries) + ");out center tags;"

    for mirror in OVERPASS_URLS:
        try:
            resp = requests.post(mirror, data={"data": ql}, headers=OSM_HEADERS, timeout=25)
            if resp.status_code == 200:
                elements = resp.json().get("elements", [])
                if elements:
                    return elements
        except Exception:
            continue

    # Fallback to general query if no elements found with contact tags
    tag_queries = []
    for tag in tags:
        k, v = tag.split("=")
        tag_queries.append(f'node(around:{radius_m},{lat},{lon})["{k}"="{v}"];')
        tag_queries.append(f'way(around:{radius_m},{lat},{lon})["{k}"="{v}"];')
    ql = f"[out:json][timeout:25];(" + "".join(tag_queries) + ");out center tags;"

    for mirror in OVERPASS_URLS:
        try:
            resp = requests.post(mirror, data={"data": ql}, headers=OSM_HEADERS, timeout=25)
            if resp.status_code == 200:
                return resp.json().get("elements", [])
        except Exception:
            continue
    return []

def extract_public_business_email_from_site(url, timeout=5):
    if not url:
        return "", "", ""
    if not url.startswith("http"):
        url = "https://" + url

    dom = extract_domain(url)
    if dom in DIRECTORY_DOMAINS:
        return "", "", ""

    if re.search(r"\.(pdf|docx?|xlsx?|zip|png|jpe?g)$", url, re.I):
        return "", "", ""

    page_html = ""
    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        page_html = resp.text

        mailtos = re.findall(r"mailto:([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", page_html)
        for em in mailtos:
            clean = normalize_email(em)
            if is_valid_email_syntax(clean) and not is_personal_email(clean) and not is_excluded_corporate_inbox(clean):
                return clean, url, page_html

        all_emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", page_html)
        for em in all_emails:
            clean = normalize_email(em)
            if is_valid_email_syntax(clean) and any(clean.startswith(p) for p in PREFERRED_INBOX_PREFIXES):
                return clean, url, page_html

        for em in all_emails:
            clean = normalize_email(em)
            if is_valid_email_syntax(clean) and not is_personal_email(clean) and not is_excluded_corporate_inbox(clean):
                return clean, url, page_html

        contact_links = re.findall(r'href=["\']([^"\']*(?:contact|about|reach)[^"\']*)["\']', page_html, re.I)
        checked_links = set()
        for clink in contact_links[:3]:
            if any(ext in clink.lower() for ext in [".css", ".js", ".png", ".jpg", ".jpeg", ".pdf", ".svg"]):
                continue
            sub_url = urljoin(url, clink)
            if sub_url in checked_links or sub_url == url:
                continue
            checked_links.add(sub_url)

            try:
                sub_resp = requests.get(sub_url, headers=BROWSER_HEADERS, timeout=timeout)
                sub_html = sub_resp.text
                sub_mailtos = re.findall(r"mailto:([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", sub_html)
                for em in sub_mailtos:
                    clean = normalize_email(em)
                    if is_valid_email_syntax(clean) and not is_personal_email(clean) and not is_excluded_corporate_inbox(clean):
                        return clean, sub_url, page_html + " " + sub_html
            except Exception:
                pass
    except Exception:
        pass

    return "", "", page_html

def find_leads_for_segment(segment, area_name="Indiranagar", limit=10):
    """
    Search and source verified leads for a given segment in Bengaluru.
    Enforces location verification, segment text confirmation, chain exclusions, and MX checks.
    """
    if segment not in SEGMENT_TAG_MAP:
        raise ValueError(f"Unknown segment: {segment}. Choose from: {', '.join(SEGMENTS)}")

    print(f"\n[LEAD DISCOVERY] Searching for '{segment}' near '{area_name}'...")
    lat, lon = geocode_bengaluru_area(area_name)
    tags = SEGMENT_TAG_MAP[segment]

    elements = query_overpass_businesses(tags, lat, lon, radius_m=4500)
    print(f"  Found {len(elements)} raw places in OpenStreetMap.")

    existing_leads = load_leads()
    new_leads = []

    for el in elements:
        if len(new_leads) >= limit:
            break

        el_tags = el.get("tags", {})
        biz_name = el_tags.get("name", "").strip()
        if not biz_name:
            continue

        raw_site = el_tags.get("website") or el_tags.get("contact:website") or ""
        osm_email = el_tags.get("email") or el_tags.get("contact:email") or ""
        address = el_tags.get("addr:street", "") + " " + el_tags.get("addr:city", "") + " " + el_tags.get("addr:postcode", "")

        # 1. Exclude corporate chains
        if is_chain_business(biz_name, raw_site, osm_email):
            continue

        target_email = ""
        source_url = ""
        site_html = ""

        # Step A: Validate email if in OSM tags
        if osm_email and is_valid_email_syntax(osm_email) and not is_personal_email(osm_email) and not is_excluded_corporate_inbox(osm_email):
            target_email = normalize_email(osm_email)
            source_url = raw_site or "OpenStreetMap"

        # Step B: If no email in OSM, visit the business's own site
        if not target_email and raw_site:
            scraped_email, scraped_source, site_html = extract_public_business_email_from_site(raw_site)
            if scraped_email:
                target_email = scraped_email
                source_url = scraped_source

        if not target_email:
            continue
        if extract_domain(target_email) in DIRECTORY_DOMAINS or extract_domain(raw_site) in DIRECTORY_DOMAINS:
            continue
        if is_chain_business(biz_name, raw_site, target_email):
            continue
        if is_excluded_corporate_inbox(target_email):
            continue

        # Step C: Deduplication check
        if is_duplicate_lead(target_email, raw_site, existing_leads + new_leads):
            continue

        # Step D: Location check & domain review check
        osm_combined_location = f"{raw_site} {address} {area_name} Bengaluru {biz_name}"
        loc_ok, loc_reason = verify_lead_location(website_url=raw_site, address_text=osm_combined_location, page_text=site_html)
        if not loc_ok:
            status_val = "rejected_location"
        else:
            is_flagged, _ = check_lead_domain_match(target_email, raw_site)
            status_val = "review_flagged" if is_flagged else "new"

        # Step E: Segment check from homepage / OSM tags
        combined_text = f"{biz_name} {site_html} {json.dumps(el_tags)}"
        seg_ok, matched_terms = confirm_segment_from_text(segment, combined_text)
        assigned_segment = segment if seg_ok else "unclassified"

        # Step F: MX Record check
        domain = extract_domain(target_email)
        if not check_mx_record(domain):
            continue

        # Step G: Extract clean service detail
        detail = extract_website_detail(raw_site, html=site_html) if raw_site else ""
        loc_label = f"({area_name}, Bengaluru)" if "bengaluru" not in (source_url or "").lower() else ""
        recorded_source = f"{source_url} {loc_label}".strip()

        new_lead = {
            "business_name": biz_name,
            "segment": assigned_segment,
            "website": raw_site,
            "email": target_email,
            "source_url": recorded_source,
            "status": status_val,
            "last_contacted": "",
            "website_detail": detail,
        }
        new_leads.append(new_lead)
        print(f"  + Added: {biz_name} | {assigned_segment} | {target_email} | Loc: {'PASS' if loc_ok else 'REJECT'}")

    if new_leads:
        all_leads = existing_leads + new_leads
        save_leads(all_leads)
        print(f"[SUCCESS] Sourced {len(new_leads)} new leads.")
    else:
        print("[INFO] No new unique leads found with verified emails in this run.")

    return new_leads

# ----------------- STEP 2: EMAIL TEMPLATES & BENEFIT-LED SUBJECTS -----------------

def count_words(text):
    if not text:
        return 0
    return len(text.strip().split())

SUBJECT_VARIANTS = {
    "gyms": [
        "Fewer member drop-offs, one simple dashboard",
        "Stop tracking gym renewals on spreadsheets",
        "Automated attendance and member renewal tracker",
    ],
    "clinics": [
        "Fewer no-shows, one simple dashboard",
        "Automate daily appointment logs and collections",
        "Stop managing clinic schedules on spreadsheets",
    ],
    "retail": [
        "Cut stockouts with one sales dashboard",
        "Automate inventory and store sales tracking",
        "Reconcile multichannel retail sales in minutes",
    ],
    "agencies": [
        "Automate client ad reporting in minutes",
        "Stop building manual ROAS client reports",
        "Client campaign metrics on one dashboard",
    ],
    "accounting": [
        "Track client GST deadlines without spreadsheets",
        "Automated client filing and reconciliation tracker",
        "Cut hours spent on client reconciliations",
    ],
    "manufacturers": [
        "Track production and inventory bottlenecks daily",
        "Automated factory floor and dispatch logs",
        "Stop tracking material inventory on spreadsheets",
    ],
    "coaching": [
        "Track fee installments and batch attendance",
        "Stop managing student batches on spreadsheets",
        "Automated student fee and attendance dashboard",
    ],
}

FOLLOWUP_SUBJECT_VARIANTS = [
    "Following up on data dashboard",
    "Quick follow-up: automated reporting dashboard",
    "Still open to a sample dashboard?",
]

SEGMENT_COPY = {
    "gyms": {
        "problem": "If tracking member attendance, renewals, and drop-offs across separate sheets is eating up your time, I can help.",
        "offer": "I turn messy gym data into simple dashboards and automated reports, at a fixed price, delivered in about 3 days.",
    },
    "clinics": {
        "problem": "If managing appointment logs, no-shows, and daily treatment collections across messy spreadsheets is painful, I can help.",
        "offer": "I turn messy clinic data into simple dashboards and automated reports, at a fixed price, delivered in about 3 days.",
    },
    "retail": {
        "problem": "If reconciling store sales, stockouts, and messy inventory sheets is slowing down your operations, I can help.",
        "offer": "I turn messy retail data into simple dashboards and automated reports, at a fixed price, delivered in about 3 days.",
    },
    "agencies": {
        "problem": "If spending hours manually pulling ad spend, ROAS, and campaign metrics into messy client sheets is draining your team, I can help.",
        "offer": "I turn messy agency data into simple dashboards and automated reports, at a fixed price, delivered in about 3 days.",
    },
    "accounting": {
        "problem": "If tracking client filing deadlines, GST reconciliations, and billing status across scattered Excel exports is getting unmanageable, I can help.",
        "offer": "I turn messy accounting data into simple dashboards and automated reports, at a fixed price, delivered in about 3 days.",
    },
    "manufacturers": {
        "problem": "If tracking raw material inventory, machine logs, and dispatch schedules across disconnected spreadsheets is causing delays, I can help.",
        "offer": "I turn messy manufacturing data into simple dashboards and automated reports, at a fixed price, delivered in about 3 days.",
    },
    "coaching": {
        "problem": "If tracking student batches, pending fee installments, and attendance across multiple spreadsheets is messy, I can help.",
        "offer": "I turn messy coaching data into simple dashboards and automated reports, at a fixed price, delivered in about 3 days.",
    },
}

UNIFIED_CTA = "Want me to make a free sample like it for your business, using dummy data?"

def get_signature_and_footer():
    site_url = os.environ.get("SITE_URL", "").strip()
    support_email = os.environ.get("OUTREACH_SUPPORT_EMAIL", os.environ.get("SMTP_REPLY_TO", "")).strip()
    return (
        "Best,\n"
        "Karan\n"
        "Sheetbolt · Automate the mess\n"
        f"{site_url}\n"
        "--\n"
        f"Reply STOP and I won't email again. Support: {support_email}"
    )

def get_rotated_subject(segment, email_address, email_type="initial"):
    if email_type == "followup":
        variants = FOLLOWUP_SUBJECT_VARIANTS
    else:
        variants = SUBJECT_VARIANTS.get(segment, SUBJECT_VARIANTS["gyms"])

    hash_val = int(hashlib.md5((email_address or "").encode("utf-8")).hexdigest(), 16)
    chosen = variants[hash_val % len(variants)]

    if count_words(chosen) >= 8:
        raise ValueError(f"Subject '{chosen}' exceeds 8 words limit ({count_words(chosen)} words).")
    return chosen

FOLLOWUP_SEGMENT_NOUNS = {
    "gyms": "gym",
    "clinics": "clinic",
    "retail": "retail",
    "agencies": "agency",
    "accounting": "accounting",
    "manufacturers": "manufacturing",
    "coaching": "coaching",
}

def generate_email(lead, email_type="initial", original_subject=None, message_id=None):
    """
    Generate tailored email adhering to:
    - Subject < 8 words (for initial or rotated subjects)
    - Body strictly < 90 words for initial, strictly < 70 words for follow-up (including greeting)
    - Follow-up template:
        Greeting line
        "Following up on my earlier note. In short: I turn messy <segment> data into simple dashboards and reports, at a fixed price, with a first version in about 3 days."
        "If it's useful, I can make a free sample using dummy data. Just reply 'yes'."
        "If it's not relevant, no worries. I won't email again."
        Signature & Footer
    - Initial template:
        Greeting line
        "If <segment problem>, I can help."
        "I turn messy <segment> data into simple dashboards and automated reports, at a fixed price, delivered in about 3 days."
        "Here's an example of what I build: <SAMPLE_DASHBOARD_URL>"
        "Want me to make a free sample like it for your business, using dummy data?"
        Signature & Footer
    """
    raw_name = lead.get("business_name", "")
    segment = lead.get("segment", "gyms")
    email = lead.get("email", "")

    greeting = get_greeting(raw_name)

    if email_type == "followup":
        if original_subject:
            if message_id:
                subject = f"Re: {original_subject}"
            else:
                subject = f"Following up: {original_subject}"
        else:
            subject = get_rotated_subject(segment, email, email_type="followup")

        seg_noun = FOLLOWUP_SEGMENT_NOUNS.get(segment, segment)
        body_main = (
            f"{greeting}\n\n"
            f"Following up on my earlier note. In short: I turn messy {seg_noun} data into simple dashboards and reports, at a fixed price, with a first version in about 3 days.\n\n"
            f"If it's useful, I can make a free sample using dummy data. Just reply 'yes'.\n\n"
            f"If it's not relevant, no worries. I won't email again."
        )
        body_limit = 70
    else:
        subject = get_rotated_subject(segment, email, email_type="initial")
        sample_url = os.environ.get("SAMPLE_DASHBOARD_URL", "").strip()
        sample_line = f"Here's an example of what I build: {sample_url}\n\n" if sample_url else ""
        copy = SEGMENT_COPY.get(segment, SEGMENT_COPY["gyms"])
        problem = copy["problem"]
        offer = copy["offer"]

        body_main = (
            f"{greeting}\n\n"
            f"{problem}\n\n"
            f"{offer}\n\n"
            f"{sample_line}"
            f"{UNIFIED_CTA}"
        )
        body_limit = 90

    signature = get_signature_and_footer()
    body = f"{body_main}\n\n{signature}"

    sub_words = count_words(subject)
    body_words = count_words(body_main)

    if not (email_type == "followup" and original_subject):
        if sub_words >= 8:
            raise ValueError(f"Subject exceeds 8 words ({sub_words} words): '{subject}'")

    if body_words >= body_limit:
        raise ValueError(f"Body exceeds {body_limit} words ({body_words} words): '{body_main}'")

    return subject, body

def generate_html_email(
    lead,
    email_type="initial",
    cid_logo=None,
    cid_dashboard=None,
    preview_logo_src=None,
    preview_dashboard_src=None,
    extra_images=None,
):
    """
    Generate clean single-column HTML email (max 600px width, inline CSS, system fonts).
    - Alt text: 'Sheetbolt logo' and 'Sample sales dashboard built on dummy data'.
    - Follow-up skips dashboard image and sample URL pitch.
    - Signature block: logo on left, Karan and company details on right, opt-out below.
    - Maximum 2 images per email.
    """
    raw_name = lead.get("business_name", "")
    segment = lead.get("segment", "gyms")

    greeting = get_greeting(raw_name)
    sample_url = os.environ.get("SAMPLE_DASHBOARD_URL", "").strip()
    site_url = os.environ.get("SITE_URL", "").strip()
    support_email = os.environ.get("OUTREACH_SUPPORT_EMAIL", os.environ.get("SMTP_REPLY_TO", "")).strip()

    logo_src = preview_logo_src or (f"cid:{cid_logo}" if cid_logo else None)
    dash_src = preview_dashboard_src or (f"cid:{cid_dashboard}" if cid_dashboard else None)

    # Maximum 2 images per email check
    used_images = [img for img in [logo_src, dash_src] if img is not None]
    if extra_images:
        used_images.extend(extra_images)
    if len(used_images) > 2:
        raise ValueError(f"Email contains {len(used_images)} images; maximum allowed is 2.")

    if email_type == "followup":
        seg_noun = FOLLOWUP_SEGMENT_NOUNS.get(segment, segment)
        content_paragraphs = [
            f"<p style=\"margin: 0 0 16px 0;\">{html_lib.escape(greeting)}</p>",
            f"<p style=\"margin: 0 0 16px 0;\">Following up on my earlier note. In short: I turn messy {html_lib.escape(seg_noun)} data into simple dashboards and reports, at a fixed price, with a first version in about 3 days.</p>",
            f"<p style=\"margin: 0 0 16px 0;\">If it's useful, I can make a free sample using dummy data. Just reply 'yes'.</p>",
            f"<p style=\"margin: 0 0 24px 0;\">If it's not relevant, no worries. I won't email again.</p>",
        ]
    else:
        copy = SEGMENT_COPY.get(segment, SEGMENT_COPY["gyms"])
        content_paragraphs = [
            f"<p style=\"margin: 0 0 16px 0;\">{html_lib.escape(greeting)}</p>",
            f"<p style=\"margin: 0 0 16px 0;\">{html_lib.escape(copy['problem'])}</p>",
            f"<p style=\"margin: 0 0 16px 0;\">{html_lib.escape(copy['offer'])}</p>",
        ]

        if sample_url:
            content_paragraphs.append(
                f"<p style=\"margin: 0 0 16px 0;\">Here's an example of what I build: <a href=\"{html_lib.escape(sample_url)}\" style=\"color: #2563eb; text-decoration: underline;\">{html_lib.escape(sample_url)}</a></p>"
            )
            # Dashboard image right under sample link wrapped in link to SAMPLE_DASHBOARD_URL
            if dash_src:
                content_paragraphs.append(
                    f"<p style=\"margin: 0 0 20px 0;\">"
                    f"<a href=\"{html_lib.escape(sample_url)}\" target=\"_blank\">"
                    f"<img src=\"{html_lib.escape(dash_src)}\" alt=\"Sample sales dashboard built on dummy data\" width=\"560\" style=\"max-width: 100%; width: 560px; height: auto; border: 1px solid #e2e8f0; border-radius: 6px; display: block;\" />"
                    f"</a>"
                    f"</p>"
                )

        content_paragraphs.append(
            f"<p style=\"margin: 0 0 24px 0;\">{html_lib.escape(UNIFIED_CTA)}</p>"
        )

    logo_td = ""
    if logo_src:
        logo_td = f"""<td style="vertical-align: top; padding-right: 18px; width: 140px;">
  <img src="{html_lib.escape(logo_src)}" alt="Sheetbolt logo" width="130" style="width: 130px; max-width: 180px; height: auto; display: block;" />
</td>"""

    signature_html = f"""<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse: collapse; margin-top: 20px; margin-bottom: 16px;">
<tr>
{logo_td}
<td style="vertical-align: top; font-size: 14px; line-height: 1.5; color: #1f2937;">
  <div style="margin-bottom: 2px;">Best,</div>
  <div style="font-weight: bold; color: #111827; margin-bottom: 2px;">Karan</div>
  <div style="color: #4b5563;">Sheetbolt &middot; Automate the mess</div>
  <div><a href="{html_lib.escape(site_url)}" style="color: #2563eb; text-decoration: none;">{html_lib.escape(site_url)}</a></div>
  <div><a href="mailto:{html_lib.escape(support_email)}" style="color: #4b5563; text-decoration: none;">{html_lib.escape(support_email)}</a></div>
  <div style="color: #6b7280; font-size: 13px;">Bengaluru, India</div>
</td>
</tr>
</table>
<div style="border-top: 1px solid #e5e7eb; padding-top: 12px; margin-top: 16px; font-size: 12px; color: #6b7280; line-height: 1.4;">
  Reply STOP and I won't email again. Support: <a href="mailto:{html_lib.escape(support_email)}" style="color: #6b7280; text-decoration: underline;">{html_lib.escape(support_email)}</a>
</div>"""

    body_html_inner = "\n".join(content_paragraphs)

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sheetbolt</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f9fafb; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
<div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; padding: 24px; border: 1px solid #e5e7eb; border-radius: 8px; font-size: 15px; line-height: 1.6; color: #1f2937;">
{body_html_inner}
{signature_html}
</div>
</body>
</html>"""
    return full_html

# ----------------- STEP 3: SENDING WINDOW, WARM-UP & SAFETY -----------------

def get_ist_now():
    return datetime.now(IST)

def is_in_sending_window(dt=None):
    if dt is None:
        dt = get_ist_now()

    weekday = dt.weekday()
    if weekday > 4:
        day_name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][weekday]
        return False, f"Today is {day_name} (weekend). Sending is only permitted on weekdays (Monday-Friday)."

    hour = dt.hour
    minute = dt.minute
    total_minutes = hour * 60 + minute
    start_minutes = 10 * 60
    end_minutes = 17 * 60

    if total_minutes < start_minutes or total_minutes >= end_minutes:
        return False, f"Current IST time is {dt.strftime('%H:%M')}. Sending is only permitted between 10:00 and 17:00 IST."

    return True, "Within active sending window (10:00-17:00 IST, Monday-Friday)."

def get_warmup_cap(log_filepath=OUTREACH_LOG_CSV, target_date=None):
    """
    Dynamic WARMUP daily cap based on first send date in outreach_log.csv:
    - Week 1 (days 0-6): 5/day
    - Week 2 (days 7-13): 10/day
    - Week 3+ (day 14+): 25/day
    """
    if target_date is None:
        target_date = get_ist_now().date()

    entries = load_outreach_log(log_filepath)
    first_send_date = None
    for e in entries:
        if e.get("status") == "sent" and e.get("email_type") != "test_send":
            ts = e.get("timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts).date()
                    if first_send_date is None or dt < first_send_date:
                        first_send_date = dt
                except Exception:
                    pass

    if first_send_date is None:
        return 5, 1, "Week 1 warmup (no prior sends)"

    days_elapsed = (target_date - first_send_date).days
    if days_elapsed < 7:
        return 5, 1, f"Week 1 warmup ({days_elapsed} days since first send)"
    elif days_elapsed < 14:
        return 10, 2, f"Week 2 warmup ({days_elapsed} days since first send)"
    else:
        cap = min(DAILY_SEND_CAP, HARD_DAILY_CAP_LIMIT)
        return cap, 3, f"Standard cap ({days_elapsed} days since first send)"

def log_circuit_breaker_override(reason, tripped_reason, window_stats):
    """Log circuit breaker override to file with ISO timestamp and user information."""
    entry = {
        "timestamp": get_ist_now().isoformat(),
        "reason": reason.strip(),
        "tripped_reason": tripped_reason,
        "window_stats": window_stats,
        "user": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
    }
    try:
        with open(OVERRIDE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{entry['timestamp']}] USER: {entry['user']} | REASON: {entry['reason']} | TRIPPED: {entry['tripped_reason']} | STATS: {entry['window_stats']}\n")
    except Exception as e:
        print(f"[!] Warning: Failed to write to {OVERRIDE_LOG_FILE}: {e}")

def get_daily_sent_count(log_filepath=OUTREACH_LOG_CSV, target_date=None):
    if target_date is None:
        target_date = get_ist_now().date()

    entries = load_outreach_log(log_filepath)
    count = 0
    for e in entries:
        if e.get("status") == "sent":
            ts = e.get("timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    if dt.date() == target_date:
                        count += 1
                except Exception:
                    pass
    return count

def load_circuit_breaker_state(state_file=CIRCUIT_BREAKER_STATE_FILE):
    """
    Load persistent circuit breaker state from JSON file.
    Returns (state_dict, is_valid).
    If missing or corrupt, returns ({}, False).
    """
    if not state_file or not os.path.exists(state_file):
        return {}, False
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data, True
            return {}, False
    except Exception as e:
        print(f"[!] Warning: Circuit breaker state file '{state_file}' is corrupt or unreadable: {e}")
        return {}, False

def save_circuit_breaker_state(state_data, state_file=CIRCUIT_BREAKER_STATE_FILE):
    """Save persistent circuit breaker state atomically."""
    if not state_file:
        return False
    tmp_path = str(state_file) + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)
        os.replace(tmp_path, state_file)
        return True
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False

def reset_circuit_breaker(reason, state_file=CIRCUIT_BREAKER_STATE_FILE, reset_log_file=RESET_BREAKER_LOG_FILE):
    """
    Manually reset a tripped circuit breaker. Requires a documented operational justification.
    Records the reset event to reset_log_file and clears the trip lock in state_file.
    """
    if not reason or not reason.strip():
        raise ValueError("A documented operational justification is required to reset the circuit breaker (--reason '<text>').")

    now_iso = get_ist_now().isoformat()
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    prev_state, _ = load_circuit_breaker_state(state_file)
    prev_reason = prev_state.get("reason", "unknown")

    log_line = f"[{now_iso}] USER: {user} | ACTION: RESET | REASON: {reason.strip()} | PRIOR_TRIP: {prev_reason}\n"
    try:
        with open(reset_log_file, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception as e:
        print(f"[!] Warning: Failed to write to {reset_log_file}: {e}")

    new_state = {
        "is_tripped": False,
        "is_reset": True,
        "reset_at": now_iso,
        "reset_reason": reason.strip(),
        "reset_by": user,
    }
    save_circuit_breaker_state(new_state, state_file=state_file)
    print(f"\n[CIRCUIT BREAKER RESET] Breaker successfully reset and unlocked by '{user}'.")
    print(f"Reason: {reason.strip()}")
    print(f"Logged to: {reset_log_file}\n")
    return True

def check_circuit_breaker(log_filepath=OUTREACH_LOG_CSV, state_file=None, window_size=None, enabled_files=None):
    """
    Persistent Bounce Circuit Breaker:
    - Evaluates across ALL initial send history using unique initial prospects (no file-scope exclusion).
    - Window rolloff is removed: adding more sends cannot rolloff or hide earlier bounces.
    - Tripped if unique initial bounces >= 3 OR (total initial prospects >= 20 and bounce rate > 5%).
    - Once tripped, the breaker stays tripped until manually reset via --reset-breaker --reason "<text>".
    - If state_file is missing or corrupt, recomputes directly from outreach_log.csv and never defaults to healthy.
    """
    if state_file is None and log_filepath == OUTREACH_LOG_CSV:
        state_file = CIRCUIT_BREAKER_STATE_FILE

    if state_file:
        state, is_valid = load_circuit_breaker_state(state_file)
        if is_valid and state.get("is_tripped", False):
            return True, state.get("rate", 0.0), state.get("bounces", 0), state.get("denominator", 0), state.get("reason", "Circuit breaker is tripped and locked. Requires manual reset: --reset-breaker --reason '<text>'")
        reset_at = state.get("reset_at") if (is_valid and state.get("is_reset", False)) else None
    else:
        reset_at = None

    entries = load_outreach_log(log_filepath)

    # Pass 1: find all bounced prospects
    bounced_prospects = set()
    for e in entries:
        st = (e.get("status") or "").lower()
        em = normalize_email(e.get("recipient_email", ""))
        ts = e.get("timestamp", "")
        if reset_at and ts and ts <= reset_at:
            continue
        if em and st == "bounced":
            bounced_prospects.add(em)

    # Pass 2: find unique prospects with initial attempts across all send history (regardless of file scope)
    initial_attempts = []
    seen_prospects = set()
    for e in entries:
        em = normalize_email(e.get("recipient_email", ""))
        e_type = (e.get("email_type") or "").lower()
        st = (e.get("status") or "").lower()
        ts = e.get("timestamp", "")
        if not em or e_type != "initial":
            continue
        if reset_at and ts and ts <= reset_at:
            continue
        if st in ["sent", "failed", "bounced"] and em not in seen_prospects:
            seen_prospects.add(em)
            initial_attempts.append(em)

    denom = len(initial_attempts)
    bounces_count = sum(1 for p in initial_attempts if p in bounced_prospects)
    rate = (bounces_count / denom) if denom > 0 else 0.0

    if bounces_count >= 3:
        reason = f"Circuit breaker tripped: {bounces_count} bounces recorded across send history ({bounces_count} unique bounces; {bounces_count}/{denom}; limit is 3). Breaker locked until manual reset."
        if state_file:
            save_circuit_breaker_state({
                "is_tripped": True,
                "tripped_at": get_ist_now().isoformat(),
                "reason": reason,
                "bounces": bounces_count,
                "denominator": denom,
                "rate": rate,
            }, state_file=state_file)
        return True, rate, bounces_count, denom, reason

    if denom >= 20 and rate > BOUNCE_RATE_LIMIT:
        reason = f"Circuit breaker tripped: bounce rate is {rate:.1%} ({bounces_count}/{denom}) across send history, exceeding 5% limit. Breaker locked until manual reset."
        if state_file:
            save_circuit_breaker_state({
                "is_tripped": True,
                "tripped_at": get_ist_now().isoformat(),
                "reason": reason,
                "bounces": bounces_count,
                "denominator": denom,
                "rate": rate,
            }, state_file=state_file)
        return True, rate, bounces_count, denom, reason

    return False, rate, bounces_count, denom, f"Circuit breaker healthy ({bounces_count}/{denom} bounces, rate {rate:.1%})."

def get_bounce_rate(log_filepath=OUTREACH_LOG_CSV):
    tripped, rate, bounce_cnt, denom, msg = check_circuit_breaker(log_filepath)
    return rate, bounce_cnt, denom


def calculate_business_days_between(d1, d2):
    if isinstance(d1, datetime):
        d1 = d1.date()
    if isinstance(d2, datetime):
        d2 = d2.date()

    if d1 > d2:
        d1, d2 = d2, d1

    business_days = 0
    curr = d1 + timedelta(days=1)
    while curr <= d2:
        if curr.weekday() < 5:
            business_days += 1
        curr += timedelta(days=1)

    return business_days

def get_lead_initial_thread_info(email, log_filepath=OUTREACH_LOG_CSV):
    """
    Search outreach_log.csv for the latest initial send to email.
    Returns (message_id, original_subject).
    """
    entries = load_outreach_log(log_filepath)
    clean = normalize_email(email)
    for entry in reversed(entries):
        if normalize_email(entry.get("recipient_email", "")) == clean:
            if entry.get("email_type") in ["initial", "test_send"] and entry.get("status") in ["sent", "test_sent", "dry_run"]:
                msg_id = (entry.get("message_id") or "").strip()
                orig_subj = (entry.get("original_subject") or "").strip() or (entry.get("subject") or "").strip()
                if orig_subj.startswith("[TEST] "):
                    orig_subj = orig_subj[7:]
                if msg_id or orig_subj:
                    return msg_id, orig_subj
    return "", ""

# Exact IMAP settings required by Gmail threading fallback
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
IMAP_SENT_FOLDER = '"[Gmail]/Sent Mail"'

def print_imap_login_error(user, error_msg):
    """Print exact IMAP settings and actionable instructions to enable IMAP in Gmail settings."""
    print("\n" + "=" * 70)
    print(f"[IMAP LOGIN FAILED] Could not connect or authenticate to Gmail IMAP for '{user}'.")
    print(f"Error details: {error_msg}")
    print("-" * 70)
    print("EXACT IMAP SETTINGS NEEDED BY THREADING FALLBACK:")
    print(f"  - Host:        {IMAP_HOST}")
    print(f"  - Port:        {IMAP_PORT} (SSL)")
    print(f"  - Sent Folder: {IMAP_SENT_FOLDER} (or 'Sent')")
    print("-" * 70)
    print("[ACTION REQUIRED] Please enable IMAP in your Gmail settings:")
    print("  1. Open Gmail in your web browser (https://mail.google.com).")
    print("  2. Click the gear icon in the top right and click 'See all settings'.")
    print("  3. Go to the 'Forwarding and POP/IMAP' tab.")
    print("  4. In the 'IMAP access' section, select 'Enable IMAP'.")
    print("  5. Click 'Save Changes' at the bottom of the page.")
    print("  6. If 2-Step Verification is active, confirm SMTP_PASS is a 16-character App Password.")
    print("=" * 70 + "\n")

def fetch_sent_message_id_via_imap(subject, to_email, user=None, password=None, timeout=10):
    """
    Connect to Gmail IMAP and fetch the real Message-ID assigned to sent email in Sent folder.
    """
    user = user or os.environ.get("SMTP_USER", "")
    password = password or os.environ.get("SMTP_PASS", "")
    if not user or not password:
        return None
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=timeout)
        mail.login(user, password)
        status, _ = mail.select(IMAP_SENT_FOLDER)
        if status != "OK":
            status, _ = mail.select("Sent")
        if status != "OK":
            mail.logout()
            return None

        status, data = mail.search(None, f'TO "{to_email}"')
        if status != "OK" or not data[0]:
            status, data = mail.search(None, "ALL")

        if status == "OK" and data[0]:
            msg_ids = data[0].split()
            for msg_num in reversed(msg_ids[-5:]):
                status, fetch_data = mail.fetch(msg_num, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT TO)])")
                if status == "OK" and fetch_data and isinstance(fetch_data[0], tuple):
                    msg_obj = py_email.message_from_bytes(fetch_data[0][1])
                    m_id = msg_obj.get("Message-ID", "")
                    m_subj = msg_obj.get("Subject", "")
                    if subject in m_subj or m_subj in subject:
                        mail.logout()
                        return m_id.strip()
        mail.logout()
    except Exception as e:
        print_imap_login_error(user, e)
    return None

# ----------------- STEP 4: SENDING ENGINE (DRY RUN, LIVE & TEST SEND) -----------------

def send_smtp_email(
    to_email,
    subject,
    body_text,
    lead=None,
    email_type="initial",
    check_urls_live=True,
    in_reply_to=None,
    references=None,
):
    verify_sender_safety(check_urls_live=check_urls_live)
    smtp_pass = os.environ.get("SMTP_PASS", "")
    if not smtp_pass:
        raise ValueError("SMTP_PASS is not set in environment (.env or .env.local).")

    user = os.environ.get("SMTP_USER", "")
    reply_to = os.environ.get("SMTP_REPLY_TO", user)
    sender_name = os.environ.get("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
    email_images = os.environ.get("EMAIL_IMAGES", "on").strip().lower()

    generated_msgid = make_msgid(domain="gmail.com")

    if email_images == "off" or lead is None:
        msg = MIMEText(body_text, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = f"{sender_name} <{user}>"
        msg["To"] = to_email
        msg["Reply-To"] = reply_to
        msg["Message-ID"] = generated_msgid
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references
    else:
        # Load processed images
        logo_data = get_processed_image("sheetbolt_logo.png", max_width=180)
        dash_data = None
        if email_type != "followup":
            dash_data = get_processed_image("sample_dashboard.png", max_width=560)

        cid_logo = "sheetbolt_logo" if logo_data else None
        cid_dashboard = "sample_dashboard" if dash_data else None

        html_content = generate_html_email(
            lead,
            email_type=email_type,
            cid_logo=cid_logo,
            cid_dashboard=cid_dashboard,
        )

        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        msg["From"] = f"{sender_name} <{user}>"
        msg["To"] = to_email
        msg["Reply-To"] = reply_to
        msg["Message-ID"] = generated_msgid
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        alt_part = MIMEMultipart("alternative")
        msg.attach(alt_part)

        text_part = MIMEText(body_text, "plain", "utf-8")
        alt_part.attach(text_part)

        html_part = MIMEText(html_content, "html", "utf-8")
        alt_part.attach(html_part)

        if logo_data:
            from email.mime.image import MIMEImage
            img = MIMEImage(logo_data[1], "png")
            img.add_header("Content-ID", f"<{cid_logo}>")
            img.add_header("Content-Disposition", "inline", filename="sheetbolt_logo.png")
            msg.attach(img)

        if dash_data and email_type != "followup":
            from email.mime.image import MIMEImage
            img = MIMEImage(dash_data[1], "png")
            img.add_header("Content-ID", f"<{cid_dashboard}>")
            img.add_header("Content-Disposition", "inline", filename="sample_dashboard.png")
            msg.attach(img)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(user, smtp_pass)
        server.send_message(msg)

    # Check if Gmail rewritten Message-ID
    real_msgid = fetch_sent_message_id_via_imap(subject, to_email, user, smtp_pass)
    print(f"Message-ID generated:            {generated_msgid}")
    print(f"Message-ID assigned by Gmail:    {real_msgid if real_msgid else generated_msgid}")
    final_msgid = real_msgid or generated_msgid
    print(f"Saved Message-ID:                {final_msgid}")

    return final_msgid, msg

def save_preview_draft(lead, subject, body, email_type="initial", in_reply_to=None):
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", lead.get("business_name", "lead")).lower()
    txt_filename = f"{lead.get('segment', 'lead')}_{slug}_{email_type}.txt"
    html_filename = f"{lead.get('segment', 'lead')}_{slug}_{email_type}.html"
    txt_filepath = os.path.join(PREVIEW_DIR, txt_filename)
    html_filepath = os.path.join(PREVIEW_DIR, html_filename)

    user = os.environ.get("SMTP_USER", "")
    sender_name = os.environ.get("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
    from_line = f"{sender_name} <{user}>"
    sample_url = os.environ.get("SAMPLE_DASHBOARD_URL", "")

    # Images
    logo_data = get_processed_image("sheetbolt_logo.png", max_width=180)
    dash_data = None
    if email_type != "followup":
        dash_data = get_processed_image("sample_dashboard.png", max_width=560)

    images_included = []
    if logo_data:
        images_included.append(f"Sheetbolt Logo ({logo_data[0]}, <= 180px, cid:sheetbolt_logo)")
    if dash_data:
        images_included.append(f"Sample Dashboard ({dash_data[0]}, <= 560px, cid:sample_dashboard)")

    images_str = ", ".join(images_included) if images_included else "None"

    # Extract body only for word count
    body_only = body.split("Best,\n")[0].strip() if "Best,\n" in body else body
    body_limit = 70 if email_type == "followup" else 90

    in_reply_to_line = ""
    if email_type == "followup":
        in_reply_to_val = in_reply_to or "<placeholder-initial-msgid@sheetboltanalytics.netlify.app>"
        in_reply_to_line = f"IN-REPLY-TO: {in_reply_to_val}\n"

    with open(txt_filepath, "w", encoding="utf-8") as f:
        f.write(f"FROM: {from_line}\n")
        f.write(f"TO: {lead.get('email')}\n")
        f.write(f"BUSINESS: {lead.get('business_name')}\n")
        f.write(f"SEGMENT: {lead.get('segment')}\n")
        f.write(f"TYPE: {email_type}\n")
        f.write(f"SUBJECT: {subject} ({count_words(subject)} words)\n")
        if in_reply_to_line:
            f.write(in_reply_to_line)
        if sample_url and email_type != "followup":
            f.write(f"SAMPLE LINK: {sample_url}\n")
        f.write(f"INCLUDED IMAGES: {images_str}\n")
        f.write(f"BODY ({count_words(body_only)} words - limit < {body_limit}):\n")
        f.write("=" * 60 + "\n")
        f.write(body)
        f.write("\n" + "=" * 60 + "\n")

    # Generate .html preview with base64 data URIs so opening directly in browser shows images
    import base64
    preview_logo_src = None
    if logo_data:
        b64 = base64.b64encode(logo_data[1]).decode("ascii")
        preview_logo_src = f"data:image/png;base64,{b64}"

    preview_dash_src = None
    if dash_data:
        b64 = base64.b64encode(dash_data[1]).decode("ascii")
        preview_dash_src = f"data:image/png;base64,{b64}"

    html_content = generate_html_email(
        lead,
        email_type=email_type,
        cid_logo="sheetbolt_logo" if logo_data else None,
        cid_dashboard="sample_dashboard" if dash_data else None,
        preview_logo_src=preview_logo_src,
        preview_dashboard_src=preview_dash_src,
    )

    with open(html_filepath, "w", encoding="utf-8") as f:
        f.write(html_content)

    return txt_filepath, html_filepath, images_included

def run_test_send(dry_run=False):
    """--test-send: Sends the first draft strictly to addresses in TEST_RECIPIENTS from .env."""
    verify_sender_safety(check_urls_live=not dry_run)
    recipients = [a.strip() for a in os.environ.get("TEST_RECIPIENTS", "").split(",") if a.strip()]
    if not recipients:
        print("[ERROR] TEST_RECIPIENTS is not configured in .env or .env.local.")
        print("Add TEST_RECIPIENTS=your_test_email@gmail.com to your .env file.")
        return

    leads = load_leads()
    eligible = [
        l for l in leads
        if l.get("status") not in ["unsubscribed", "replied", "bounced", "rejected_location", "review_flagged"]
        and l.get("segment") != "unclassified"
        and not is_chain_business(l.get("business_name", ""), l.get("website", ""), l.get("email", ""))
        and not is_excluded_corporate_inbox(l.get("email", ""))
    ]
    if not eligible:
        print("[!] No eligible leads found in leads.csv to generate test draft from.")
        return

    lead = eligible[0]
    subject, body = generate_email(lead, email_type="initial")
    test_subject = f"[TEST] {subject}"

    user = os.environ.get("SMTP_USER", "")
    sender_name = os.environ.get("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
    from_line = f"{sender_name} <{user}>"
    sample_url = os.environ.get("SAMPLE_DASHBOARD_URL", "")

    logo_data = get_processed_image("sheetbolt_logo.png", max_width=180)
    dash_data = get_processed_image("sample_dashboard.png", max_width=560)
    images_included = []
    if logo_data:
        images_included.append("Sheetbolt Logo (cid:sheetbolt_logo)")
    if dash_data:
        images_included.append("Sample Dashboard (cid:sample_dashboard)")

    print("\n" + "=" * 60)
    print(f"RENDERED TEST EMAIL OUTPUT (Preview for '{lead.get('business_name')}'):")
    print("=" * 60)
    print(f"FROM:                     {from_line}")
    print(f"SUBJECT:                  {test_subject}")
    print(f"SEGMENT:                  {lead.get('segment')}")
    print(f"SAMPLE LINK:              {sample_url}")
    print(f"INCLUDED IMAGES:          {', '.join(images_included) if images_included else 'None'}")
    print(f"WORD COUNT (body only):   {count_words(body.split('Best,\n')[0].strip())} words (Limit: < 90)")
    print(f"TARGET TEST RECIPIENT(S): {', '.join(recipients)}")
    print("-" * 60)
    print(body)
    print("=" * 60 + "\n")

    if dry_run:
        print("[DRY RUN] Skipping live SMTP send for test email.")
        return

    for r in recipients:
        try:
            final_msgid, _ = send_smtp_email(r, test_subject, body, lead=lead, email_type="initial", check_urls_live=True)
            now_iso = get_ist_now().isoformat()
            append_outreach_log({
                "timestamp": now_iso,
                "recipient_email": r,
                "business_name": f"[TEST for {lead.get('business_name')}]",
                "segment": lead.get("segment", ""),
                "email_type": "test_send",
                "subject": test_subject,
                "status": "test_sent",
                "error_message": "",
                "message_id": final_msgid,
                "original_subject": test_subject,
            })
            print(f" [OK] Successfully sent test email to {r}")
        except Exception as e:
            print(f" [FAIL] Failed to send to {r}: {e}")
            if "WebLoginRequired" in str(e) or "534" in str(e):
                print("\n" + "=" * 65)
                print("[GOOGLE SECURITY ALERT: WebLoginRequired]")
                print("Google requires browser verification for this account before SMTP send:")
                print("1. Log into Gmail in your browser at https://mail.google.com as sheetbolt.analytics@gmail.com")
                print("2. Visit: https://accounts.google.com/DisplayUnlockCaptcha")
                print("3. Click 'Continue' to unlock access.")
                print("4. Re-run: python outreach_pipeline.py --test-send")
                print("=" * 65 + "\n")

def run_test_followup(dry_run=False):
    """--test-followup: Sends the follow-up as a real threaded reply to the test email sent by --test-send, strictly to TEST_RECIPIENTS."""
    verify_sender_safety(check_urls_live=not dry_run)
    recipients = [a.strip() for a in os.environ.get("TEST_RECIPIENTS", "").split(",") if a.strip()]
    if not recipients:
        print("[ERROR] TEST_RECIPIENTS is not configured in .env or .env.local.")
        print("Add TEST_RECIPIENTS=your_test_email@gmail.com to your .env file.")
        return

    leads = load_leads()
    eligible = [
        l for l in leads
        if l.get("status") not in ["unsubscribed", "replied", "bounced", "rejected_location", "review_flagged"]
        and l.get("segment") != "unclassified"
        and not is_chain_business(l.get("business_name", ""), l.get("website", ""), l.get("email", ""))
        and not is_excluded_corporate_inbox(l.get("email", ""))
    ]
    if not eligible:
        print("[!] No eligible leads found in leads.csv to generate test draft from.")
        return

    lead = eligible[0]

    for r in recipients:
        msg_id, orig_subj = get_lead_initial_thread_info(r)

        if msg_id:
            followup_subject = f"Re: {orig_subj}" if orig_subj else "Re: [TEST] Quick question"
            in_reply_to = msg_id
            references = msg_id
        else:
            followup_subject = f"Following up: {orig_subj}" if orig_subj else "Following up: automated reporting"
            in_reply_to = None
            references = None

        _, body = generate_email(lead, email_type="followup", original_subject=orig_subj, message_id=msg_id)

        user = os.environ.get("SMTP_USER", "")
        sender_name = os.environ.get("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
        from_line = f"{sender_name} <{user}>"

        logo_data = get_processed_image("sheetbolt_logo.png", max_width=180)
        images_included = []
        if logo_data:
            images_included.append("Sheetbolt Logo (cid:sheetbolt_logo)")

        print("\n" + "=" * 60)
        print(f"RENDERED TEST FOLLOW-UP OUTPUT (Preview for '{lead.get('business_name')}'):")
        print("=" * 60)
        print(f"FROM:                     {from_line}")
        print(f"SUBJECT:                  {followup_subject}")
        print(f"IN-REPLY-TO:              {in_reply_to or 'None'}")
        print(f"REFERENCES:               {references or 'None'}")
        print(f"SEGMENT:                  {lead.get('segment')}")
        print(f"INCLUDED IMAGES:          {', '.join(images_included) if images_included else 'None'}")
        print(f"WORD COUNT:               {count_words(body.split('Best,\n')[0].strip())} words (Limit: < 70)")
        print(f"TARGET TEST RECIPIENT(S): {r}")
        print("-" * 60)
        print(body)
        print("=" * 60 + "\n")

        if dry_run:
            print(f"[DRY RUN] Skipping live SMTP send for test follow-up to {r}.")
            continue

        try:
            final_msgid, _ = send_smtp_email(
                r,
                followup_subject,
                body,
                lead=lead,
                email_type="followup",
                check_urls_live=True,
                in_reply_to=in_reply_to,
                references=references,
            )
            now_iso = get_ist_now().isoformat()
            append_outreach_log({
                "timestamp": now_iso,
                "recipient_email": r,
                "business_name": f"[TEST FOLLOWUP for {lead.get('business_name')}]",
                "segment": lead.get("segment", ""),
                "email_type": "test_followup",
                "subject": followup_subject,
                "status": "test_sent",
                "error_message": "",
                "message_id": final_msgid,
                "original_subject": orig_subj,
            })
            print(f"[TEST FOLLOWUP SENT] Delivered threaded test follow-up to {r}.")
        except Exception as e:
            print(f"[TEST FOLLOWUP ERROR] Failed to send to {r}: {e}")
            if "WebLoginRequired" in str(e) or "534" in str(e):
                print("\n" + "=" * 65)
                print("[GOOGLE SECURITY ALERT: WebLoginRequired]")
                print("Google requires browser verification for this account before SMTP send:")
                print("1. Log into Gmail in your browser at https://mail.google.com as sheetbolt.analytics@gmail.com")
                print("2. Visit: https://accounts.google.com/DisplayUnlockCaptcha")
                print("3. Click 'Continue' to unlock access.")
                print("4. Re-run: python outreach_pipeline.py --test-followup")
                print("=" * 65 + "\n")

def check_lead_followup_qualification(lead, log_entries=None, log_filepath=OUTREACH_LOG_CSV, today=None):
    """
    Check if a lead qualifies for a follow-up email.
    Criteria:
    - outreach_log.csv shows a successful initial send (email_type == 'initial' and status == 'sent')
      at least 4 business days ago.
    - No reply (lead status != 'replied' and no log entry with status == 'replied' or email_type == 'reply').
    - No unsubscribe (lead status != 'unsubscribed' and no log entry with status == 'unsubscribed' or email_type == 'unsubscribe').
    - No bounce (lead status != 'bounced' and no log entry with status == 'bounced').
    - No follow-up already sent (lead status != 'contacted_2' and no log entry with email_type == 'followup' and status == 'sent').
    Returns (is_qualified: bool, reason: str, send_date: Optional[date], business_days_elapsed: int).
    """
    st = lead.get("status", "new")
    if st in ["unsubscribed", "replied", "bounced", "rejected_location", "review_flagged", "unclassified_hold"]:
        return False, f"Lead status in leads.csv is '{st}'", None, 0
    if st == "contacted_2":
        return False, "Follow-up already sent (lead status is 'contacted_2')", None, 0

    clean_email = normalize_email(lead.get("email", ""))
    if not clean_email:
        return False, "Lead has no email address", None, 0

    if log_entries is None:
        log_entries = load_outreach_log(log_filepath)

    lead_logs = [e for e in log_entries if normalize_email(e.get("recipient_email", "")) == clean_email]

    # Check for disqualifications in outreach_log.csv
    for e in lead_logs:
        e_status = (e.get("status") or "").lower()
        e_type = (e.get("email_type") or "").lower()
        if e_status == "replied" or e_type == "reply":
            return False, "Lead has replied according to outreach log", None, 0
        if e_status == "unsubscribed" or e_type == "unsubscribe":
            return False, "Lead has unsubscribed according to outreach log", None, 0
        if e_status == "bounced":
            return False, "Previous outreach bounced according to outreach log", None, 0
        if e_type == "followup" and e_status == "sent":
            return False, "Follow-up already sent according to outreach log", None, 0

    # Check for successful initial send
    initial_sends = [
        e for e in lead_logs
        if (e.get("email_type") or "").lower() == "initial" and (e.get("status") or "").lower() == "sent"
    ]
    if not initial_sends:
        return False, "Never emailed: no successful initial send found in outreach log", None, 0

    # Get latest successful initial send
    latest_send = initial_sends[-1]
    ts = latest_send.get("timestamp", "")
    try:
        send_date = datetime.fromisoformat(ts).date()
    except Exception:
        return False, f"Invalid timestamp '{ts}' in outreach log", None, 0

    if today is None:
        today = get_ist_now().date()

    bdays = calculate_business_days_between(send_date, today)
    if bdays < 4:
        return False, f"Initial send on {send_date.isoformat()} was only {bdays} business days ago (< 4 required)", send_date, bdays

    return True, f"Initial send on {send_date.isoformat()} ({bdays} business days elapsed)", send_date, bdays

def get_global_suppressed_emails(log_filepath=OUTREACH_LOG_CSV):
    """
    Collect all bounced and unsubscribed email addresses across:
    1. outreach_log.csv (status in ['bounced', 'unsubscribed'])
    2. All lead CSV files in directory (leads*.csv)
    Returns set of lowercase normalized email addresses.
    """
    suppressed = set()
    entries = load_outreach_log(log_filepath)
    for e in entries:
        st = (e.get("status") or "").lower()
        em = normalize_email(e.get("recipient_email", ""))
        if em and st in ["bounced", "unsubscribed"]:
            suppressed.add(em)

    import glob
    lead_files = set(glob.glob("leads*.csv"))
    if LEADS_CSV:
        lead_files.add(LEADS_CSV)
    for fpath in lead_files:
        try:
            for row in load_leads(fpath):
                em = normalize_email(row.get("email", ""))
                st = (row.get("status") or "").lower()
                if em and st in ["bounced", "unsubscribed"]:
                    suppressed.add(em)
        except Exception:
            pass
    return suppressed

def get_eligible_leads(leads, followup_mode=False, allowed_cities=None, log_filepath=OUTREACH_LOG_CSV, segment_filter=None, today=None):
    """
    Filter leads to only those eligible for outreach:
    - Send and dry-run only pick leads with status == 'new' AND segment != 'unclassified'
      (or for followup_mode: qualifying initial send >= 4 business days ago in outreach_log.csv).
    - Must NOT be segment == 'unclassified' or status == 'unclassified_hold'.
    - Must NOT be chain or excluded corporate inbox.
    - Must pass location verification.
    - Must not be flagged by domain match check.
    - Must not be bounced or unsubscribed anywhere (global cross-CSV suppression).
    """
    if allowed_cities is None:
        allowed_cities = get_allowed_cities()
    if today is None:
        today = get_ist_now().date()
    eligible_leads = []
    log_entries = load_outreach_log(log_filepath) if followup_mode else None
    suppressed_emails = get_global_suppressed_emails(log_filepath)

    for lead in leads:
        st = lead.get("status", "new")
        segment = lead.get("segment", "unclassified")
        email = lead.get("email", "")
        norm_email = normalize_email(email)

        # Global cross-file suppression check
        if norm_email in suppressed_emails:
            continue

        if segment_filter and segment != segment_filter:
            continue

        # Exclude unclassified segments and unclassified_hold status
        if segment == "unclassified" or st == "unclassified_hold":
            continue

        if st in ["unsubscribed", "replied", "bounced", "rejected_location", "review_flagged"]:
            continue

        if not followup_mode and st != "new":
            continue

        biz_name = lead.get("business_name", "")
        website = lead.get("website", "")
        email = lead.get("email", "")

        # Exclude chains and corporate inboxes
        if is_chain_business(biz_name, website, email):
            continue
        if is_excluded_corporate_inbox(email):
            continue

        # Location check
        loc_ok, _ = verify_lead_location(website, lead.get("source_url", ""), f"{biz_name} {lead.get('website_detail', '')}", allowed_cities)
        if not loc_ok:
            continue

        # Domain and name review check
        name_flagged, _ = check_lead_name_vs_domain(biz_name, email, website)
        if name_flagged:
            continue

        is_flagged, _ = check_lead_domain_match(email, website)
        if is_flagged:
            continue

        # Live mailbox check (reject invalid MX or server 550)
        mb_ok, _ = verify_email_mailbox_live(email)
        if not mb_ok:
            continue

        if followup_mode:
            qual_ok, qual_reason, s_date, bdays = check_lead_followup_qualification(
                lead, log_entries=log_entries, today=today
            )
            if qual_ok:
                lead["_followup_qualification"] = qual_reason
                eligible_leads.append(lead)
        else:
            if st == "new":
                eligible_leads.append(lead)

    return eligible_leads

def run_outreach(send_live=False, followup_mode=False, limit=None, force_window=False, warmup=True, segment_filter=None, override_reason="", leads_filepath=None, log_filepath=None, skip_location_audit=False, override_circuit_breaker=False, enabled_files=None, state_file=None):
    """Main outreach execution loop with dry-run default, location audit, segment audit, and review flagging."""
    if enabled_files is None:
        enabled_files = ENABLED_LEAD_FILES
    if leads_filepath is None:
        leads_filepath = enabled_files[0] if enabled_files else LEADS_CSV
    if log_filepath is None:
        log_filepath = OUTREACH_LOG_CSV

    if leads_filepath not in enabled_files and leads_filepath in ["leads_abroad_agencies.csv", "leads_austin.csv"]:
        print(f"\n[ERROR] '{leads_filepath}' is disabled by default in ENABLED_LEAD_FILES.")
        print("        Verify UK/EU GDPR & PECR regulations or US CAN-SPAM Act compliance before enabling.")
        return

    # 1. Audit locations in leads file
    if not skip_location_audit:
        audit_leads_location(leads_filepath)


    # 2. Audit segment classification (reclassifies Raintree Partners and others)
    _, seg_changes = audit_leads_segment(leads_filepath)
    if seg_changes:
        print("\n" + "=" * 65)
        print(f"[SEGMENT AUDIT] {len(seg_changes)} lead(s) reclassified:")
        for ch_lead, old_s, new_s, reason in seg_changes:
            print(f"  - {ch_lead.get('business_name')} ({mask_email(ch_lead.get('email', ''))}): {old_s} -> {new_s} ({reason})")
        print("=" * 65)

    # 3. Audit corporate chains, national brands, blocked inboxes, and domain mismatches
    flagged_leads = audit_leads_domain_match(leads_filepath)
    if flagged_leads:
        print("\n" + "=" * 65)
        print(f"[REVIEW FLAGGED AUDIT] {len(flagged_leads)} lead(s) flagged for review:")
        for fl_lead, r_reason in flagged_leads:
            print(f"  - {fl_lead.get('business_name')} ({mask_email(fl_lead.get('email', ''))}): {r_reason}")
        print("=" * 65)

    # 3b. Audit mailboxes (live MX and SMTP handshake check)
    mb_flagged = audit_leads_mailboxes(leads_filepath)
    if mb_flagged:
        print("\n" + "=" * 65)
        print(f"[MAILBOX AUDIT] {len(mb_flagged)} lead(s) flagged for invalid mailboxes:")
        for fl_lead, r_reason in mb_flagged:
            print(f"  - {fl_lead.get('business_name')} ({mask_email(fl_lead.get('email', ''))}): {r_reason}")
        print("=" * 65)


    # 4. Print segment and status summary (with warnings for < 5 leads)
    print_segment_and_status_audit(leads_filepath)

    # 5. Print remaining retail leads still marked 'new'
    print_new_retail_leads(leads_filepath)

    leads = load_leads(leads_filepath)
    if not leads:
        print(f"[!] No leads found in {leads_filepath}. Run with --find-leads first.")
        return

    # Check circuit breaker
    is_tripped, rate, bounce_cnt, sent_cnt, cb_reason = check_circuit_breaker(log_filepath=log_filepath, state_file=state_file, enabled_files=enabled_files)
    if is_tripped:
        actual_reason = override_reason or ("Operator override via flag" if override_circuit_breaker else "")
        if actual_reason:
            log_circuit_breaker_override(
                reason=actual_reason,
                tripped_reason=cb_reason,
                window_stats=f"{bounce_cnt}/{sent_cnt} bounces ({rate:.1%})"
            )
            print("\n" + "!" * 75)
            print("⚠️  [CIRCUIT BREAKER OVERRIDE ACTIVE]  ⚠️")
            print(f"Condition: {cb_reason}")
            print(f"Operator Justification: {actual_reason}")
            print(f"Logged to: {OVERRIDE_LOG_FILE}")
            print("WARNING: Bypassing circuit breaker safety lock for THIS RUN ONLY.")
            print("Pre-send mailbox verification and suppression lists remain fully active.")
            print("!" * 75 + "\n")
        else:
            print("\n" + "=" * 75)
            print(f"[CIRCUIT BREAKER TRIGGERED] {cb_reason}")
            print("Halting all sending to protect sender domain reputation.")
            print("To override for a single run, supply justification via:")
            print("  --override-reason \"<detailed operational justification>\"")
            print("=" * 75 + "\n")
            return

    # Sample link check if live
    if send_live:
        sample_url = os.environ.get("SAMPLE_DASHBOARD_URL", "").strip()
        if sample_url:
            print(f"[SAMPLE LINK] Including demo URL: {sample_url}")
        else:
            print("[SAMPLE LINK] No sample URL set in .env. Using conversational zero-link reply CTA.")

        try:
            verify_sender_safety(check_urls_live=True)
        except Exception as e:
            print(f"\n[SENDER SAFETY ERROR] {e}")
            return

        if not force_window:
            is_allowed, reason = is_in_sending_window()
            if not is_allowed:
                print(f"\n[SENDING PAUSED] {reason}")
                print("To preview drafts without sending, omit the --send flag.")
                return

    # Daily cap check with hard safety guard
    today_sent = get_daily_sent_count()
    if warmup:
        eff_cap, warmup_week, warmup_desc = get_warmup_cap()
    else:
        eff_cap = min(DAILY_SEND_CAP, HARD_DAILY_CAP_LIMIT)
        warmup_week, warmup_desc = 3, f"Standard cap (warmup disabled; guarded by {HARD_DAILY_CAP_LIMIT}/day limit)"

    # Hard guard: eff_cap can never exceed HARD_DAILY_CAP_LIMIT
    eff_cap = min(eff_cap, HARD_DAILY_CAP_LIMIT)

    remaining_cap = max(0, eff_cap - today_sent)
    if send_live and remaining_cap <= 0:
        print(f"\n[DAILY CAP REACHED] Already sent {today_sent}/{eff_cap} emails today ({warmup_desc}). Halting sending.")
        return

    # Filter eligible leads
    allowed_cities = [] if skip_location_audit else get_allowed_cities()
    new_eligible_leads = get_eligible_leads(leads, followup_mode=False, allowed_cities=allowed_cities, log_filepath=log_filepath, segment_filter=segment_filter)
    eligible_leads = get_eligible_leads(leads, followup_mode=followup_mode, allowed_cities=allowed_cities, log_filepath=log_filepath, segment_filter=segment_filter) if followup_mode else new_eligible_leads

    # Print real emailable lead count per segment and in total
    emailable_counts = Counter(l.get("segment", "unknown") for l in new_eligible_leads)
    total_emailable = len(new_eligible_leads)

    print("\n" + "=" * 65)
    print("REAL EMAILABLE LEADS (status == 'new' and segment != 'unclassified')")
    print("=" * 65)
    for seg in SEGMENTS:
        cnt = emailable_counts.get(seg, 0)
        print(f"  - {seg:15s}: {cnt:3d} leads")
    print("-" * 65)
    print(f"  TOTAL EMAILABLE LEADS: {total_emailable}")
    print("=" * 65)


    if not eligible_leads:
        mode_str = "follow-up" if followup_mode else "initial outreach"
        reason_str = (
            "no leads with an initial send >= 4 business days ago without reply/unsubscribe/bounce/prior followup"
            if followup_mode
            else "after location, segment, chain, and inbox filters"
        )
        print(f"\n[INFO] No leads eligible for {mode_str} at this time ({reason_str}).")
        return

    batch_limit = min(limit or len(eligible_leads), remaining_cap if send_live else (limit or len(eligible_leads)))
    if not send_live and limit and limit >= 2:
        by_seg = {}
        for l in eligible_leads:
            s = l.get("segment", "unknown")
            by_seg.setdefault(s, []).append(l)
        target_leads = []
        seg_keys = list(by_seg.keys())
        idx = 0
        while len(target_leads) < batch_limit and any(by_seg.values()):
            curr_seg = seg_keys[idx % len(seg_keys)]
            if by_seg[curr_seg]:
                target_leads.append(by_seg[curr_seg].pop(0))
            idx += 1
            if not any(by_seg.values()):
                break
    else:
        target_leads = eligible_leads[:batch_limit]

    print("\n" + "=" * 65)
    print(f"OUTREACH RUN ({'LIVE SENDING' if send_live else 'DRY RUN / PREVIEW'})")
    print("=" * 65)
    print(f"Eligible Leads: {len(eligible_leads)} | Target Batch: {len(target_leads)}")
    print(f"Today's Sent Count: {today_sent}/{eff_cap} ({warmup_desc})")
    print(f"Bounce Status: {bounce_cnt}/{sent_cnt} sends ({cb_reason})")
    print("=" * 65)

    if followup_mode:
        print("\n" + "=" * 65)
        print(f"QUALIFIED FOLLOW-UP CANDIDATES ({len(eligible_leads)} eligible):")
        print("=" * 65)
        for idx, l in enumerate(target_leads, 1):
            q_res = l.get("_followup_qualification", "")
            print(f"  {idx}. {l.get('business_name')} ({l.get('email')}) -> {q_res}")
        print("=" * 65)

    preview_outputs = []

    for idx, lead in enumerate(target_leads, 1):
        email_type = "followup" if followup_mode else "initial"
        in_reply_to = None
        references = None
        orig_subj = None

        if followup_mode:
            msg_id, orig_subj = get_lead_initial_thread_info(lead["email"])
            if msg_id:
                in_reply_to = msg_id
                references = msg_id
            else:
                if not send_live:
                    in_reply_to = "<placeholder-initial-msgid@sheetboltanalytics.netlify.app>"

        subject, body = generate_email(
            lead,
            email_type=email_type,
            original_subject=orig_subj,
            message_id=in_reply_to if followup_mode else None,
        )
        txt_path, html_path, img_list = save_preview_draft(
            lead, subject, body, email_type=email_type, in_reply_to=in_reply_to
        )

        # Verification details for reporting
        loc_ok, loc_res = verify_lead_location(lead.get("website", ""), lead.get("source_url", ""), f"{lead.get('business_name', '')} {lead.get('website_detail', '')}", allowed_cities)
        seg_ok, seg_terms = confirm_segment_from_text(lead.get("segment", ""), f"{lead.get('business_name', '')} {lead.get('website_detail', '')}")

        preview_outputs.append((lead, subject, body, txt_path, html_path, img_list, loc_res, seg_terms, in_reply_to))

        if send_live:
            # Pre-send live mailbox check to eliminate any bounce risk
            mb_res = verify_email_mailbox_live(lead["email"])
            probe_path = getattr(mb_res, "probe_path", "probe_unknown")
            if not mb_res.is_valid:
                print(f"\n[PRE-SEND VERIFICATION REJECTED] Skipping {lead['business_name']} ({mask_email(lead['email'])}): {mb_res.reason} [{probe_path}]")
                lead["status"] = "review_flagged"
                save_leads(leads, leads_filepath)
                continue

            print(f"\n[{idx}/{len(target_leads)}] Sending to {lead['business_name']} ({mask_email(lead['email'])})...")
            try:
                final_msgid, _ = send_smtp_email(
                    lead["email"],
                    subject,
                    body,
                    lead=lead,
                    email_type=email_type,
                    check_urls_live=True,
                    in_reply_to=in_reply_to if followup_mode and in_reply_to != "<placeholder-initial-msgid@sheetboltanalytics.netlify.app>" else None,
                    references=references if followup_mode else None,
                )
                now_iso = get_ist_now().isoformat()
                lead["status"] = "contacted_2" if followup_mode else "contacted_1"
                lead["last_contacted"] = now_iso

                append_outreach_log({
                    "timestamp": now_iso,
                    "recipient_email": lead["email"],
                    "business_name": lead["business_name"],
                    "segment": lead["segment"],
                    "email_type": email_type,
                    "subject": subject,
                    "status": "sent",
                    "error_message": "",
                    "message_id": final_msgid,
                    "original_subject": subject if not followup_mode else orig_subj,
                    "probe_path": probe_path,
                }, filepath=log_filepath)
                save_leads(leads, leads_filepath)
                print(f"    [SENT OK] Marked status as '{lead['status']}'.")

                if idx < len(target_leads):
                    delay = random.randint(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
                    print(f"    [POLITE DELAY] Waiting {delay}s before next send...")
                    time.sleep(delay)

            except Exception as e:
                err_str = str(e)
                print(f"    [SEND ERROR] {err_str}")
                is_auth_error = (
                    isinstance(e, smtplib.SMTPAuthenticationError)
                    or getattr(e, "smtp_code", None) in [534, 535]
                    or any(k in err_str.lower() for k in [
                        "534", "535", "webloginrequired", "invalid credentials",
                        "authentication failed", "login challenge", "username and password not accepted"
                    ])
                )
                is_bounce = (not is_auth_error) and (bool(re.search(r"\b550\b", err_str)) or "recipient rejected" in err_str.lower())
                status_val = "bounced" if is_bounce else "failed"

                if is_bounce:
                    lead["status"] = "bounced"
                    save_leads(leads, leads_filepath)

                append_outreach_log({
                    "timestamp": get_ist_now().isoformat(),
                    "recipient_email": lead["email"],
                    "business_name": lead["business_name"],
                    "segment": lead["segment"],
                    "email_type": email_type,
                    "subject": subject,
                    "status": status_val,
                    "error_message": err_str,
                    "message_id": "",
                    "original_subject": subject if not followup_mode else orig_subj,
                    "probe_path": probe_path,
                }, filepath=log_filepath)

                if is_auth_error:
                    print(f"\n[CRITICAL AUTH FAILURE] SMTP Authentication / Login Challenge detected ({err_str}). Aborting entire outreach run immediately.")
                    break

                tripped, _, _, _, reason = check_circuit_breaker(log_filepath=log_filepath, state_file=state_file, enabled_files=enabled_files)
                if tripped:
                    print(f"\n[!] Circuit breaker triggered after bounce ({reason}). Aborting batch.")
                    break
        else:
            # Dry-run mode: do not write to outreach_log.csv or leads file
            pass

    display_count = min(len(preview_outputs), limit or 6)
    print(f"\n--- SHOWING FIRST {display_count} EMAILS FOR REVIEW & APPROVAL ---")
    user = os.environ.get("SMTP_USER", "")
    sender_name = os.environ.get("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
    from_line = f"{sender_name} <{user}>"
    sample_url = os.environ.get("SAMPLE_DASHBOARD_URL", "")
    sig_text = get_signature_and_footer()

    for i in range(display_count):
        ld, sbj, bdy, txt_p, html_p, img_list, loc_info, seg_info, in_rep = preview_outputs[i]
        matched_str = f"({', '.join(seg_info)} found)" if seg_info else "(confirmed from tags)"
        body_only = bdy.split("Best,\n")[0].strip() if "Best,\n" in bdy else bdy
        body_limit_str = "< 70 words (including greeting)" if followup_mode else "< 90 words (signature excluded)"
        print(f"\n==================== [EMAIL PREVIEW #{i+1}] ====================")
        print(f"FROM:           {from_line}")
        print(f"TO:             {mask_email(ld['email'])}")
        print(f"BUSINESS:       {ld['business_name']} ({ld['segment']})")
        print(f"GREETING:       {get_greeting(ld['business_name'])}")
        print(f"LOCATION CHECK: [PASS] {loc_info}")
        print(f"SEGMENT CHECK:  [PASS] Confirmed {ld['segment']} {matched_str}")
        if followup_mode:
            qual_reason = ld.get("_followup_qualification", "")
            print(f"QUALIFICATION:  [PASS] {qual_reason}")
        print(f"SUBJECT:        {sbj}")
        if followup_mode:
            print(f"IN-REPLY-TO:    {in_rep or '<placeholder-initial-msgid@sheetboltanalytics.netlify.app>'}")
        print(f"BODY WORDS:     {count_words(body_only)} words (max {body_limit_str})")
        if not followup_mode:
            print(f"SAMPLE LINK:    {sample_url}")
        print(f"INCLUDED IMAGES: {', '.join(img_list) if img_list else 'None'}")
        print(f"TEXT DRAFT:     {txt_p}")
        print(f"HTML PREVIEW:   {html_p}")
        print("-------------------- [PLAIN-TEXT BODY] --------------------")
        print(bdy)
        print("-------------------- [SIGNATURE & FOOTER] --------------------")
        print(sig_text)
        print("========================================================\n")

    if not send_live:
        print(f"[DRY RUN COMPLETE] {len(preview_outputs)} drafts generated in '{PREVIEW_DIR}/'.")
        print("Zero emails were sent. To send live emails, use the --send flag during the sending window.")

# ----------------- STEP 5: STATE MANAGEMENT & REPORTING -----------------

def mark_lead_state(email, new_status, reason="", log_filepath=None, lead_files=None):
    if new_status not in ["replied", "unsubscribed", "bounced", "rejected_location", "review_flagged", "unclassified_hold", "new"]:
        raise ValueError(f"Invalid status: {new_status}")

    clean = normalize_email(email)
    if lead_files is None:
        import glob
        lead_files = set(glob.glob("leads*.csv"))
        if LEADS_CSV:
            lead_files.add(LEADS_CSV)
    found_any = False
    biz_name = ""
    biz_segment = ""

    for l_file in lead_files:
        try:
            leads = load_leads(l_file)
            file_updated = False
            for lead in leads:
                if normalize_email(lead.get("email", "")) == clean:
                    lead["status"] = new_status
                    file_updated = True
                    found_any = True
                    biz_name = biz_name or lead.get("business_name", "")
                    biz_segment = biz_segment or lead.get("segment", "")
            if file_updated:
                save_leads(leads, l_file)
        except Exception:
            pass

    append_outreach_log({
        "timestamp": get_ist_now().isoformat(),
        "recipient_email": clean,
        "business_name": biz_name,
        "segment": biz_segment,
        "email_type": "status_update",
        "subject": f"Marked as {new_status}",
        "status": new_status,
        "error_message": reason,
    }, filepath=log_filepath)
    if found_any:
        print(f"[STATUS UPDATED] Lead '{mask_email(clean)}' is now marked as '{new_status}' across lead lists.")
    else:
        print(f"[STATUS UPDATED] Recorded '{new_status}' for '{mask_email(clean)}' in outreach_log.csv (not present in leads CSV).")

def extract_ndr_diagnostic(body):
    """Extract NDR diagnostic code/reason from bounce notification text."""
    resp_match = re.search(r"The response was:\s*(?:<[^>]+>)*\s*([^\n<]+)", body or "", re.I)
    if resp_match:
        return resp_match.group(1).strip()
    for line in (body or "").splitlines():
        line_s = line.strip()
        if any(k in line_s.lower() for k in ["dns error", "status code: 550", "status: 550", "status code:", "status:", "diagnostic-code", "user unknown", "does not exist", "recipient not found", "undeliverable"]):
            return line_s
    return "Automated delivery failure / bounce notification"

def classify_bounce_cause(diag_text, body=""):
    """Classify bounce cause into invalid mailbox, domain/DNS, provider rejection, or other."""
    combined = (str(diag_text) + " " + str(body)).lower()
    if any(k in combined for k in ["does not exist", "user unknown", "no such user", "nosuchuser", "address not found", "recipient not found", "invalid recipient"]):
        return "invalid mailbox"
    elif any(k in combined for k in ["domain not found", "no mx", "dns error", "dns type", "name or service not known", "unrouteable address"]):
        return "domain/DNS"
    elif any(k in combined for k in ["status code: 550", "status: 550", "rejected", "blocked", "spam", "blacklisted", "policy", "relay access denied", "dmarc", "spf"]):
        return "provider rejection"
    return "other"

def classify_inbound_message(subject, body, from_addr, headers=None):
    """
    Deterministic rule-based classification of inbound emails.
    Categories:
    - bounce_notice: Delivery failures, mailer-daemon, NDRs
    - auto_reply: Out of office, automatic vacation responders
    - unsubscribe: Stop, opt-out, do not contact, not interested
    - pricing: Questions about pricing, rates, fees, cost
    - wants_info: Requests for information, portfolio, case studies, details
    - interested: Clear interest, call requests, meeting requests
    - wrong_contact: Wrong person, not in charge, someone else handles this
    - needs_review: Other genuine inbound messages
    """
    subj_lower = (subject or "").lower()
    body_lower = (body or "").lower()
    from_lower = (from_addr or "").lower()
    combined = f"{subj_lower} {body_lower}"

    # 1. Auto-reply / Out of office (checked first to prevent misclassifying OOO as bounce)
    auto_subj_patterns = [
        "out of office", "auto-reply", "autoreply", "automatic reply",
        "away from office", "vacation response", "on leave", "out of the office",
        "i am currently away", "i will be out of", "away from my desk"
    ]
    auto_body_patterns = [
        "out of the office", "out of office", "away from the office", "away from office",
        "i am away", "on annual leave", "on parental leave", "on sick leave",
        "i will be out of", "i am currently out", "back in the office"
    ]
    is_auto = False
    auto_reason = ""
    if headers:
        auto_sub = headers.get("Auto-Submitted", "").lower() if hasattr(headers, "get") else ""
        if auto_sub in ["auto-replied", "vacation"] or (auto_sub and auto_sub != "no" and "auto" in auto_sub):
            is_auto = True
            auto_reason = f"Auto-submitted header ({auto_sub})"
        elif headers.get("X-Autoreply", "") if hasattr(headers, "get") else False:
            is_auto = True
            auto_reason = "X-Autoreply header present"

    if not is_auto:
        if any(p in subj_lower for p in auto_subj_patterns):
            is_auto = True
            auto_reason = "Out of office / automatic responder subject"
        elif any(p in body_lower for p in auto_body_patterns):
            is_auto = True
            auto_reason = "Out of office / automatic responder body"

    if is_auto:
        return "auto_reply", auto_reason or "Out of office / automatic responder"

    # 2. Bounce / NDR Notice
    bounce_senders = ["mailer-daemon@", "postmaster@", "mail-delivery-system"]
    bounce_subj_patterns = [
        "delivery status notification", "failure notice", "undeliverable",
        "returned mail", "mail delivery failed", "address not found",
        "message could not be delivered", "delivery failure"
    ]
    if any(s in from_lower for s in bounce_senders) or any(p in subj_lower for p in bounce_subj_patterns):
        diag = extract_ndr_diagnostic(body)
        cause = classify_bounce_cause(diag, body)

        # Strict DSN markers for delay:
        # Match only on: Delivery Status Notification (Delay), Status: 4.x.x, "will keep trying", "temporary failure"
        # Bare "delay" or "delayed" keywords removed to eliminate false positives
        is_delay = (
            "delivery status notification (delay)" in subj_lower
            or "delivery status notification (delay)" in body_lower
            or bool(re.search(r"\bstatus:\s*4\.\d+\.\d+\b", body_lower))
            or "will keep trying" in body_lower
            or "temporary failure" in body_lower
        )
        if is_delay:
            return "delivery_delay", f"[{cause}] {diag} (transient delay; flag for recheck after 72h)"
        else:
            return "bounce_permanent", f"[{cause}] {diag}"

    # 3. Unsubscribe / Opt-out / Not Interested (Suppression)
    unsub_phrases = [
        "unsubscribe", "remove me", "stop", "opt out", "opt-out",
        "do not email", "don't email", "take me off", "delete my email",
        "not interested", "no thanks", "no, thanks", "not interested at this time",
        "please do not contact", "not looking for", "leave me alone",
        "please remove our email", "don't contact", "dont contact"
    ]
    clean_words = set(re.findall(r"\b[a-z']+\b", combined))
    if "stop" in clean_words or "unsubscribe" in clean_words:
        return "unsubscribe", "Explicit unsubscribe/stop keyword"
    for phrase in unsub_phrases:
        if phrase in combined:
            return "unsubscribe", f"Opt-out match: '{phrase}'"

    # 4. Wrong contact
    wrong_contact_phrases = [
        "wrong person", "wrong contact", "not the right person",
        "no longer work", "left the company", "not with the company",
        "reach out to", "contact someone else", "speak with someone else"
    ]
    for phrase in wrong_contact_phrases:
        if phrase in combined:
            return "wrong_contact", f"Wrong contact referral: '{phrase}'"

    # 5. Pricing requests
    pricing_phrases = [
        "how much", "what is the cost", "pricing", "what are your rates",
        "quote", "charge", "fee structure", "how much do you charge",
        "cost for", "budget", "commercials"
    ]
    for phrase in pricing_phrases:
        if phrase in combined:
            return "pricing", f"Pricing inquiry: '{phrase}'"

    # 6. Information requests
    info_phrases = [
        "more details", "send more info", "tell me more", "what do you offer",
        "how does it work", "sample", "share examples", "portfolio",
        "case study", "deck", "can you share", "send across"
    ]
    for phrase in info_phrases:
        if phrase in combined:
            return "wants_info", f"Info inquiry: '{phrase}'"

    # 7. Interested / Meeting request
    interested_phrases = [
        "let's talk", "let's connect", "lets talk", "lets connect",
        "schedule a call", "set up a call", "book a demo", "free for a call",
        "sounds good", "interested", "call me", "reach me at", "available on",
        "lets meet", "let's meet", "share your calendar", "calendar link", "yes"
    ]
    for phrase in interested_phrases:
        if phrase in combined:
            return "interested", f"Expressed interest: '{phrase}'"

    # 8. Fallback for any other prospect reply
    return "needs_review", "Inbound prospect reply (needs manual review)"

def sync_inbox(log_filepath=OUTREACH_LOG_CSV, max_messages=50, imap_conn=None, leads_filepath=None, lead_files=None, dry_run=False):
    """
    Read IMAP inbox, Spam, and All Mail folders (read-only), match messages to leads via
    In-Reply-To/References or sender matching, classify responses deterministically,
    and update state idempotently.
    In dry-run mode, classifies and prints but writes nothing.
    """
    print("\n" + "=" * 70)
    print(f"📥 SHEETBOLT INBOX & UNSUBSCRIBE SYNC (IMAP) {'[DRY-RUN]' if dry_run else ''}")
    print("=" * 70)
    if dry_run:
        print("[DRY-RUN] Simulation mode active. No lead status or log files will be modified.\n")

    # 1. Build lookup tables
    log_entries = load_outreach_log(log_filepath)
    msg_id_to_lead = {}
    contacted_emails = {}
    for e in log_entries:
        mid = (e.get("message_id") or "").strip()
        em = normalize_email(e.get("recipient_email", ""))
        if mid and mid != "dry_run":
            msg_id_to_lead[mid] = e
        if em and e.get("status") == "sent":
            contacted_emails[em] = e

    # Build map of existing leads across all lead files
    all_leads = {}
    if lead_files is not None:
        target_lead_files = set(lead_files)
    else:
        import glob
        target_lead_files = set(glob.glob("leads*.csv"))
        if LEADS_CSV:
            target_lead_files.add(LEADS_CSV)
    for fpath in target_lead_files:
        try:
            for l in load_leads(fpath):
                lem = normalize_email(l.get("email", ""))
                if lem:
                    all_leads[lem] = l
        except Exception:
            pass

    # 2. Connect to IMAP
    mail = imap_conn
    need_logout = False
    if mail is None:
        user = os.environ.get("SMTP_USER", "")
        password = os.environ.get("SMTP_PASS", "")
        if not user or not password:
            print("[ERROR] SMTP_USER or SMTP_PASS not set in environment. Cannot sync IMAP inbox.")
            return {"error": "Missing credentials"}
        try:
            mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=15)
            mail.login(user, password)
            need_logout = True
        except Exception as e:
            print(f"[ERROR] Failed to connect/login to IMAP ({IMAP_HOST}:{IMAP_PORT}): {e}")
            return {"error": str(e)}

    results = {
        "total_messages": 0,
        "matched_messages": 0,
        "unsubscribes": 0,
        "bounces": 0,
        "auto_replies": 0,
        "interested": 0,
        "wants_info": 0,
        "pricing": 0,
        "wrong_contact": 0,
        "needs_review": 0,
        "skipped_already_synced": 0,
        "items": []
    }

    folders_to_search = [
        ("INBOX", ["INBOX"]),
        ("Spam", ["[Gmail]/Spam", "Spam", "Junk"]),
        ("All Mail", ["[Gmail]/All Mail", "All Mail"]),
    ]

    seen_msg_ids = set()
    already_synced_mids = set()
    for e in log_entries:
        if (e.get("email_type") or "").startswith("inbox_sync"):
            smid = (e.get("message_id") or "").strip()
            if smid:
                already_synced_mids.add(smid)

    try:
        for folder_label, candidate_names in folders_to_search:
            selected_name = None
            for cand in candidate_names:
                try:
                    status, _ = mail.select(cand, readonly=True)
                    if status == "OK":
                        selected_name = cand
                        break
                except Exception:
                    continue

            if not selected_name:
                continue

            status, data = mail.search(None, "ALL")
            if status != "OK" or not data or not data[0]:
                continue

            msg_nums = data[0].split()
            results["total_messages"] += len(msg_nums)
            folder_nums = msg_nums[-max_messages:]

            for num in folder_nums:
                res, mdata = mail.fetch(num, "(RFC822)")
                if res != "OK" or not mdata or not mdata[0]:
                    continue

                raw_email = mdata[0][1]
                msg = email.message_from_bytes(raw_email)

                msg_id = (msg.get("Message-ID") or "").strip()
                if msg_id and msg_id in seen_msg_ids:
                    continue
                if msg_id:
                    seen_msg_ids.add(msg_id)

                in_reply_to = (msg.get("In-Reply-To") or "").strip()
                references = (msg.get("References") or "").strip()
                from_hdr = msg.get("From", "")
                _, from_email = parseaddr(from_hdr)
                clean_from = normalize_email(from_email)
                subject = msg.get("Subject", "")
                date_hdr = msg.get("Date", "")

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ctype = part.get_content_type()
                        cdispo = str(part.get("Content-Disposition"))
                        if ctype == "text/plain" and "attachment" not in cdispo:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body += payload.decode("utf-8", errors="ignore")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="ignore")

                matched_lead = None
                matched_email = ""

                refs_to_check = [in_reply_to] + references.split()
                for ref in refs_to_check:
                    clean_ref = ref.strip()
                    if clean_ref and clean_ref in msg_id_to_lead:
                        matched_log = msg_id_to_lead[clean_ref]
                        matched_email = normalize_email(matched_log.get("recipient_email", ""))
                        matched_lead = all_leads.get(matched_email)
                        break

                if not matched_email and clean_from in contacted_emails:
                    matched_email = clean_from
                    matched_lead = all_leads.get(matched_email)

                if not matched_email and clean_from in all_leads:
                    matched_email = clean_from
                    matched_lead = all_leads.get(matched_email)

                is_bounce_sender = any(x in clean_from for x in ["mailer-daemon", "postmaster"])
                if not matched_email and is_bounce_sender:
                    for candidate_em in contacted_emails:
                        if candidate_em in body.lower():
                            matched_email = candidate_em
                            matched_lead = all_leads.get(matched_email)
                            break

                if not matched_email:
                    continue

                results["matched_messages"] += 1

                if msg_id and msg_id in already_synced_mids:
                    results["skipped_already_synced"] += 1
                    continue

                category, cat_reason = classify_inbound_message(subject, body, clean_from, headers=msg)
                biz_name = (matched_lead.get("business_name") if matched_lead else "") or (contacted_emails.get(matched_email, {}).get("business_name", ""))

                action_taken = ""
                if category == "unsubscribe":
                    if not dry_run:
                        mark_lead_state(matched_email, "unsubscribed", reason=cat_reason, log_filepath=log_filepath, lead_files=lead_files)
                    results["unsubscribes"] += 1
                    action_taken = "Suppressed (unsubscribed across all lead lists)" if not dry_run else "[DRY-RUN] Would suppress (unsubscribe across all lead lists)"
                elif category in ["bounce_notice", "bounce_permanent"]:
                    if not dry_run:
                        mark_lead_state(matched_email, "bounced", reason=cat_reason, log_filepath=log_filepath, lead_files=lead_files)
                    results["bounces"] += 1
                    action_taken = "Marked bounced (follow-ups cancelled)" if not dry_run else "[DRY-RUN] Would mark bounced (cancel follow-ups)"
                elif category == "delivery_delay":
                    results["delivery_delays"] = results.get("delivery_delays", 0) + 1
                    action_taken = "Delivery delay (transient warning; no suppression; flag for recheck after 72h)"
                elif category == "auto_reply":
                    results["auto_replies"] += 1
                    action_taken = "Ignored (auto-responder / OOO - not a genuine reply)"
                else:
                    if not dry_run:
                        mark_lead_state(matched_email, "replied", reason=f"{category}: {cat_reason}", log_filepath=log_filepath, lead_files=lead_files)
                    results[category] = results.get(category, 0) + 1
                    action_taken = f"Marked replied ({category}) - manual review needed" if not dry_run else f"[DRY-RUN] Would mark replied ({category}) - manual review needed"

                if not dry_run:
                    status_val = (
                        "unsubscribed" if category == "unsubscribe"
                        else ("bounced" if category in ["bounce_notice", "bounce_permanent"]
                        else ("delivery_delay" if category == "delivery_delay"
                        else ("auto_reply" if category == "auto_reply"
                        else "replied")))
                    )
                    append_outreach_log({
                        "timestamp": get_ist_now().isoformat(),
                        "recipient_email": matched_email,
                        "business_name": biz_name,
                        "segment": (matched_lead.get("segment") if matched_lead else "") or (contacted_emails.get(matched_email, {}).get("segment", "")),
                        "email_type": f"inbox_sync:{category}",
                        "subject": subject[:80],
                        "status": status_val,
                        "error_message": cat_reason,
                        "message_id": msg_id,
                        "original_subject": subject[:80],
                    }, filepath=log_filepath)
                    if msg_id:
                        already_synced_mids.add(msg_id)

                results["items"].append({
                    "email": mask_email(matched_email),
                    "business_name": biz_name,
                    "category": category,
                    "reason": cat_reason,
                    "action": action_taken,
                    "subject": subject,
                    "date": date_hdr,
                    "folder": folder_label,
                })

    finally:
        if need_logout:
            try:
                mail.logout()
            except Exception:
                pass

    print(f"\nSynced {results['matched_messages']} prospect message(s) across folders:")
    print(f"  - Genuine replies: {results['interested'] + results['wants_info'] + results['pricing'] + results['wrong_contact'] + results['needs_review']}")
    print(f"  - Unsubscribes processed: {results['unsubscribes']}")
    print(f"  - Delivery bounces detected: {results['bounces']}")
    print(f"  - Auto-replies ignored: {results['auto_replies']}")
    print(f"  - Already synced (idempotent skips): {results['skipped_already_synced']}")

    if results["items"]:
        print("\n" + "-" * 75)
        print(f"{'Prospect':<20} {'Category':<15} {'Action Taken'}")
        print("-" * 75)
        for item in results["items"]:
            print(f"{item['email']:<20} {item['category']:<15} {item['action']}")
        print("-" * 75)

    return results

def generate_report(log_filepath=OUTREACH_LOG_CSV, lead_files=None):
    """
    Generate outreach performance report based strictly on UNIQUE PROSPECTS (never row counts).
    Reports counts and rates by status (sent, bounced, followed up, replied, suppressed)
    per source file and globally across all sources, with exact denominators.
    """
    if lead_files is None:
        lead_files = [LEADS_CSV, "leads_abroad_agencies.csv", "leads_austin.csv"]
    # Filter to existing files
    active_files = [f for f in lead_files if os.path.exists(f)]

    entries = load_outreach_log(log_filepath)

    # 1. Map log activity by unique prospect email
    log_initial_sent = set()
    log_followup_sent = set()
    log_bounced = set()
    log_replied = set()
    log_unsubscribed = set()

    for e in entries:
        em = normalize_email(e.get("recipient_email", ""))
        if not em:
            continue
        etype = (e.get("email_type") or "").lower()
        st = (e.get("status") or "").lower()

        if etype == "initial" and st in ["sent", "contacted_1", "bounced"]:
            log_initial_sent.add(em)
        elif etype == "followup" and st in ["sent", "contacted_2"]:
            log_followup_sent.add(em)

        if st == "bounced":
            log_bounced.add(em)
        elif st in ["replied", "interested", "wants_info", "pricing", "wrong_contact"]:
            log_replied.add(em)
        elif st == "unsubscribed":
            log_unsubscribed.add(em)

    today = get_ist_now().date()
    print("\n" + "=" * 78)
    print("📊 SHEETBOLT OUTREACH REPORT (UNIQUE PROSPECTS BREAKDOWN)")
    print("=" * 78)

    window_ok, window_reason = is_in_sending_window()
    print(f"Sending Window:  {'[OPEN]' if window_ok else '[CLOSED]'} ({window_reason})")
    cap, week, desc = get_warmup_cap(log_filepath=log_filepath, target_date=today)
    today_sent = get_daily_sent_count(log_filepath=log_filepath, target_date=today)
    print(f"Daily Volume:    {today_sent}/{cap} emails sent today ({desc})")
    print(f"Daily Cap Guard: {HARD_DAILY_CAP_LIMIT}/day max ceiling")

    tripped, rate, bounce_cnt, sent_cnt, reason = check_circuit_breaker(log_filepath=log_filepath)
    cb_status = "[TRIGGERED - BLOCKED]" if tripped else "[HEALTHY]"
    print(f"Circuit Breaker: {cb_status} ({bounce_cnt}/{sent_cnt} bounces, rate {rate:.1%})")
    print("-" * 78)

    report_data = {
        "files": {},
        "global": {}
    }

    global_prospects = set()
    global_initial_sent = set()
    global_bounced = set()
    global_followup = set()
    global_replied = set()
    global_suppressed = set()

    print("\n--- BREAKDOWN BY SOURCE FILE (UNIQUE PROSPECTS) ---")
    for fpath in active_files:
        leads = load_leads(fpath)
        file_prospects = {normalize_email(l.get("email", "")) for l in leads if l.get("email")}
        total_p = len(file_prospects)
        if total_p == 0:
            continue

        file_bounced_leads = {normalize_email(l.get("email", "")) for l in leads if l.get("status") == "bounced"}
        file_unsub_leads = {normalize_email(l.get("email", "")) for l in leads if l.get("status") == "unsubscribed"}
        file_replied_leads = {normalize_email(l.get("email", "")) for l in leads if l.get("status") == "replied"}

        sent_p = file_prospects.intersection(log_initial_sent)
        bounced_p = file_prospects.intersection(log_bounced.union(file_bounced_leads))
        fu_p = file_prospects.intersection(log_followup_sent)
        replied_p = file_prospects.intersection(log_replied.union(file_replied_leads))
        suppressed_p = file_prospects.intersection(log_unsubscribed.union(file_unsub_leads).union(bounced_p))

        s_count = len(sent_p)
        b_count = len(bounced_p)
        fu_count = len(fu_p)
        r_count = len(replied_p)
        sup_count = len(suppressed_p)

        global_prospects.update(file_prospects)
        global_initial_sent.update(sent_p)
        global_bounced.update(bounced_p)
        global_followup.update(fu_p)
        global_replied.update(replied_p)
        global_suppressed.update(suppressed_p)

        sent_rate = (s_count / total_p * 100) if total_p else 0
        bounce_rate = (b_count / s_count * 100) if s_count else 0
        fu_rate = (fu_count / s_count * 100) if s_count else 0
        reply_rate = (r_count / s_count * 100) if s_count else 0
        sup_rate = (sup_count / total_p * 100) if total_p else 0

        fname = os.path.basename(fpath)
        print(f"\n📁 File: {fname} ({total_p} unique prospects)")
        print(f"   • Initial Sent:  {s_count:>3} / {total_p:<3} ({sent_rate:>5.1f}%)")
        print(f"   • Bounced:       {b_count:>3} / {s_count:<3} ({bounce_rate:>5.1f}% of sent) [{b_count}/{total_p} total]")
        print(f"   • Followed Up:   {fu_count:>3} / {s_count:<3} ({fu_rate:>5.1f}% of sent)")
        print(f"   • Replied:       {r_count:>3} / {s_count:<3} ({reply_rate:>5.1f}% of sent)")
        print(f"   • Suppressed:    {sup_count:>3} / {total_p:<3} ({sup_rate:>5.1f}% of pool)")

        report_data["files"][fname] = {
            "total_prospects": total_p,
            "initial_sent": s_count,
            "bounced": b_count,
            "followed_up": fu_count,
            "replied": r_count,
            "suppressed": sup_count,
        }

    # Global summary
    tot_global = len(global_prospects)
    g_sent = len(global_initial_sent)
    g_bounce = len(global_bounced)
    g_fu = len(global_followup)
    g_reply = len(global_replied)
    g_sup = len(global_suppressed)

    g_sent_rate = (g_sent / tot_global * 100) if tot_global else 0
    g_bounce_rate = (g_bounce / g_sent * 100) if g_sent else 0
    g_fu_rate = (g_fu / g_sent * 100) if g_sent else 0
    g_reply_rate = (g_reply / g_sent * 100) if g_sent else 0
    g_sup_rate = (g_sup / tot_global * 100) if tot_global else 0

    print("\n" + "=" * 78)
    print(f"🌐 GLOBAL UNIQUE PROSPECT RECONCILIATION ({tot_global} total prospects across sources)")
    print("=" * 78)
    print(f"  • Unique Prospects Contacted (Initial): {g_sent:>3} / {tot_global:<3} ({g_sent_rate:>5.1f}%)")
    print(f"  • Unique Prospects Bounced:              {g_bounce:>3} / {g_sent:<3} ({g_bounce_rate:>5.1f}% of sent) [{g_bounce}/{tot_global} total]")
    print(f"  • Unique Prospects Followed Up:          {g_fu:>3} / {g_sent:<3} ({g_fu_rate:>5.1f}% of sent)")
    print(f"  • Unique Prospects Replied:              {g_reply:>3} / {g_sent:<3} ({g_reply_rate:>5.1f}% of sent)")
    print(f"  • Unique Prospects Suppressed:           {g_sup:>3} / {tot_global:<3} ({g_sup_rate:>5.1f}% of pool)")
    print("=" * 78 + "\n")

    report_data["global"] = {
        "total_prospects": tot_global,
        "initial_sent": g_sent,
        "bounced": g_bounce,
        "followed_up": g_fu,
        "replied": g_reply,
        "suppressed": g_sup,
    }

    return report_data

def recheck_delivery_delays(log_filepath=OUTREACH_LOG_CSV, max_age_hours=72.0, lead_files=None):
    """
    Read-only audit listing delivery delay notices older than 72h with no subsequent final result.
    Does not send emails, change lead statuses, or contact prospects.
    Returns list of unresolved delay records.
    """
    if not os.path.exists(log_filepath):
        print(f"[RECHECK DELAYS] Log file '{log_filepath}' not found.")
        return []

    entries = load_outreach_log(log_filepath)
    now_ist = get_ist_now()

    # Track all events per recipient to detect final resolution after the delay
    prospect_events = {}
    delays = []

    for entry in entries:
        em = normalize_email(entry.get("recipient_email", ""))
        if not em:
            continue
        ts_str = entry.get("timestamp", "")
        dt = None
        if ts_str:
            try:
                clean_ts = ts_str.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean_ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=IST)
            except Exception:
                dt = None

        if dt:
            if em not in prospect_events:
                prospect_events[em] = []
            prospect_events[em].append((dt, entry.get("status", ""), entry.get("email_type", "")))

            st = entry.get("status", "")
            etype = entry.get("email_type", "")
            if st == "delivery_delay" or etype == "inbox_sync:delivery_delay":
                delays.append((dt, em, entry))

    unresolved_delays = []
    for delay_dt, em, delay_entry in delays:
        age_hours = (now_ist - delay_dt).total_seconds() / 3600.0
        if age_hours < max_age_hours:
            continue  # Delay is more recent than 72h window

        # Check for events happening AFTER this delay notice
        events_after = [
            (e_dt, e_st, e_type) for (e_dt, e_st, e_type) in prospect_events.get(em, [])
            if e_dt > delay_dt
        ]
        has_resolution = any(
            e_st in ["bounced", "replied", "interested", "wants_info", "pricing", "unsubscribed"]
            or (e_st in ["sent", "contacted_1", "contacted_2"] and "inbox_sync" not in e_type)
            for (e_dt, e_st, e_type) in events_after
        )

        if not has_resolution:
            unresolved_delays.append({
                "recipient_email": em,
                "business_name": delay_entry.get("business_name", ""),
                "timestamp": delay_entry.get("timestamp", ""),
                "age_hours": round(age_hours, 1),
                "error_message": delay_entry.get("error_message", ""),
                "subject": delay_entry.get("subject", ""),
            })

    print("\n" + "=" * 78)
    print(f"⏱️  DELIVERY DELAY AUDIT (> {int(max_age_hours)}h without final resolution)")
    print("=" * 78)
    if not unresolved_delays:
        print(f"No unresolved delivery delays older than {int(max_age_hours)}h found in log.")
    else:
        print(f"Found {len(unresolved_delays)} delay notice(s) older than {int(max_age_hours)}h requiring operator attention:")
        for idx, item in enumerate(unresolved_delays, 1):
            print(f"  {idx}. {item['business_name']} ({mask_email(item['recipient_email'])})")
            print(f"     Notice Timestamp: {item['timestamp']} ({item['age_hours']}h ago)")
            print(f"     Diagnostic:       {item['error_message'][:70]}")
    print("=" * 78 + "\n")

    return unresolved_delays

def run_preview_only():
    """Renders and displays a clean preview for all 7 business segments without sending any emails."""
    leads = load_leads()
    by_seg = {}
    for l in leads:
        st = l.get("status")
        sg = l.get("segment")
        if st not in ["unsubscribed", "replied", "bounced", "rejected_location", "review_flagged"] and sg in SEGMENTS:
            if sg not in by_seg:
                by_seg[sg] = l

    print("\n" + "=" * 76)
    print("📢 OUTREACH PIPELINE — ALL 7 SEGMENTS RENDER PREVIEW (ZERO SENDS)")
    print("=" * 76)
    print("Targeting: Bengaluru Businesses | CTA: Zero-Link Conversational | Max Words: < 90")
    print("=" * 76 + "\n")

    summary_rows = []

    for idx, seg in enumerate(SEGMENTS, 1):
        lead = by_seg.get(seg)
        if not lead:
            lead = {
                "business_name": f"Sample {seg.title()} Studio",
                "segment": seg,
                "website": f"https://sample-{seg}.in",
                "email": f"contact@sample-{seg}.in",
                "website_detail": ""
            }

        subj, body = generate_email(lead, email_type="initial")
        subj_words = count_words(subj)
        body_only = body.split("Best,\n")[0].strip() if "Best,\n" in body else body
        body_words = count_words(body_only)
        user = os.environ.get("SMTP_USER", "")
        sender_name = os.environ.get("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")
        from_line = f"{sender_name} <{user}>"
        sample_url = os.environ.get("SAMPLE_DASHBOARD_URL", "")

        summary_rows.append({
            "segment": seg,
            "business": lead.get("business_name", ""),
            "subj_words": subj_words,
            "body_words": body_words,
        })

        print(f"==================== [SEGMENT {idx}/7: {seg.upper()}] ====================")
        print(f"FROM:            {from_line}")
        print(f"TARGET BUSINESS: {lead.get('business_name')} ({lead.get('email')})")
        print(f"SUBJECT LINE:    {subj} ({subj_words} words - limit < 8)")
        print(f"WORD COUNT:      {body_words} words (limit < 90, signature excluded)")
        print(f"SAMPLE LINK:     {sample_url}")
        print("-" * 76)
        print(body)
        print("=" * 76 + "\n")

    print("=" * 76)
    print("📊 7-SEGMENT COMPLIANCE & TONE SUMMARY")
    print("=" * 76)
    print(f"{'Segment':<15} {'Business Preview':<25} {'Subj':<6} {'Words':<8} {'Status'}")
    print("-" * 76)
    for r in summary_rows:
        ok = r["body_words"] < 90 and r["subj_words"] < 8
        status_str = "✅ PASS" if ok else "❌ FAIL"
        print(f"{r['segment']:<15} {r['business'][:23]:<25} {r['subj_words']:<6} {r['body_words']:<8} {status_str}")
    print("=" * 76 + "\n")

# ----------------- CLI INTERFACE -----------------

def main():
    parser = argparse.ArgumentParser(description="Freelance Data Service Outreach Pipeline for Bengaluru.")
    parser.add_argument("command", nargs="?", default="", help="Subcommand, e.g. 'sync-inbox'.")
    parser.add_argument("--sync-inbox", action="store_true", help="Sync IMAP inbox and unsubscribe requests.")
    parser.add_argument("--find-leads", action="store_true", help="Scrape new business leads in Bengaluru.")
    parser.add_argument("--segment", type=str, choices=SEGMENTS, default="clinics", help="Target business segment.")
    parser.add_argument("--area", type=str, default="Indiranagar", help="Area or neighborhood in Bengaluru.")
    parser.add_argument("--limit", type=int, default=10, help="Max leads to process/source.")
    parser.add_argument("--leads-file", type=str, default="leads.csv", help="Path to leads CSV file (default: leads.csv).")
    parser.add_argument("--dry-run", action="store_true", help="Run in simulation mode without sending emails or modifying files.")
    parser.add_argument("--preview-only", "--dry-render", action="store_true", help="Render and display all 7 segment emails without sending.")
    parser.add_argument("--send", action="store_true", help="Send emails live via Gmail SMTP.")
    parser.add_argument("--test-send", action="store_true", help="Send first draft strictly to TEST_RECIPIENTS.")
    parser.add_argument("--test-followup", action="store_true", help="Send follow-up as a threaded reply strictly to TEST_RECIPIENTS.")
    parser.add_argument("--followup", action="store_true", help="Process follow-up emails (4 business days after email 1).")
    parser.add_argument("--force-window", action="store_true", help="Override sending window restrictions for testing.")
    parser.add_argument("--no-warmup", action="store_true", help="Disable warmup daily cap (forces 25/day cap).")
    parser.add_argument("--audit-locations", action="store_true", help="Audit all leads in leads.csv against ALLOWED_CITIES.")
    parser.add_argument("--audit-domains", action="store_true", help="Audit all leads for domain matching and flag review.")
    parser.add_argument("--audit-mailboxes", action="store_true", help="Audit all leads via DNS MX and live SMTP handshake.")
    parser.add_argument("--list-flagged", action="store_true", help="Print all review_flagged leads with reasons.")
    parser.add_argument("--check-imap", action="store_true", help="Display IMAP settings and test connection for Gmail threading fallback.")
    parser.add_argument("--mark-replied", type=str, help="Mark recipient email as replied.")
    parser.add_argument("--mark-unsubscribed", type=str, help="Permanently mark recipient email as unsubscribed.")
    parser.add_argument("--mark-bounced", type=str, help="Mark recipient email as bounced.")
    parser.add_argument("--override-reason", type=str, default="", help="Provide explicit justification to bypass circuit breaker for one run.")
    parser.add_argument("--override-circuit-breaker", action="store_true", help="Deprecated: use --override-reason '<reason>' instead.")
    parser.add_argument("--reset-breaker", action="store_true", help="Manually reset a tripped circuit breaker. Requires --reason '<text>'.")
    parser.add_argument("--reason", type=str, default="", help="Operational justification for manual actions.")
    parser.add_argument("--skip-location-audit", action="store_true", help="Skip location verification and city filtering (e.g. for abroad leads).")
    parser.add_argument("--report", action="store_true", help="Print outreach performance report by segment.")
    parser.add_argument("--recheck-delays", action="store_true", help="List delivery delay notices older than 72h with no final result.")


    args = parser.parse_args()

    if args.recheck_delays or args.command == "recheck-delays":
        recheck_delivery_delays(log_filepath=OUTREACH_LOG_CSV)
        return

    if args.reset_breaker or args.command == "reset-breaker":
        justification = (args.reason or args.override_reason).strip()
        if not justification:
            print("\n" + "!" * 75)
            print("[ERROR] --reset-breaker requires a documented operational reason:")
            print("  python outreach_pipeline.py --reset-breaker --reason \"<your reason>\"")
            print("!" * 75 + "\n")
            return
        reset_circuit_breaker(justification)
        return

    global LEADS_CSV
    if args.leads_file:
        LEADS_CSV = args.leads_file

    if args.check_imap:
        user = os.environ.get("SMTP_USER", "")
        password = os.environ.get("SMTP_PASS", "")
        print("\n" + "=" * 70)
        print("EXACT IMAP SETTINGS NEEDED BY THREADING FALLBACK:")
        print(f"  - Host:        {IMAP_HOST}")
        print(f"  - Port:        {IMAP_PORT} (SSL)")
        print(f"  - Sent Folder: {IMAP_SENT_FOLDER} (or 'Sent')")
        print(f"  - User:        {user or '<Not set in SMTP_USER>'}")
        print("=" * 70)
        if not user or not password:
            print("[ERROR] SMTP_USER or SMTP_PASS not set in environment.")
            return
        try:
            print(f"Testing IMAP connection to {IMAP_HOST}:{IMAP_PORT}...")
            mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=10)
            mail.login(user, password)
            status, _ = mail.select(IMAP_SENT_FOLDER)
            if status != "OK":
                status, _ = mail.select("Sent")
            mail.logout()
            print("[OK] IMAP connection and authentication succeeded! Sent folder verified.\n")
        except Exception as e:
            print_imap_login_error(user, e)
        return

    if args.preview_only:
        run_preview_only()
        return

    if args.report or args.command == "report":
        generate_report(log_filepath=OUTREACH_LOG_CSV)
        return

    if args.audit_locations:
        total, updated = audit_leads_location()
        print(f"[AUDIT COMPLETE] Checked {total} leads. Updated {updated} leads.")
        return

    if args.audit_domains or args.list_flagged:
        flagged = audit_leads_domain_match(LEADS_CSV)
        print(f"\n[REVIEW FLAGGED AUDIT] Found {len(flagged)} flagged leads:")
        print("=" * 80)
        for idx, (lead, reason) in enumerate(flagged, 1):
            print(f"{idx:2d}. {lead.get('business_name', '')} ({lead.get('segment', '')})")
            print(f"    Email:   {lead.get('email', '')}")
            print(f"    Website: {lead.get('website', '')}")
            print(f"    Reason:  {reason}")
            print("-" * 80)
        return

    if args.audit_mailboxes:
        flagged = audit_leads_mailboxes(LEADS_CSV)
        print(f"\n[MAILBOX AUDIT] Checked 'new' leads. Flagged {len(flagged)} invalid/unreachable mailboxes:")
        print("=" * 80)
        for idx, (lead, reason) in enumerate(flagged, 1):
            print(f"{idx:2d}. {lead.get('business_name', '')} ({lead.get('segment', '')})")
            print(f"    Email:   {lead.get('email', '')}")
            print(f"    Website: {lead.get('website', '')}")
            print(f"    Reason:  {reason}")
            print("-" * 80)
        return



    if args.command == "sync-inbox" or args.sync_inbox or "sync-inbox" in sys.argv:
        dry_run_mode = bool(args.dry_run or "--dry-run" in sys.argv)
        sync_inbox(dry_run=dry_run_mode)
        return

    if args.override_circuit_breaker and not args.override_reason:
        print("\n" + "!" * 75)
        print("[ERROR] Bare --override-circuit-breaker is disabled for safety.")
        print("To bypass the circuit breaker, you must provide an operational justification:")
        print("  python outreach_pipeline.py --override-reason \"<your reason>\"")
        print("!" * 75 + "\n")
        return

    dry_run_explicit = "--dry-run" in sys.argv
    if args.test_send:
        run_test_send(dry_run=dry_run_explicit)
        return

    if args.test_followup:
        run_test_followup(dry_run=dry_run_explicit)
        return

    if args.mark_replied:
        mark_lead_state(args.mark_replied, "replied")
        return

    if args.mark_unsubscribed:
        mark_lead_state(args.mark_unsubscribed, "unsubscribed")
        return

    if args.mark_bounced:
        mark_lead_state(args.mark_bounced, "bounced")
        return

    if args.find_leads:
        find_leads_for_segment(args.segment, area_name=args.area, limit=args.limit)
        return

    send_live = bool(args.send)
    seg_filter = args.segment if "--segment" in sys.argv else None
    run_outreach(
        send_live=send_live,
        followup_mode=args.followup,
        limit=args.limit,
        force_window=args.force_window,
        warmup=not args.no_warmup,
        segment_filter=seg_filter,
        override_reason=args.override_reason,
        override_circuit_breaker=bool(args.override_reason),
        leads_filepath=args.leads_file if args.leads_file else LEADS_CSV,
        skip_location_audit=args.skip_location_audit,
    )


if __name__ == "__main__":
    main()
