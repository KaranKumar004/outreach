"""
lead_finder_buildings.py — Free commercial building and company lead sourcing tool.

Uses OpenStreetMap Overpass API and geocodes via Nominatim.
Tailored for B2B commercial building contracting leads (e.g. offices, factories, schools).

Upgraded Version:
- Caps maximum listings analyzed per run to 12 to prevent rate-limiting and speed up searches.
- Uses separate User-Agents for OpenStreetMap APIs and web browser scrapers.
- Supports Brave Search web lookup fallback for websites and emails when OSM lacks them.
- Guesses high-probability emails (e.g. info@domain) based on found websites.
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
SENT_LOG_PATH = "sent_log.json"

# Maps building/business category to OpenStreetMap tags.
BUILDING_TAG_MAP = {
    "retail_store": ["shop=department", "shop=supermarket", "shop=mall", "shop=retail"],
    "restaurant": ["amenity=restaurant"],
    "cafe": ["amenity=cafe"],
    "salon": ["shop=hairdresser", "shop=beauty"],
    "clinic": ["amenity=clinic", "amenity=doctors"],
    "gym": ["leisure=fitness_centre", "amenity=gym"],
    "coworking_space": ["office=coworking", "amenity=coworking"],
    "office": ["office=yes", "office=company", "office=commercial"],
    "bank_branch": ["amenity=bank"],
    "school": ["amenity=school", "amenity=college"],
    "hospital": ["amenity=hospital"],
    "hotel": ["tourism=hotel"],
    "warehouse": ["industrial=warehouse", "building=warehouse"],
    "factory": ["industrial=factory", "building=factory", "craft=sawmill", "craft=carpenter"],
    "it_park": ["office=it", "boundary=industrial"],
    "logistics_company": ["office=logistics", "industrial=logistics"]
}

# Separate headers for compliance and compatibility
OSM_HEADERS = {"User-Agent": "LeadPilotBuildingsFinder/1.2 (B2B contracting lead finder, non-commercial)"}
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


def generate_context_notes(category, website):
    """Generates building-centric B2B context notes based on the category."""
    base_note = f"Website: {website}" if website else "No website listed"
    category = category.lower()
    
    if category == "office":
        hook = "Potential requirements: office fit-outs, interior partition repairs, ceiling grid replacements, and wall painting."
    elif category == "warehouse":
        hook = "Potential requirements: structural concrete repairs, industrial flooring upgrades, structural steel reinforcements, and exterior heavy-duty scaffolding."
    elif category == "factory":
        hook = "Potential requirements: machine foundation concrete work, industrial roof leaks repair, structural steel painting, and safety barrier installations."
    elif category == "retail_store":
        hook = "Potential requirements: shop facade refurbishment, display racking civil anchoring, floor tiling repairs, and lighting layout civil modifications."
    elif category in ["restaurant", "cafe"]:
        hook = "Potential requirements: kitchen drainage plumbing/tiling renovations, dining space wooden interiors restoration, waterproof kitchen coating, and decorative plastering."
    elif category == "coworking_space":
        hook = "Potential requirements: acoustical wall panel installation, cafeteria layout expansion, minor cabin construction, and ceiling ducting repairs."
    elif category in ["hospital", "clinic"]:
        hook = "Potential requirements: medical-grade hygienic flooring, antibacterial wall painting, concrete access ramp construction, and sterile zone partitions."
    elif category == "school":
        hook = "Potential requirements: classroom ceiling repairs, sports court surface coating, playground boundary wall plastering, and washroom block renovation."
    elif category == "hotel":
        hook = "Potential requirements: lobby marble polishing, exterior facade scaffolding painting, swimming pool tiling/waterproofing, and ballroom decorative POP ceiling."
    elif category == "it_park":
        hook = "Potential requirements: external landscaping civil elements, structural expansion joint waterproofing, common area pathway repaving, and glass facade cleaning scaffolding."
    elif category == "logistics_company":
        hook = "Potential requirements: truck loading dock repairs, concrete apron expansion, heavy machinery floor grouting, and security check elements."
    else:
        hook = "Potential requirements: general building masonry repairs, interior partition updates, waterproof tiling, and scaffolding hire for maintenance."
        
    return f"{base_note}. {hook}"


def search_website_via_brave(business_name, area_name):
    """Search Brave Search to find the official website for a business."""
    query = f"{business_name} {area_name} Bengaluru website"
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
    query = f'"{business_name}" "{area_name}" Bengaluru contact email'
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
    """Turn a neighborhood name into (lat, lon) using Nominatim."""
    params = {"q": f"{area_name}, Bengaluru, India", "format": "json", "limit": 1}
    resp = requests.get(NOMINATIM_URL, params=params, headers=OSM_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        print(f"Warning: Could not find coordinates for area: {area_name}")
        return None, None
    return float(data[0]["lat"]), float(data[0]["lon"])


def build_overpass_query(tags, lat, lon, radius_m):
    """Build an Overpass QL query for the given tags within radius_m of (lat, lon)."""
    parts = []
    for tag in tags:
        key, value = tag.split("=")
        parts.append(f'node(around:{radius_m},{lat},{lon})["{key}"="{value}"];')
        parts.append(f'way(around:{radius_m},{lat},{lon})["{key}"="{value}"];')
    return "[out:json][timeout:25];(" + "".join(parts) + ");out center tags;"


def search_area_businesses(category, area_name, radius_m=1500):
    """Find commercial buildings of a given category in a single area."""
    lat, lon = geocode_area(area_name)
    if lat is None or lon is None:
        return []

    tags = BUILDING_TAG_MAP[category]
    query = build_overpass_query(tags, lat, lon, radius_m)

    resp = requests.post(OVERPASS_URL, data={"data": query}, headers=OSM_HEADERS, timeout=60)
    resp.raise_for_status()
    elements = resp.json().get("elements", [])

    results = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        results.append({
            "business_name": name.strip(),
            "business_type": category,
            "phone": tags.get("phone") or tags.get("contact:phone") or "",
            "website": tags.get("website") or tags.get("contact:website") or "",
        })
    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: python lead_finder_buildings.py <category> <area_names_separated_by_commas> [radius_meters]")
        print("       python lead_finder_buildings.py --report")
        sys.exit(1)

    if sys.argv[1] == "--report":
        print_report()
        sys.exit(0)

    if len(sys.argv) < 3:
        print("Error: Missing area argument.")
        print("Usage: python lead_finder_buildings.py <category> <area_names_separated_by_commas> [radius_meters]")
        sys.exit(1)

    category = sys.argv[1].lower()
    area_input = sys.argv[2]
    radius_m = int(sys.argv[3]) if len(sys.argv) > 3 else 1500

    if category not in BUILDING_TAG_MAP:
        print(f"Error: Unknown commercial category '{category}'.")
        print(f"Supported: {', '.join(BUILDING_TAG_MAP)}")
        sys.exit(1)

    # Parse multi-area input
    areas = [a.strip() for a in area_input.split(",") if a.strip()]

    print("Loading tracking database and existing CSVs...")
    seen_names = load_existing_leads()
    log_data = load_sent_log()
    print(f"Loaded {len(seen_names)} unique existing business names.")

    new_ready_rows = []
    new_phone_only_rows = []
    new_rejected_rows = []
    new_unverified_rows = []

    total_found_leads = 0
    total_verified_valid = 0
    total_verified_invalid = 0
    total_verified_risky = 0
    total_no_email = 0
    total_catch_all_no_phone = 0

    for area in areas:
        print(f"\nSearching for commercial '{category}' near '{area}' (radius {radius_m}m)...")
        try:
            businesses = search_area_businesses(category, area, radius_m)
        except Exception as e:
            print(f"Error searching near '{area}': {e}")
            continue

        print(f"Found {len(businesses)} total listings in Overpass.")
        
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

        # Cap results to avoid API / engine blocks
        max_leads = 12
        if len(unseen_businesses) > max_leads:
            print(f"Capping analysis from {len(unseen_businesses)} to {max_leads} new commercial listings to prevent rate-limiting.")
            unseen_businesses = unseen_businesses[:max_leads]

        print(f"{len(unseen_businesses)} new commercial sites to analyze. Scoping websites...")
        
        for idx, biz in enumerate(unseen_businesses):
            print(f"  [{idx+1}/{len(unseen_businesses)}] Checking {biz['business_name']}...")
            email = ""
            website = biz["website"]
            
            # Step 1: Web lookup fallback if website is not in OSM
            if not website:
                print(f"    - No website in OSM. Searching web...")
                website = search_website_via_brave(biz["business_name"], area)
                if website:
                    print(f"      Found website: {website}")
                    biz["website"] = website
                time.sleep(1)

            # Step 2: Try parsing email from the site
            email_source = ""
            if website:
                email = find_email_on_site(website)
                if email:
                    email_source = f"Scraped from website: {website}"
                    time.sleep(1)
            
            # Step 3: Extract email directly from search snippets
            if not email:
                email = search_email_via_brave(biz["business_name"], area)
                if email:
                    email_source = "Extracted from search snippets"
                    time.sleep(1)

            # Step 4: Guess domain-based email as placeholder
            is_guessed = False
            if not email and website:
                try:
                    parsed = urlparse(website)
                    domain = parsed.netloc
                    if domain.startswith("www."):
                        domain = domain[4:]
                    if domain:
                        guessed_email = f"info@{domain}"
                        if validate_email(guessed_email):
                            email = guessed_email
                            is_guessed = True
                            email_source = f"Guessed info@{domain} based on website"
                except Exception:
                    pass

            # Step 5: Validate and route
            is_valid_email = validate_email(email)
            
            # Compute identifier (uses original email if it passes format check)
            identifier = get_lead_identifier(email if is_valid_email else "", biz["phone"], biz["business_name"])
            
            # Deduplicate against the persistent tracking database
            if identifier in log_data:
                print(f"    - Skipping (lead already exists in persistent tracking log: {identifier})")
                continue

            # Increment count of new leads evaluated
            total_found_leads += 1

            # Determine routing and contact method using ZeroBounce verification
            verification_status = "none"
            if is_valid_email and email:
                print(f"    - Running real-time email verification for {email}...")
                verification_status = verify_email_exists(email)
                print(f"      Verification status: {verification_status}")
                
                if verification_status == "valid":
                    total_verified_valid += 1
                    contact_method = "email"
                elif verification_status == "invalid":
                    total_verified_invalid += 1
                    contact_method = "email"
                else: # risky or unknown
                    total_verified_risky += 1
                    if biz["phone"]:
                        contact_method = "phone"
                    else:
                        contact_method = "unverified"
                        total_catch_all_no_phone += 1
            else:
                email = ""  # Erase invalid email format
                total_no_email += 1
                if biz["phone"]:
                    contact_method = "phone"
                else:
                    contact_method = "none"

            # Construct category-aware notes
            notes = generate_context_notes(biz["business_type"], website)
            if is_valid_email and email:
                note_tag = f"[Email Source: {email_source}] [Verification: {verification_status}]"
            else:
                note_tag = "[Email Source: None/Invalid]"

            row = {
                "business_name": biz["business_name"],
                "email": email,  # String (either valid/risky email or "")
                "business_type": biz["business_type"],
                "contact_name": "",
                "phone": biz["phone"],
                "context_notes": f"{note_tag} {notes}",
                "contact_method": contact_method,
            }

            # Log the new lead in our tracking database
            log_data[identifier] = {
                "identifier": identifier,
                "business_name": biz["business_name"],
                "source": f"lead_finder_buildings.py -- category: {category}, area: {area}",
                "date_first_sourced": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "date_last_contacted": None,
                "contact_status": "new",
                "number_of_contacts": 0
            }

            # Route to appropriate lists
            if is_valid_email and email:
                if verification_status == "valid":
                    new_ready_rows.append(row)
                    print(f"    *** Found email: {email} (Verified Valid) -> Added to leads_ready_for_email.csv")
                elif verification_status == "invalid":
                    new_rejected_rows.append(row)
                    print(f"    - Invalid Email: {email} (Verified Invalid) -> Added to leads_rejected.csv")
                else: # risky / unknown
                    if biz["phone"]:
                        new_phone_only_rows.append(row)
                        print(f"    - Risky Email: {email} but has Phone: {biz['phone']} -> Added to leads_phone_only.csv")
                    else:
                        new_unverified_rows.append(row)
                        print(f"    - Risky/Catch-All Email: {email} (No Phone) -> Added to leads_unverified.csv (Review manually)")
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
            print("Make sure this CSV file is not open in Excel or another program, then run the script again.")
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

    print("\n==================================================")
    print("COMMERCIAL SWEEP COMPLETE.")
    print("New leads saved in this run:")
    print(f"  + {ready_count} leads -> leads_ready_for_email.csv (verified valid)")
    print(f"  + {rejected_count} leads -> leads_rejected.csv (verified invalid or no contact info)")
    print(f"  + {phone_count} leads -> leads_phone_only.csv (risky or no email, but has phone)")
    print(f"  + {unverified_count} leads -> leads_unverified.csv (risky/catch-all with no phone)")
    
    if total_catch_all_no_phone > 0:
        print(f"\n  [ATTENTION] {total_catch_all_no_phone} catch-all, no phone -- review leads_unverified.csv manually before discarding!")
        
    print("\nVerification statistics for this run:")
    print(f"  Found {total_found_leads} new leads -> {total_verified_valid} verified valid, "
          f"{total_verified_invalid} invalid, {total_verified_risky} risky, {total_no_email} no email found")
    print("==================================================")


if __name__ == "__main__":
    main()
