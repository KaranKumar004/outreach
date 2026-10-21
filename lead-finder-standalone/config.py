"""
config.py

Configuration file for LocalLeads Kit.
Modify the defaults below to change the default behavior of the application.
"""

import re

VERSION = "1.0.2"
SUPPORT_EMAIL = "supportlocalleadskit@gmail.com"

# Default search settings
DEFAULT_CITY = "Austin, Texas"
DEFAULT_RADIUS_METERS = 2500
DEFAULT_MAX_LEADS = 25

# Expanded OpenStreetMap tag map for categories
BUSINESS_TAG_MAP = {
    "Real Estate / Estate Agents": ["office=estate_agent", "shop=estate_agent"],
    "Salon / Hairdresser / Spa": ["shop=hairdresser", "shop=beauty", "amenity=spa"],
    "Restaurant / Cafe / Bakery": ["amenity=restaurant", "amenity=cafe", "shop=bakery"],
    "Gym / Fitness / Yoga": [
        "leisure=fitness_centre",
        "amenity=gym",
        'leisure=sports_centre["sport"~"fitness|yoga|pilates|crossfit|gym",i]',
    ],
    "Clinic / Doctor / Dental": [
        "amenity=clinic",
        "amenity=doctors",
        "amenity=dentist",
        "healthcare=clinic",
        "healthcare=doctor",
        "healthcare=dentist",
    ],
    "Lawyer / Legal Services": ["office=lawyer"],
    "Contractor / Construction / Home": [
        "craft=builder",
        "craft=electrician",
        "craft=plumber",
        "craft=carpenter",
        "craft=hvac",
        "craft=roofer",
        "craft=painter",
        "office=construction_company",
    ],
    "Hotel / Hospitality": ["tourism=hotel", "tourism=guest_house"],
    "Coworking / IT / Office": ["office=coworking", "office=it", "office=company", "amenity=coworking_space"],
    "Boutique / Fashion / Retail": ["shop=boutique", "shop=clothes"],
}

# Verified Overpass API endpoints (tested live)
# Includes primary servers and independent verified mirrors
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
]

# Nominatim API
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Honest User-Agent header for website contact crawling and search queries
BROWSER_HEADERS = {
    "User-Agent": f"Mozilla/5.0 (compatible; LocalLeadsKit/{VERSION})",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Directory domains that should NEVER be treated as a business's official website
DIRECTORY_DOMAINS = [
    "justdial.com",
    "sulekha.com",
    "indiamart.com",
    "practo.com",
    "zomato.com",
    "swiggy.com",
    "yelp.com",
    "tripadvisor.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "google.com",
    "maps.google.com",
    "wikipedia.org",
    "twitter.com",
    "x.com",
    "yellowpages.com",
    "foursquare.com",
    "bbb.org",
    "mapquest.com",
    "apple.com",
    "bing.com",
]

# Email validation rules
JUNK_EMAIL_DOMAINS = [
    "example.com",
    "domain.com",
    "email.com",
    "test.com",
    "yourdomain.",
    "sentry",
    "wixpress.com",
]

NO_REPLY_PREFIXES = [
    "noreply",
    "no-reply",
    "donotreply",
    "mailer-daemon",
    "postmaster",
]

FILE_EXTENSION_TLDS = {
    "png", "jpg", "jpeg", "gif", "svg", "webp",
    "woff", "woff2", "ttf", "eot", "css", "js", "pdf",
}

PREFERRED_CONTACT_LOCALS = [
    "info", "contact", "hello", "sales", "enquiry", "care", "support",
]

# Strict email validation patterns
BASE_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
VERSION_PATTERN = re.compile(r"^\d+(\.\d+)+$")
CDN_AND_VERSION_PATTERN = re.compile(r"(@\d|unpkg\.com|cdnjs|jsdelivr|github\.com/.*\.js)", re.IGNORECASE)

# Verification Settings
VERIFICATION_CACHE_FILE = "verified_emails_cache.json"
ZEROBOUNCE_API_URL = "https://api.zerobounce.net/v2/validate"
ZEROBOUNCE_CREDITS_URL = "https://api.zerobounce.net/v2/getcredits"

# Geographic Places Configuration
POPULATION_RADIUS_MAP = [
    (5_000_000, 25_000),  # > 5M population -> 25 km radius
    (1_000_000, 15_000),  # > 1M population -> 15 km radius
    (250_000, 10_000),    # > 250k population -> 10 km radius
    (0, 6_000),           # default -> 6 km radius
]
MAX_SELECTED_NEIGHBORHOODS = 25
NEIGHBORHOOD_CACHE_TTL_DAYS = 30
PLACES_CACHE_DIR = "places_cache"

# Canonical CSV Export Fields
CSV_FIELDS = [
    "business_name",
    "address",
    "phone",
    "phone_e164",
    "email",
    "verification_status",
    "website",
    "maps_url",
    "email_source",
    "phone_source",
    "source_url",
    "business_type",
    "contact_name",
    "contact_method",
    "context_notes",
    "osm_type",
    "osm_id",
    "latitude",
    "longitude",
    "shared_email",
]

# Attribution
# Exact wording matching upstream geonames.org terms
GEONAMES_ATTRIBUTION = "Contains data from GeoNames (https://www.geonames.org), used under the Creative Commons Attribution license (CC BY). See https://www.geonames.org/export/ for terms."



