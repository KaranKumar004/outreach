"""
web_lead_finder.py — Sourcing tool for businesses WITHOUT a website.

Target Offer: Website design & creation services.
Target Audience: Local businesses, agencies, clinics, gyms, salons, restaurants, retail, etc.
Sourcing Strategy:
1. Queries OpenStreetMap / Overpass API for businesses in target locations.
2. Filters exclusively for businesses lacking an active website.
3. Classifies contacts into:
   - 'email': for businesses where a public email is found.
   - 'whatsapp': for businesses with a valid phone number.
4. Exports ready-to-run leads for cold email and WhatsApp outreach.
"""

import os
import sys
import re
import csv
import time
import json
import hashlib
import requests
from typing import Dict, Any, List, Set, Optional
from urllib.parse import urlparse

# Force UTF-8 stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Import WhatsApp generator helper
try:
    from whatsapp_templates import (
        normalize_phone_number,
        is_mobile_number,
        get_whatsapp_message,
        generate_wa_link,
        export_whatsapp_leads
    )
except ImportError:
    from .whatsapp_templates import (
        normalize_phone_number,
        is_mobile_number,
        get_whatsapp_message,
        generate_wa_link,
        export_whatsapp_leads
    )


def load_env_file(filepath: Optional[str] = None):
    """Loads environment variables from .env or .env.local."""
    paths = [
        filepath,
        os.path.join(SCRIPT_DIR, ".env.local"),
        os.path.join(SCRIPT_DIR, ".env"),
        os.path.join(SCRIPT_DIR, "..", ".env.local"),
        os.path.join(SCRIPT_DIR, "..", ".env")
    ]
    for p in paths:
        if p and os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
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

load_env_file()

DEFAULT_PHONE_COUNTRY = os.environ.get("DEFAULT_PHONE_COUNTRY", "IN")
ZEROBOUNCE_API_KEY = os.environ.get("ZEROBOUNCE_API_KEY", "")

SENT_LOG_PATH = os.path.join(SCRIPT_DIR, "sent_log.json")
LEADS_WEBSITE_CSV = os.path.join(SCRIPT_DIR, "leads_website.csv")
LEADS_WHATSAPP_CSV = os.path.join(SCRIPT_DIR, "leads_phone_whatsapp.csv")
VERIFIED_CACHE_PATH = os.path.join(SCRIPT_DIR, "verified_emails_cache.json")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

OSM_HEADERS = {"User-Agent": "WebsiteOutreachFinder/1.0 (contact: outreach@local.org)"}
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

BUSINESS_TAG_MAP = {
    "agency": ["office=advertising", "office=marketing", "office=digital", "office=media", "office=company"],
    "agencies": ["office=advertising", "office=marketing", "office=digital", "office=media", "office=company"],
    "clinic": ["amenity=clinic", "amenity=doctors", "healthcare=clinic"],
    "clinics": ["amenity=clinic", "amenity=doctors", "healthcare=clinic"],
    "dentist": ["amenity=dentist", "healthcare=dentist"],
    "dentists": ["amenity=dentist", "healthcare=dentist"],
    "gym": ["leisure=fitness_centre", "amenity=gym", "leisure=sports_centre"],
    "gyms": ["leisure=fitness_centre", "amenity=gym", "leisure=sports_centre"],
    "salon": ["shop=hairdresser", "shop=beauty", "shop=spa"],
    "salons": ["shop=hairdresser", "shop=beauty", "shop=spa"],
    "restaurant": ["amenity=restaurant", "amenity=cafe"],
    "restaurants": ["amenity=restaurant", "amenity=cafe"],
    "retail": ["shop=boutique", "shop=clothes", "shop=shoes", "shop=electronics", "shop=interior_decoration", "shop=furniture"],
    "accounting": ["office=accountant", "office=financial"],
    "general": ["shop=yes", "office=yes", "amenity=yes"],
}

BASE_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
CDN_AND_VERSION_PATTERN = re.compile(r"(@\d|unpkg\.com|cdnjs|jsdelivr|github\.com/.*\.js)", re.IGNORECASE)


def validate_email(email: str) -> bool:
    """Validates email format strictly."""
    if not email:
        return False
    email_clean = email.strip()
    if not BASE_EMAIL_PATTERN.match(email_clean):
        return False
    if CDN_AND_VERSION_PATTERN.search(email_clean):
        return False
    parts = email_clean.split("@", 1)
    if len(parts) != 2:
        return False
    local_part, domain = parts[0], parts[1]
    if "." not in domain:
        return False
    tld = domain.split(".")[-1]
    if len(tld) < 2 or not tld.isalpha():
        return False
    if any(x in domain.lower() for x in ["wixpress", "sentry", "example.com", "schema.org", "googleapis"]):
        return False
    if local_part.lower() in ["youremail", "yourname", "email", "name", "test"]:
        return False
    return True


