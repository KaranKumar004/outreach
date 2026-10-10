"""
lead_finder.py — Free local business lead sourcing tool.

Upgraded Version:
- Caps maximum listings analyzed per run to 12 to prevent rate-limiting and speed up searches.
- Uses separate User-Agents for OpenStreetMap APIs and web browser scrapers.
- Supports Brave Search web lookup fallback for official websites when OSM lacks them.
- Strictly forbids synthesizing info@domain or guessing emails. Accepts only emails found on the page with a source URL.
- Employs strict generic email validation to filter out JS library / CDN references.
- Supports nullable emails and contact_method field ('email' / 'phone').
- Persistent sent_log.json tracking to avoid duplicate sourcing and repeated contacts.
- Atomic file writes to prevent file corruption.
- Simple report CLI parameter (--report).
"""

import os
import requests
import re
import csv
import sys
import time
import json
import hashlib
from urllib.parse import urlparse, urljoin

# Force stdout to use UTF-8 encoding to prevent UnicodeEncodeError on Windows terminals
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Environment variable loader
def load_env_file(filepath=".env.local"):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("=", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if val.startswith(('"', "'")) and val.endswith(('"', "'")):
                        val = val[1:-1]
                    os.environ[key] = val

# Load environment variables
load_env_file(".env")
load_env_file(".env.local")

ZEROBOUNCE_API_KEY = os.environ.get("ZEROBOUNCE_API_KEY", "")
CACHE_FILE_PATH = "verified_emails_cache.json"

def load_verification_cache():
    if not os.path.exists(CACHE_FILE_PATH):
        return {}
    try:
        with open(CACHE_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not read {CACHE_FILE_PATH} ({e}). Returning empty cache.")
        return {}

def save_verification_cache(cache_data):
    temp_filepath = CACHE_FILE_PATH + ".tmp"
    try:
        with open(temp_filepath, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
        os.replace(temp_filepath, CACHE_FILE_PATH)
    except Exception as e:
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except Exception:
                pass
        print(f"Warning: Could not save verification cache atomically: {e}")

def verify_email_exists(email):
    """
    Verifies if an email exists using ZeroBounce API with caching and retry logic.
    Returns: "valid", "invalid", "risky", or "unknown"
    """
    email_clean = email.strip().lower()
    if not email_clean:
        return "unknown"
        
    cache = load_verification_cache()
    if email_clean in cache:
        return cache[email_clean].get("status", "unknown")
        
    if not ZEROBOUNCE_API_KEY:
        print(f"    - [API Warning] ZEROBOUNCE_API_KEY is not set. Skipping verification for {email_clean}")
        return "unknown"
        
    url = "https://api.zerobounce.net/v2/validate"
    params = {
        "api_key": ZEROBOUNCE_API_KEY,
        "email": email_clean,
        "ip_address": ""
    }
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            # Short timeout of 10s. ZeroBounce usually responds in <1s.
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "error" in data:
                    print(f"    - [API Error] ZeroBounce API returned error: {data['error']}")
                    return "unknown"
                    
                api_status = data.get("status")
                # Map ZeroBounce status to internal status
                if api_status == "valid":
                    status = "valid"
                elif api_status in ["invalid", "spamtrap", "abuse", "do_not_mail"]:
                    status = "invalid"
                elif api_status == "catch-all":
                    status = "risky"
                else:
                    status = "unknown"
                    
                # Cache the response
                cache[email_clean] = {
                    "status": status,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }
                save_verification_cache(cache)
                return status
            elif response.status_code == 429:
                print(f"    - [API Warning] ZeroBounce rate limit hit (429). Retrying in 2 seconds...")
                time.sleep(2)
            else:
                print(f"    - [API Warning] ZeroBounce API returned HTTP {response.status_code}. Retrying in 2 seconds...")
                time.sleep(2)
        except (requests.Timeout, requests.RequestException) as e:
            print(f"    - [API Warning] Request attempt {attempt+1} failed: {e}. Retrying in 2 seconds...")
            time.sleep(2)
            
    return "unknown"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_URLS = [
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
SENT_LOG_PATH = "sent_log.json"

# Maps business_type to OpenStreetMap tags.
BUSINESS_TAG_MAP = {
    "real estate": ["office=estate_agent"],
    "salon": ["shop=hairdresser", "shop=beauty"],
    "restaurant": ["amenity=restaurant", "amenity=cafe"],
    "gym": ["leisure=fitness_centre", "amenity=gym"],
    "clinic": ["amenity=clinic", "amenity=doctors"],
    "boutique": ["shop=boutique", "shop=clothes"],
    "dentist": ["amenity=dentist", "healthcare=dentist"],
    "dentists": ["amenity=dentist", "healthcare=dentist"],
}

# Separate headers for compliance and compatibility
OSM_HEADERS = {"User-Agent": "LeadPilotFinder/1.2 (contact: buyer@gmail.com)"}
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}

# Strict email validation
BASE_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
VERSION_PATTERN = re.compile(r"^\d+(\.\d+)+$")
CDN_AND_VERSION_PATTERN = re.compile(r"(@\d|unpkg\.com|cdnjs|jsdelivr|github\.com/.*\.js)", re.IGNORECASE)

CSV_FIELDS = ["business_name", "email", "business_type", "contact_name", "phone", "context_notes", "contact_method"]


def validate_email(email):
    if not email:
        return False
    email_clean = email.strip()
    
    # 1. Base format check
    if not BASE_EMAIL_PATTERN.match(email_clean):
        return False
        
    # 2. Reject if email contains version indicators or CDN keywords
    if CDN_AND_VERSION_PATTERN.search(email_clean):
        return False
        
    parts = email_clean.split("@", 1)
    local_part, domain = parts[0], parts[1]
    
    # 3. Baseline TLD check: must end in 2+ letter alphabet-only TLD
    domain_parts = domain.split(".")
    if len(domain_parts) < 2:
        return False
    tld = domain_parts[-1]
    if len(tld) < 2 or not tld.isalpha():
        return False
        
    # 4. Reject if domain portion has no letters (e.g. 1.8.1)
    if not any(c.isalpha() for c in domain):
        return False
        
    # 5. Reject if domain matches a version-only pattern (e.g. 3.2.2)
    if VERSION_PATTERN.match(domain):
        return False

    # 6. Reject template placeholders and SDK/error tracking domains (Sentry, Wix, etc.)
    domain_lower = domain.lower()
    local_lower = local_part.lower()
    if any(x in domain_lower for x in ["wixpress", "sentry", "example.com", "schema.org", "googleapis"]):
        return False
    if local_lower in ["youremail", "yourname", "email", "name", "test"]:
        return False
        
    return True


def load_sent_log():
    if not os.path.exists(SENT_LOG_PATH):
        return {}
    try:
        with open(SENT_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not read sent_log.json ({e}). Returning empty log.")
        return {}


def save_log_atomic(log_data, filepath=SENT_LOG_PATH):
    temp_filepath = filepath + ".tmp"
    try:
        with open(temp_filepath, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)
        os.replace(temp_filepath, filepath)
    except Exception as e:
        if os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except Exception:
                pass
        print(f"\n[ERROR] Could not save sent_log.json atomically: {e}")
        print("Please make sure the file is not locked or open in another application.")


def get_lead_identifier(email, phone, business_name):
    if email and validate_email(email):
        return email.strip().lower()
    if phone:
        cleaned_phone = re.sub(r"[^0-9+]", "", phone)
        if cleaned_phone:
            return cleaned_phone
    name_slug = re.sub(r"[^a-z0-9]", "", business_name.lower())
    if not name_slug:
        name_slug = "unknown"
    return f"hash-{hashlib.sha256(name_slug.encode('utf-8')).hexdigest()[:16]}"


def load_existing_leads():
    """Load all seen names from sent_log.json and existing CSV files to prevent duplicates."""
    seen_names = set()
    
    # 1. Load from sent_log.json
    log_data = load_sent_log()
    for ident, entry in log_data.items():
        if entry.get("business_name"):
            seen_names.add(entry["business_name"].strip().lower())
            
    # 2. Load from existing CSV files if present
    for csv_file in ["leads_ready_for_email.csv", "leads_phone_only.csv", "leads_rejected.csv", "leads_unverified.csv"]:
        if os.path.exists(csv_file):
            try:
                with open(csv_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get("business_name"):
                            seen_names.add(row["business_name"].strip().lower())
            except Exception:
                pass
                
    return seen_names


def print_report():
    log_data = load_sent_log()
    total = len(log_data)
    new_count = sum(1 for e in log_data.values() if e.get("contact_status") == "new")
    sent_count = sum(1 for e in log_data.values() if e.get("contact_status") == "sent")
    bounced_count = sum(1 for e in log_data.values() if e.get("contact_status") == "bounced")
    replied_count = sum(1 for e in log_data.values() if e.get("contact_status") == "replied")
    won_count = sum(1 for e in log_data.values() if e.get("contact_status") == "won")
    lost_count = sum(1 for e in log_data.values() if e.get("contact_status") == "lost")
    
    print("\n==================================================")
    print("LEADPILOT OUTREACH TRACKING REPORT")
    print("==================================================")
    print(f"Total Leads Tracked: {total}")
    print(f"  - New (Never Contacted): {new_count}")
    print(f"  - Sent (Contacted): {sent_count}")
    print(f"  - Bounced: {bounced_count}")
    print(f"  - Replied: {replied_count}")
    print(f"  - Won: {won_count}")
    print(f"  - Lost: {lost_count}")
    print("==================================================")


def normalize_phone_us(raw_phone):
    """Normalize US phone numbers to (512) 555-0123 format."""
    if not raw_phone:
        return ""
    digits = re.sub(r"\D", "", str(raw_phone))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return str(raw_phone).strip()


def strip_tracking_params(url):
    """Strip tracking parameters (utm_*, ?y_source=..., fbclid, gclid) from URL."""
    if not url:
        return ""
    try:
        import urllib.parse
        parsed = urlparse(url)
        if not parsed.query:
            return url
        qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        filtered = [
            (k, v) for k, v in qs
            if not k.lower().startswith("utm_")
            and not k.lower().startswith("fbclid")
            and not k.lower().startswith("gclid")
            and k.lower() not in ("y_source", "ref", "source", "_ga", "_gl")
        ]
        new_query = urllib.parse.urlencode(filtered)
        return urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
    except Exception:
        return url


def search_website_via_brave(business_name, area_name):
    """Search Brave Search to find the official website for a business."""
    loc = area_name if ("austin" in area_name.lower() or "," in area_name) else f"{area_name} Bengaluru"
    query = f"{business_name} {loc} website"
    url = "https://search.brave.com/search"
    params = {"q": query}
    try:
        resp = requests.get(url, params=params, headers=BROWSER_HEADERS, timeout=10)
        if resp.status_code == 200:
            links = re.findall(r'href="([^"]+)"', resp.text)
            for link in links:
                if link.startswith("http") and not any(x in link.lower() for x in ["brave.com", "google", "microsoft.com", "msn.com", "w3.org", "wikipedia.org", "justdial.com", "indiamart.com", "facebook.com", "twitter.com", "instagram.com", "linkedin.com", "youtube.com", "pinterest.com", "tiktok.com", "reddit.com"]):
                    return link
    except Exception as e:
        print(f"    - Search warning: {e}")
    return ""


def search_email_via_brave(business_name, area_name):
    """Search Brave Search to extract an email from search snippets directly."""
    loc = area_name if ("austin" in area_name.lower() or "," in area_name) else f"{area_name} Bengaluru"
    query = f'"{business_name}" "{loc}" contact email'
    url = "https://search.brave.com/search"
    params = {"q": query}
    try:
        resp = requests.get(url, params=params, headers=BROWSER_HEADERS, timeout=10)
        if resp.status_code == 200:
            emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", resp.text)
            for email in emails:
                if validate_email(email):
                    return email.strip().rstrip('.')
    except Exception as e:
        print(f"    - Search email warning: {e}")
    return ""


def find_email_on_site(url, timeout=10):
    """Fetch a website and look for a contact email, scanning sub-pages too."""
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        html = resp.text
        
        # Check main page
        mailto_match = re.search(r"mailto:([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", html)
        if mailto_match and validate_email(mailto_match.group(1)):
            return mailto_match.group(1).strip().rstrip('.')
            
        emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", html)
        for email in emails:
            if validate_email(email):
                return email.strip().rstrip('.')
            
        # Try contact, about, or reach page links
        links = re.findall(r'href=["\']([^"\']*(?:contact|about|reach)[^"\']*)["\']', html, re.I)
        for clink in links:
            if any(x in clink.lower() for x in [".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".woff", ".ico"]):
                continue
            
            contact_url = clink
            if not contact_url.startswith("http"):
                contact_url = urljoin(url, contact_url)
            
            try:
                resp_contact = requests.get(contact_url, headers=BROWSER_HEADERS, timeout=timeout)
                html_contact = resp_contact.text
                mailto_match = re.search(r"mailto:([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", html_contact)
                if mailto_match and validate_email(mailto_match.group(1)):
                    return mailto_match.group(1).strip().rstrip('.')
                emails_contact = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", html_contact)
                for email in emails_contact:
                    if validate_email(email):
                        return email.strip().rstrip('.')
            except Exception:
                pass
    except Exception:
        pass
    return ""


def geocode_area(area_name):
    """Turn an area or neighborhood name into (lat, lon) using Nominatim."""
    q = area_name.strip()
    params = {"q": q, "format": "json", "limit": 1}
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=OSM_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if not data and "," not in q:
            # Fallback for bare local Bengaluru neighborhood names
            params = {"q": f"{q}, Bengaluru, India", "format": "json", "limit": 1}
            resp = requests.get(NOMINATIM_URL, params=params, headers=OSM_HEADERS, timeout=15)
            data = resp.json()
        if not data:
            print(f"Warning: Could not find coordinates for area: {area_name}")
            return None, None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"Warning: Geocoding failed for {area_name}: {e}")
        return None, None


def build_overpass_query(tags, lat, lon, radius_m):
    """Build an Overpass QL query for the given tags within radius_m of (lat, lon)."""
    parts = []
    for tag in tags:
        key, value = tag.split("=")
        parts.append(f'node(around:{radius_m},{lat},{lon})["{key}"="{value}"];')
        parts.append(f'way(around:{radius_m},{lat},{lon})["{key}"="{value}"];')
    return "[out:json][timeout:25];(" + "".join(parts) + ");out center tags;"


def search_area_businesses(business_type, area_name, radius_m=25000):
    """Find businesses of a given type in a single area with mirror failover."""
    lat, lon = geocode_area(area_name)
    if lat is None or lon is None:
        return []

    tags = BUSINESS_TAG_MAP[business_type]
    query = build_overpass_query(tags, lat, lon, radius_m)

    elements = []
    for mirror in OVERPASS_URLS:
        try:
            resp = requests.post(mirror, data={"data": query}, headers=OSM_HEADERS, timeout=30)
            if resp.status_code == 200:
                elements = resp.json().get("elements", [])
                break
        except Exception:
            continue

    results = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue

        osm_email = tags.get("email") or tags.get("contact:email") or ""
        if osm_email and not validate_email(osm_email):
            osm_email = ""

        raw_rev = tags.get("review_count") or tags.get("reviews") or tags.get("rating:count") or 0
        try:
            rev_count = int(raw_rev)
        except Exception:
            rev_count = 0

        results.append({
            "business_name": name.strip(),
            "business_type": business_type,
            "phone": tags.get("phone") or tags.get("contact:phone") or "",
            "website": tags.get("website") or tags.get("contact:website") or "",
            "email": osm_email,
            "review_count": rev_count,
        })
    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: python lead_finder.py <business_type> <area_names_separated_by_commas> [radius_meters]")
        print("       python lead_finder.py \"<niche> in <location>\"")
        print("       python lead_finder.py --report")
        sys.exit(1)

    if sys.argv[1] == "--report":
        print_report()
        sys.exit(0)

    # Support single-string query format like "Dentists in Austin, TX"
    if len(sys.argv) == 2 and " in " in sys.argv[1].lower():
        parts = re.split(r"\s+in\s+", sys.argv[1], flags=re.IGNORECASE, maxsplit=1)
        business_type = parts[0].strip().lower()
        area_input = parts[1].strip()
        radius_m = 25000
    elif len(sys.argv) >= 3:
        business_type = sys.argv[1].lower()
        area_input = sys.argv[2]
        radius_m = int(sys.argv[3]) if len(sys.argv) > 3 else (25000 if ("austin" in area_input.lower() or "," in area_input) else 1500)
    else:
        print("Error: Missing area argument.")
        print("Usage: python lead_finder.py <business_type> <area_names_separated_by_commas> [radius_meters]")
        sys.exit(1)

    if business_type not in BUSINESS_TAG_MAP:
        print(f"Error: Unknown business type '{business_type}'.")
        print(f"Supported: {', '.join(BUSINESS_TAG_MAP)}")
        sys.exit(1)

    # Parse multi-area input without splitting "City, State" (e.g. Austin, TX)
    if re.search(r",\s*[A-Z]{2}$", area_input, re.IGNORECASE):
        areas = [area_input]
    else:
        areas = [a.strip() for a in area_input.split(",") if a.strip()]

    print("Loading tracking database...")
    seen_names = set()
    log_data = load_sent_log()

    new_ready_rows = []
    new_phone_only_rows = []
    new_rejected_rows = []
    new_unverified_rows = []
    all_analyzed_leads = []

    total_found_leads = 0
    total_verified_valid = 0
    total_verified_invalid = 0
    total_verified_risky = 0
    total_no_email = 0
    total_catch_all_no_phone = 0

    for area in areas:
        print(f"\nSearching for '{business_type}' near '{area}' (radius {radius_m}m)...")
        try:
            businesses = search_area_businesses(business_type, area, radius_m)
        except Exception as e:
            print(f"Error searching near '{area}': {e}")
            continue

        print(f"Found {len(businesses)} total business listings in Overpass.")
        
        # Filter duplicates in memory first
        unseen_businesses = []
        for biz in businesses:
            name_lower = biz["business_name"].lower()
            if name_lower in seen_names:
                continue
            seen_names.add(name_lower)
            unseen_businesses.append(biz)

        if not unseen_businesses:
            print("All listings in this area have already been sourced in previous runs.")
            continue

        # Target 50-100 businesses
        max_leads = 100
        if len(unseen_businesses) > max_leads:
            print(f"Capping analysis from {len(unseen_businesses)} to {max_leads} new businesses.")
            unseen_businesses = unseen_businesses[:max_leads]

        print(f"{len(unseen_businesses)} new businesses to analyze. Scoping websites...")
        
        for idx, biz in enumerate(unseen_businesses):
            print(f"  [{idx+1}/{len(unseen_businesses)}] Checking {biz['business_name']}...")
            email = biz.get("email") or ""
            website = biz.get("website") or ""
            
            # Step 1: Web lookup fallback if website is not in OSM
            if not website:
                website = search_website_via_brave(biz["business_name"], area)
                if website:
                    print(f"      Found website: {website}")
                    biz["website"] = website
                time.sleep(0.5)

            # Step 2: If listing has no email, visit business website (homepage + /contact) and extract public email with regex
            email_source = ""
            if email:
                email_source = f"OSM listing ({website or 'OpenStreetMap'})"
            elif website:
                found_addr = find_email_on_site(website, timeout=8)
                if found_addr:
                    email = found_addr
                    email_source = f"Scraped from website: {website}"
                    time.sleep(0.5)

            # Strictly require valid source_url; never synthesize or guess info@domain
            is_valid_email = validate_email(email)
            if not is_valid_email or not email_source:
                email = ""
                email_source = ""
            biz["email"] = email
            biz["email_source"] = email_source
            all_analyzed_leads.append(biz)
            
            # Compute identifier
            identifier = get_lead_identifier(email, biz["phone"], biz["business_name"])
            
            if identifier in log_data:
                print(f"    - Skipping (lead already exists in persistent tracking log: {identifier})")
                continue

            total_found_leads += 1

            # Determine routing and contact method using ZeroBounce verification if available
            verification_status = "none"
            if email:
                print(f"    - Running real-time email verification for {email}...")
                verification_status = verify_email_exists(email)
                print(f"      Verification status: {verification_status}")
                
                if verification_status == "valid":
                    total_verified_valid += 1
                    contact_method = "email"
                elif verification_status == "invalid":
                    total_verified_invalid += 1
                    contact_method = "email"
                else:
                    total_verified_risky += 1
                    if biz["phone"]:
                        contact_method = "phone"
                    else:
                        contact_method = "unverified"
                        total_catch_all_no_phone += 1
            else:
                total_no_email += 1
                if biz["phone"]:
                    contact_method = "phone"
                else:
                    contact_method = "none"

            # Construct notes
            base_note = f"Website: {website}" if website else "No website listed"
            if email:
                note_tag = f"[Email Source: {email_source}] [Verification: {verification_status}]"
            else:
                note_tag = "[Email Source: None]"

            row = {
                "business_name": biz["business_name"],
                "email": email,
                "business_type": biz["business_type"],
                "contact_name": "",
                "phone": biz["phone"],
                "context_notes": f"{note_tag} {base_note}",
                "contact_method": contact_method,
            }

            log_data[identifier] = {
                "identifier": identifier,
                "business_name": biz["business_name"],
                "source": f"lead_finder.py -- category: {business_type}, area: {area}",
                "date_first_sourced": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "date_last_contacted": None,
                "contact_status": "new",
                "number_of_contacts": 0
            }

            # Route to appropriate lists
            if email:
                if verification_status == "valid":
                    new_ready_rows.append(row)
                    print(f"    *** Found email: {email} (Verified Valid) -> Added to leads_ready_for_email.csv")
                elif verification_status == "invalid":
                    new_rejected_rows.append(row)
                    print(f"    - Invalid Email: {email} (Verified Invalid) -> Added to leads_rejected.csv")
                else:
                    if biz["phone"]:
                        new_phone_only_rows.append(row)
                        print(f"    - Risky Email: {email} but has Phone: {biz['phone']} -> Added to leads_phone_only.csv")
                    else:
                        new_unverified_rows.append(row)
                        print(f"    - Risky/Catch-All Email: {email} (No Phone) -> Added to leads_unverified.csv")
            else:
                if biz["phone"]:
                    new_phone_only_rows.append(row)
                    print(f"    - Phone Only: {biz['phone']} -> Added to leads_phone_only.csv")
                else:
                    new_rejected_rows.append(row)
                    print("    - No valid email or phone found -> Added to leads_rejected.csv")

    # Load existing CSV rows to append, ensuring we do not delete previously gathered rows
    def append_rows_to_csv(filepath, new_rows):
        if not new_rows:
            return 0
        existing_rows = []
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for r in reader:
                        existing_rows.append(r)
            except Exception:
                pass
        
        all_rows = existing_rows + new_rows
        
        try:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                writer.writeheader()
                writer.writerows(all_rows)
            return len(new_rows)
        except PermissionError:
            print(f"\n[ERROR] Permission Denied: Could not save to '{filepath}'.")
            return 0
        except Exception as e:
            print(f"\n[ERROR] Failed to write to {filepath}: {e}")
            return 0

    # Write CSVs
    ready_count = append_rows_to_csv("leads_ready_for_email.csv", new_ready_rows)
    phone_count = append_rows_to_csv("leads_phone_only.csv", new_phone_only_rows)
    rejected_count = append_rows_to_csv("leads_rejected.csv", new_rejected_rows)
    unverified_count = append_rows_to_csv("leads_unverified.csv", new_unverified_rows)

    # Save the atomic log
    save_log_atomic(log_data)

    # ----------------- CLEAN DATA & EXPORT PROOF CSV -----------------
    clean_proof_rows = []
    seen_dedupe_phones = set()
    seen_dedupe_sites = set()

    for b in all_analyzed_leads:
        raw_phone = b.get("phone", "")
        norm_phone = normalize_phone_us(raw_phone)
        
        raw_site = b.get("website", "")
        clean_site = strip_tracking_params(raw_site)
        
        # Drop rows with no phone AND no website
        if not norm_phone and not clean_site:
            continue
            
        # Dedupe by phone and website
        is_dup = False
        if norm_phone and norm_phone in seen_dedupe_phones:
            is_dup = True
        if clean_site:
            clean_dom = urlparse(clean_site).netloc.lower().replace("www.", "") or clean_site.lower()
            if clean_dom in seen_dedupe_sites:
                is_dup = True
                
        if is_dup:
            continue
            
        if norm_phone:
            seen_dedupe_phones.add(norm_phone)
        if clean_site:
            clean_dom = urlparse(clean_site).netloc.lower().replace("www.", "") or clean_site.lower()
            seen_dedupe_sites.add(clean_dom)

        email_clean = b.get("email", "").strip()
        if not validate_email(email_clean):
            email_clean = ""

        clean_row = {
            "business_name": b.get("business_name", "").strip(),
            "phone": norm_phone,
            "email": email_clean,
            "website": clean_site,
            "review_count": int(b.get("review_count", 0)),
        }
        clean_proof_rows.append(clean_row)

    # Sort by review_count descending
    clean_proof_rows.sort(key=lambda r: int(r.get("review_count", 0)), reverse=True)

    # Save as dentists_austin_sample.csv
    proof_filename = "dentists_austin_sample.csv"
    proof_fields = ["business_name", "phone", "email", "website", "review_count"]
    with open(proof_filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=proof_fields)
        writer.writeheader()
        writer.writerows(clean_proof_rows)

    # Print summary: total rows, % with email, % with website, top 5 rows
    total_rows = len(clean_proof_rows)
    with_email_cnt = sum(1 for r in clean_proof_rows if r.get("email"))
    with_site_cnt = sum(1 for r in clean_proof_rows if r.get("website"))
    pct_email = (with_email_cnt / total_rows * 100) if total_rows > 0 else 0.0
    pct_site = (with_site_cnt / total_rows * 100) if total_rows > 0 else 0.0

    print("\n==================================================")
    print("DENTISTS IN AUSTIN, TX — PROOF EXPORT SUMMARY")
    print("==================================================")
    print(f"Total rows: {total_rows}")
    print(f"% with email: {pct_email:.1f}% ({with_email_cnt}/{total_rows})")
    print(f"% with website: {pct_site:.1f}% ({with_site_cnt}/{total_rows})")
    print("\nTop 5 rows:")
    for idx, r in enumerate(clean_proof_rows[:5], 1):
        print(f"  {idx}. {r['business_name']} | Phone: {r['phone']} | Email: {r['email']} | Website: {r['website']} | Reviews: {r['review_count']}")
    print(f"\nSaved clean proof CSV to: {proof_filename}")
    print("==================================================")


if __name__ == "__main__":
    main()