def load_sent_log() -> Dict[str, Any]:
    if not os.path.exists(SENT_LOG_PATH):
        return {}
    try:
        with open(SENT_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_sent_log(data: Dict[str, Any]):
    temp_path = SENT_LOG_PATH + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, SENT_LOG_PATH)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def get_lead_id(name: str, phone: str = "", email: str = "") -> str:
    """Returns a unique lead identifier for deduplication."""
    if email and validate_email(email):
        return f"email-{email.strip().lower()}"
    if phone:
        norm_phone = re.sub(r"\D", "", phone)
        if norm_phone:
            return f"phone-{norm_phone}"
    name_clean = re.sub(r"[^a-z0-9]", "", name.lower())
    return f"hash-{hashlib.sha256(name_clean.encode('utf-8')).hexdigest()[:16]}"


def geocode_area(area_name: str) -> Optional[tuple]:
    """Finds lat, lon bounding coordinates for an area."""
    params = {"q": area_name, "format": "json", "limit": 1}
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=OSM_HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"  Geocoding error for {area_name}: {e}")
    return None


def fetch_overpass_listings(tags: List[str], lat: float, lon: float, radius: int = 2500) -> List[Dict[str, Any]]:
    """Queries Overpass API for businesses near coordinates."""
    union_queries = []
    for tag in tags:
        k, v = tag.split("=", 1)
        if v == "yes":
            union_queries.append(f'node["{k}"](around:{radius},{lat},{lon});')
            union_queries.append(f'way["{k}"](around:{radius},{lat},{lon});')
        else:
            union_queries.append(f'node["{k}"="{v}"](around:{radius},{lat},{lon});')
            union_queries.append(f'way["{k}"="{v}"](around:{radius},{lat},{lon});')

    query_str = f"""
    [out:json][timeout:25];
    (
        {' '.join(union_queries)}
    );
    out tags;
    """

    for endpoint in OVERPASS_URLS:
        try:
            resp = requests.post(endpoint, data={"data": query_str}, headers=OSM_HEADERS, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("elements", [])
        except Exception:
            continue
    return []


def search_email_snippet(business_name: str, area_name: str) -> str:
    """Searches Brave Search for any publicly listed contact email for a business."""
    query = f'"{business_name}" "{area_name}" contact email'
    url = "https://search.brave.com/search"
    params = {"q": query}
    try:
        resp = requests.get(url, params=params, headers=BROWSER_HEADERS, timeout=8)
        if resp.status_code == 200:
            emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", resp.text)
            for em in emails:
                if validate_email(em):
                    return em.strip().rstrip(".")
    except Exception:
        pass
    return ""


def check_has_official_website(business_name: str, area_name: str) -> bool:
    """
    Checks if a business actually has a live official website by doing a quick search.
    If search results show only social media (Facebook, Instagram, LinkedIn, Justdial, Indiamart, Maps),
    then they DO NOT have an official website!
    """
    query = f'"{business_name}" {area_name} official website'
    url = "https://search.brave.com/search"
    params = {"q": query}
    try:
        resp = requests.get(url, params=params, headers=BROWSER_HEADERS, timeout=8)
        if resp.status_code == 200:
            links = re.findall(r'href="(https?://[^"]+)"', resp.text)
            social_domains = [
                "brave.com", "google.", "bing.", "yahoo.", "facebook.com", "instagram.com",
                "linkedin.com", "twitter.com", "x.com", "youtube.com", "justdial.com",
                "indiamart.com", "yellowpages", "yelp.com", "tripadvisor.com", "wikipedia.org",
                "zaubacorp.com", "tofler.in", "mapsofindia.com"
            ]
            for link in links[:5]:
                parsed = urlparse(link)
                netloc = parsed.netloc.lower()
                if not any(soc in netloc for soc in social_domains):
                    # Found an independent domain that matches part of the business name
                    name_parts = [p for p in re.sub(r"[^a-z0-9]", " ", business_name.lower()).split() if len(p) > 2]
                    if any(part in netloc for part in name_parts):
                        return True
    except Exception:
        pass
    return False


def run_sourcing(
    business_type: str,
    area_name: str,
    radius: int = 3000,
    max_leads: int = 50,
    country_code: str = DEFAULT_PHONE_COUNTRY
) -> List[Dict[str, Any]]:
    """Runs the full discovery cycle for businesses without websites."""
    print(f"\n=======================================================")
    print(f"SEARCHING FOR '{business_type.upper()}' WITHOUT A WEBSITE")
    print(f"Location: {area_name} (Radius: {radius}m)")
    print(f"=======================================================")

    coords = geocode_area(area_name)
    if not coords:
        print(f"Could not geocode location: '{area_name}'")
        return []

    lat, lon = coords
    print(f"Geocoded coordinates: {lat}, {lon}")

    tags = BUSINESS_TAG_MAP.get(business_type.lower(), BUSINESS_TAG_MAP["general"])
    print(f"Querying Overpass API...")
    elements = fetch_overpass_listings(tags, lat, lon, radius=radius)
    print(f"Found {len(elements)} raw listings from OpenStreetMap.")

    sent_log = load_sent_log()
    qualifying_leads: List[Dict[str, Any]] = []

    for item in elements:
        t = item.get("tags", {})
        name = t.get("name")
        if not name or len(name.strip()) < 2:
            continue

        # FILTER 1: EXCLUDE ANY BUSINESS WITH A WEBSITE TAG IN OSM
        osm_website = t.get("website") or t.get("contact:website") or ""
        if osm_website.strip():
            continue

        phone = t.get("phone") or t.get("contact:phone") or t.get("contact:mobile") or ""
        email = t.get("email") or t.get("contact:email") or ""

        # Normalize lead id for deduplication
        lead_id = get_lead_id(name, phone=phone, email=email)
        if lead_id in sent_log:
            continue

        # Check if they have an email or phone
        if not phone and not email:
            # Try to locate a contact email from search
            email = search_email_snippet(name, area_name)
            time.sleep(0.3)

        if not phone and not email:
            # Cannot reach without email or phone
            continue

        # Verify they don't have a hidden official website
        has_site = check_has_official_website(name, area_name)
        if has_site:
            continue

        if email and validate_email(email):
            channel = "email"
        elif phone and is_mobile_number(phone, default_country=country_code):
            channel = "whatsapp"
        elif phone:
            channel = "phone_call"
        else:
            continue

        norm_phone = normalize_phone_number(phone, default_country=country_code)

        lead_entry = {
            "business_name": name.strip(),
            "segment": business_type.lower(),
            "area": area_name,
            "website": "",
            "email": email.strip() if validate_email(email) else "",
            "phone": phone.strip(),
            "normalized_phone": norm_phone,
            "channel": channel,
            "status": "ready",
            "last_contacted": "",
            "notes": f"No website found. Sourced via OSM & area scan in {area_name}"
        }

        qualifying_leads.append(lead_entry)
        sent_log[lead_id] = {
            "business_name": name.strip(),
            "sourced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "channel": channel,
            "status": "sourced"
        }

        if len(qualifying_leads) >= max_leads:
            break

    save_sent_log(sent_log)
    print(f"\nDiscovered {len(qualifying_leads)} verified businesses without a website!")
    return qualifying_leads


def save_leads_to_csv(leads: List[Dict[str, Any]], country_code: str = DEFAULT_PHONE_COUNTRY):
    """Appends leads to master leads_website.csv and exports leads_phone_whatsapp.csv."""
    if not leads:
        return

    file_exists = os.path.exists(LEADS_WEBSITE_CSV)
    fieldnames = [
        "business_name",
        "segment",
        "area",
        "website",
        "email",
        "phone",
        "normalized_phone",
        "channel",
        "status",
        "last_contacted",
        "notes"
    ]

    # Append to master leads_website.csv
    with open(LEADS_WEBSITE_CSV, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for l in leads:
            writer.writerow({k: l.get(k, "") for k in fieldnames})

    print(f"Saved {len(leads)} leads to: {LEADS_WEBSITE_CSV}")

    # Export WhatsApp / Phone leads
    phone_leads = [l for l in leads if l.get("phone")]
    if phone_leads:
        count = export_whatsapp_leads(phone_leads, LEADS_WHATSAPP_CSV, default_country=country_code)
        print(f"Exported {count} WhatsApp/Phone outreach leads to: {LEADS_WHATSAPP_CSV}")


def print_report():
    """Prints status breakdown of website outreach leads."""
    sent_log = load_sent_log()
    print("\n==================================================")
    print("WEBSITE CREATION OUTREACH TRACKING REPORT")
    print("==================================================")
    print(f"Total Unique Businesses Sourced: {len(sent_log)}")
    channels = {}
    for entry in sent_log.values():
        ch = entry.get("channel", "unknown")
        channels[ch] = channels.get(ch, 0) + 1
    for ch, count in channels.items():
        print(f"  - Channel [{ch}]: {count}")
    print("==================================================")


def main():
    if len(sys.argv) < 2:
        print("Usage: py web_lead_finder.py <business_type> <location> [radius_meters] [max_leads]")
        print("       py web_lead_finder.py --report")
        print("\nExamples:")
        print("  py web_lead_finder.py agency Koramangala 3000")
        print("  py web_lead_finder.py clinic \"Indiranagar, Bengaluru\"")
        print("  py web_lead_finder.py dentist \"Austin, TX\" 15000")
        sys.exit(1)

    if sys.argv[1] == "--report":
        print_report()
        sys.exit(0)

    biz_type = sys.argv[1].lower()
    location = sys.argv[2] if len(sys.argv) > 2 else "Bengaluru"
    radius = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
    max_leads = int(sys.argv[4]) if len(sys.argv) > 4 else 30

    leads = run_sourcing(biz_type, location, radius=radius, max_leads=max_leads)
    if leads:
        save_leads_to_csv(leads)
    else:
        print("No new qualifying businesses found without a website in this area.")


if __name__ == "__main__":
    main()
