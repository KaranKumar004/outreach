"""
leadcore.py — LocalLeads Kit Core Processing Engine.

Pure business and data logic with zero streamlit imports.
Includes:
- Anti-garbage email validation & ranking
- Safe phone extraction and E.164 normalization via phonenumbers
- OpenStreetMap Nominatim geocoding with strict 1 req/s rate limits
- Overpass API querying with multi-mirror failover & exponential backoff
- Concurrent website crawling with per-domain politeness
- Directory domain filtering
- ZeroBounce API integration & cache
- Deduplication keyed on OSM element ID
- Atomic file writes & formula injection protection for CSV export
"""

import os
import re
import csv
import time
import json
import socket
import math
import logging
from typing import Dict, List, Tuple, Optional, Any, Set
from urllib.parse import urlparse, urljoin, unquote
from urllib.robotparser import RobotFileParser
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
import phonenumbers

import config

logger = logging.getLogger("leadcore")

# Canonical CSV Fields (v1.0.2 schema)
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

# Valid status taxonomy
VALID_STATUSES = {"valid", "risky", "invalid", "unknown", "unverified", "guessed", "no_email"}

# Valid source provenance taxonomy (machine values)
VALID_SOURCE_VALUES = {"osm_tag", "website_crawl", "search_snippet", "guessed_domain", ""}


class CrawlResult(tuple):
    """
    Tuple containing (best_email, display_phone, e164_phone, crawl_diagnostic).
    Preserves exact 4-tuple unpacking for backwards compatibility,
    while exposing .source_url attribute for the page a crawled value came from.
    """
    def __new__(cls, email: str, phone: str, e164: str, diagnostic: str, source_url: str = ""):
        obj = super().__new__(cls, (email, phone, e164, diagnostic))
        obj.source_url = source_url
        obj.email = email
        obj.phone = phone
        obj.e164 = e164
        obj.diagnostic = diagnostic
        return obj

    def __getitem__(self, item: Any) -> Any:
        if item == 4:
            return self.source_url
        return super().__getitem__(item)


def safe_clean_str(val: Any) -> str:
    """
    Safely converts any value to a trimmed string.
    Returns empty string if val is None, float NaN/inf, or case-insensitive 'nan'.
    """
    if val is None:
        return ""
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return ""
    s = str(val).strip()
    if s.lower() == "nan":
        return ""
    return s


# =====================================================================
# 1. Domain & URL Helpers
# =====================================================================

def clean_domain(url_or_domain: str) -> str:
    """Extracts a clean, lowercase domain name without www or port."""
    val = safe_clean_str(url_or_domain).lower()
    if not val:
        return ""
    if not val.startswith(("http://", "https://")):
        val = "http://" + val
    try:
        parsed = urlparse(val)
        domain = parsed.netloc or parsed.path
        if ":" in domain:
            domain = domain.split(":", 1)[0]
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.strip(".")
    except Exception:
        return ""


def is_directory_domain(url_or_domain: str) -> bool:
    """Checks whether the domain belongs to known directories, socials, or search engines."""
    domain = clean_domain(url_or_domain)
    if not domain:
        return False
    for directory in config.DIRECTORY_DOMAINS:
        directory_clean = directory.lower().strip(".")
        if domain == directory_clean or domain.endswith("." + directory_clean):
            return True
    return False


NON_HTML_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".txt",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".rar",
    ".csv", ".tsv",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tif", ".tiff",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".m4a", ".flac",
    ".exe", ".dmg", ".pkg", ".deb", ".rpm", ".iso", ".bin",
)


def is_non_html_url(url_or_path: str) -> bool:
    """
    Checks whether a URL or path ends in a non-HTML file extension
    (e.g., .pdf, .docx, .zip) that cannot yield scraped contact web pages.
    """
    if not url_or_path:
        return False
    try:
        val = safe_clean_str(url_or_path)
        if not val.startswith(("http://", "https://")):
            val = "https://" + val
        parsed = urlparse(val)
        path = unquote(parsed.path or "").strip().lower().rstrip("/")
        return any(path.endswith(ext) for ext in NON_HTML_EXTENSIONS)
    except Exception:
        return False


KNOWN_TWO_PART_TLDS = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk", "net.uk",
    "co.in", "net.in", "org.in", "gen.in", "ind.in", "nic.in",
    "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.nz", "net.nz", "org.nz", "govt.nz",
    "co.za", "org.za", "net.za",
    "com.br", "net.br", "org.br",
    "co.jp", "ne.jp", "or.jp", "ac.jp",
    "com.mx", "org.mx", "gob.mx",
    "com.sg", "org.sg", "gov.sg",
    "com.tr", "org.tr", "gov.tr",
    "com.tw", "org.tw", "idv.tw",
    "com.hk", "org.hk", "gov.hk",
    "com.ar", "com.co", "com.pk",
}


def get_registrable_domain(url_or_domain: str) -> str:
    """
    Extracts the registrable domain (e.g. 'example.com' from 'sub.example.com',
    or 'example.co.uk' from 'www.sub.example.co.uk').
    Treats www and subdomains on the same registrable domain as the same site.
    """
    domain = clean_domain(url_or_domain)
    if not domain:
        return ""
    parts = domain.split(".")
    if len(parts) <= 2:
        return domain
    two_part = f"{parts[-2]}.{parts[-1]}"
    if two_part in KNOWN_TWO_PART_TLDS and len(parts) >= 3:
        return f"{parts[-3]}.{parts[-2]}.{parts[-1]}"
    return f"{parts[-2]}.{parts[-1]}"


_robots_cache: Dict[str, Optional[RobotFileParser]] = {}


def is_path_allowed_by_robots(
    target_url: str,
    user_agent: Optional[str] = None,
    timeout: int = 4
) -> bool:
    """
    Checks robots.txt for target_url's domain. Caches RobotFileParser per domain.
    Returns True if crawling the path is allowed, or if robots.txt is unavailable/404.
    Returns False only if explicitly disallowed.
    """
    reg_dom = get_registrable_domain(target_url)
    if not reg_dom:
        return True

    ua = user_agent or config.BROWSER_HEADERS.get("User-Agent", "*")

    if reg_dom in _robots_cache:
        rp = _robots_cache[reg_dom]
        if rp is None:
            return True
        try:
            return rp.can_fetch(ua, target_url) or rp.can_fetch("*", target_url)
        except Exception:
            return True

    try:
        parsed = urlparse(target_url)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or clean_domain(target_url)
        robots_url = f"{scheme}://{netloc}/robots.txt"

        rp = RobotFileParser()
        resp = requests.get(robots_url, headers=config.BROWSER_HEADERS, timeout=timeout)
        if resp.status_code == 200 and resp.text:
            rp.parse(resp.text.splitlines())
            _robots_cache[reg_dom] = rp
            return rp.can_fetch(ua, target_url) or rp.can_fetch("*", target_url)
        else:
            _robots_cache[reg_dom] = None
            return True
    except Exception:
        _robots_cache[reg_dom] = None
        return True


def normalize_source_value(val: Any) -> str:
    """
    Normalizes provenance source string to standard machine taxonomy:
    'osm_tag', 'website_crawl', 'search_snippet', 'guessed_domain', or ''.
    Migrates legacy human strings from older releases.
    """
    s = safe_clean_str(val).lower()
    if not s:
        return ""
    if s in ("osm_tag", "osm_tags", "osm tag", "osm tags"):
        return "osm_tag"
    if s in ("website_crawl", "website crawl", "crawl", "scraped"):
        return "website_crawl"
    if s in ("search_snippet", "search snippet", "search snippet (domain matched)", "brave_search"):
        return "search_snippet"
    if s in ("guessed_domain", "guessed", "domain placeholder", "domain placeholder (info@)"):
        return "guessed_domain"
    return s


def build_google_maps_url(
    business_name: str = "",
    address_or_area: str = "",
    lat: Optional[float] = None,
    lon: Optional[float] = None
) -> str:
    """
    Builds documented Google Maps search URL scheme without external API calls.
    Scheme: https://www.google.com/maps/search/?api=1&query={encoded_query}
    Query = URL-encoded 'business_name, address (or suburb/city)' when available;
    falls back to f'{lat},{lon}'.
    """
    from urllib.parse import quote_plus

    name_clean = safe_clean_str(business_name)
    area_clean = safe_clean_str(address_or_area)

    parts = [p for p in [name_clean, area_clean] if p]
    if parts:
        query_str = ", ".join(parts)
    elif lat is not None and lon is not None and not (isinstance(lat, float) and math.isnan(lat)) and not (isinstance(lon, float) and math.isnan(lon)):
        query_str = f"{lat},{lon}"
    else:
        return ""

    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query_str)}"


def format_osm_address(tags_dict: Dict[str, Any]) -> str:
    """
    Builds a clean, human-readable address from OSM address tags:
    addr:housenumber, addr:street, addr:suburb, addr:city, addr:postcode.
    Returns comma-separated string, omitting blank segments.
    """
    if not isinstance(tags_dict, dict):
        return ""

    housenumber = safe_clean_str(tags_dict.get("addr:housenumber"))
    street = safe_clean_str(tags_dict.get("addr:street"))
    suburb = safe_clean_str(tags_dict.get("addr:suburb") or tags_dict.get("addr:neighbourhood") or tags_dict.get("addr:district"))
    city = safe_clean_str(tags_dict.get("addr:city") or tags_dict.get("addr:town") or tags_dict.get("addr:village"))
    postcode = safe_clean_str(tags_dict.get("addr:postcode"))

    street_line = f"{housenumber} {street}".strip() if (housenumber and street) else (street or housenumber)
    segments = [s for s in [street_line, suburb, city, postcode] if s]
    if segments:
        return ", ".join(segments)
    return safe_clean_str(tags_dict.get("addr:full"))


# =====================================================================
# 2. Email Validation & Ranking
# =====================================================================

def validate_email(email: Any) -> bool:
    """
    Validates an email address against syntax, CDN/library names,
    junk domains, file-extension TLDs, and noreply addresses.
    """
    e = safe_clean_str(email).lower()
    if not e:
        return False

    # 1. Base format regex
    if not config.BASE_EMAIL_PATTERN.match(e):
        return False

    # 2. CDN, unpkg, version indicators
    if config.CDN_AND_VERSION_PATTERN.search(e):
        return False

    parts = e.split("@", 1)
    if len(parts) != 2:
        return False
    local_part, domain = parts[0], parts[1]

    # 3. Reject noreply / robot prefix addresses
    for prefix in config.NO_REPLY_PREFIXES:
        if local_part == prefix or local_part.startswith(prefix + "-") or local_part.startswith(prefix + "_") or local_part.startswith(prefix + "."):
            return False
    if local_part in config.NO_REPLY_PREFIXES:
        return False

    # 4. Domain & TLD checks
    domain_parts = domain.split(".")
    if len(domain_parts) < 2:
        return False
    tld = domain_parts[-1]
    if tld in config.FILE_EXTENSION_TLDS:
        return False
    if len(tld) < 2 or not tld.isalpha():
        return False
    if config.VERSION_PATTERN.match(domain):
        return False
    if not any(c.isalpha() for c in domain):
        return False

    # 5. Reject placeholder/junk domains
    for junk in config.JUNK_EMAIL_DOMAINS:
        junk_clean = junk.lower()
        if os.environ.get("LOCALLEADS_DEMO") and junk_clean == "example.com":
            if domain == "example.com":
                return False
            continue
        if junk_clean.endswith("."):
            if domain.startswith(junk_clean) or f".{junk_clean}" in domain:
                return False
        else:
            if domain == junk_clean or domain.endswith("." + junk_clean) or junk_clean in domain:
                return False

    return True


def select_best_email(emails: List[str], website_url: str = "") -> str:
    """
    Ranks a list of candidate emails and selects the highest-quality address.
    Prioritizes emails on the business domain and contact-style local parts.
    """
    valid_emails = [em.strip().lower() for em in emails if validate_email(em)]
    if not valid_emails:
        return ""

    website_domain = clean_domain(website_url)

    def score_email(em: str) -> int:
        score = 0
        local_part, domain = em.split("@", 1)
        if website_domain and (domain == website_domain or domain.endswith("." + website_domain)):
            score += 20
        for pref in config.PREFERRED_CONTACT_LOCALS:
            if local_part == pref or local_part.startswith(pref):
                score += 10
                break
        return score

    ranked = sorted(valid_emails, key=score_email, reverse=True)
    return ranked[0]


# =====================================================================
# 3. Phone Extraction & Normalization via phonenumbers
# =====================================================================

def normalize_phone(raw_phone: Any, default_region: Optional[str] = None) -> Tuple[str, str]:
    """
    Parses and normalizes a phone number using libphonenumber.
    Derives default region from Nominatim country code (e.g., 'IN', 'US', 'GB').
    Accepts ONLY is_valid_number results.
    Rejects timestamps, GA codes, postal codes, and dates.

    Returns:
        (display_phone, e164_phone) if valid, else ("", "")
    """
    cleaned = safe_clean_str(raw_phone)
    if not cleaned:
        return "", ""

    # Fast rejection of obviously non-phone strings
    # 1. Dates like 2024-05-12 or 2024/05/12
    if re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}$", cleaned):
        return "", ""
    # 2. Google Analytics tracking IDs (UA-XXXXX)
    if cleaned.upper().startswith("UA-"):
        return "", ""
    # 3. Large unix timestamps (e.g. 13-digit millisecond epoch)
    digits_only = re.sub(r"\D", "", cleaned)
    if len(digits_only) >= 13 and not cleaned.startswith("+"):
        return "", ""
    # 4. Short pincodes (5 or 6 digits with no separators or +)
    if len(digits_only) <= 6 and not cleaned.startswith("+") and " " not in cleaned and "-" not in cleaned:
        return "", ""

    region = default_region.upper() if default_region else None

    try:
        num_obj = phonenumbers.parse(cleaned, region)
        if phonenumbers.is_valid_number(num_obj):
            e164 = phonenumbers.format_number(num_obj, phonenumbers.PhoneNumberFormat.E164)
            # Use international format if not in national region, else national format
            display = phonenumbers.format_number(num_obj, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
            return display, e164
    except Exception:
        pass

    return "", ""


# =====================================================================
# 4. Web Crawling & Contact Scraping
# =====================================================================

def decode_cfemail(cf_hex: str) -> str:
    """
    Decodes Cloudflare email protection data-cfemail hex string.
    The first 2 hex chars are the XOR key; subsequent 2-char pairs are XOR'd chars.
    """
    try:
        cf_hex = str(cf_hex).strip()
        if len(cf_hex) < 4 or len(cf_hex) % 2 != 0:
            return ""
        key = int(cf_hex[:2], 16)
        email_chars = [chr(int(cf_hex[i:i+2], 16) ^ key) for i in range(2, len(cf_hex), 2)]
        return "".join(email_chars).strip()
    except Exception:
        return ""


def detect_contact_form(soup: BeautifulSoup) -> bool:
    """
    Detects if the page contains a contact or inquiry form.
    """
    if not soup:
        return False

    # 1. Forms with inputs or textareas
    for form in soup.find_all("form"):
        inputs = form.find_all(["input", "textarea", "button", "select"])
        if len(inputs) >= 1:
            return True
        form_attrs = " ".join([
            form.get("action", ""),
            form.get("id", ""),
            " ".join(form.get("class", []))
        ]).lower()
        if any(w in form_attrs for w in ("contact", "form", "submit", "message", "inquiry", "appointment", "reach")):
            return True

    # 2. Form container classes (e.g. form builders / embeds)
    for div in soup.find_all(["div", "section"]):
        classes = " ".join(div.get("class", [])).lower()
        elem_id = str(div.get("id", "")).lower()
        combined = f"{classes} {elem_id}"
        if any(w in combined for w in ("wpforms", "gravityform", "contact-form", "form-wrapper", "formspree", "hubspot-form", "jotform")):
            return True

    # 3. Standalone textarea
    if soup.find("textarea"):
        return True

    return False


def extract_contacts_from_html(html: str, base_url: str, default_region: Optional[str] = None) -> Tuple[List[str], str, str, List[str]]:
    """
    Extracts mailto links, Cloudflare data-cfemail, [at]/(at) de-obfuscated emails,
    visible emails, tel: links, and visible phones. Also discovers internal contact/about subpages.
    """
    if not html:
        return [], "", "", []

    soup = BeautifulSoup(html, "html.parser")
    found_emails: List[str] = []
    found_phones: List[str] = []

    # 0. Cloudflare data-cfemail extraction (before any tags are stripped)
    for elem in soup.find_all(attrs={"data-cfemail": True}):
        cf_hex = elem.get("data-cfemail", "")
        dec = decode_cfemail(cf_hex)
        if dec and validate_email(dec):
            found_emails.append(dec)

    for cf_hex in re.findall(r'data-cfemail=["\']([0-9a-fA-F]{4,})["\']', html):
        dec = decode_cfemail(cf_hex)
        if dec and validate_email(dec):
            found_emails.append(dec)

    # 1. Mailto links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if validate_email(addr):
                found_emails.append(addr)
        elif href.lower().startswith("tel:"):
            ph = href[4:].split("?")[0].strip()
            found_phones.append(ph)

    # Remove non-content tags for text parsing
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "template"]):
        tag.decompose()

    # 2. Extract visible text only
    text = soup.get_text(separator=" ")

    # 3a. Standard email regex over visible text
    text_emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", text)
    for em in text_emails:
        clean_em = em.strip().rstrip(".")
        if validate_email(clean_em):
            found_emails.append(clean_em)

    # 3b. [at] / (at) de-obfuscation in visible text
    # e.g. contact [at] domain [dot] com, info(at)site.com, hello AT clinic DOT org
    obf_pattern = re.compile(
        r'\b([a-zA-Z0-9_.+-]+)\s*(?:\[at\]|\(at\)|\{at\}|\s+at\s+)\s*([a-zA-Z0-9-]+)\s*(?:\[dot\]|\(dot\)|\{dot\}|\s+dot\s+|\.)\s*([a-zA-Z]{2,10}(?:\s*(?:\[dot\]|\(dot\)|\.)\s*[a-zA-Z]{2,10})?)\b',
        re.IGNORECASE
    )
    for match in obf_pattern.finditer(text):
        local_part = match.group(1).strip()
        domain_part = match.group(2).strip()
        tld_part = re.sub(r'\s*(?:\[dot\]|\(dot\)|\{dot\}|\s+dot\s+|\.)\s*', '.', match.group(3).strip())
        deobf_email = f"{local_part}@{domain_part}.{tld_part}".lower()
        if validate_email(deobf_email):
            found_emails.append(deobf_email)

    # 4. Phone search in visible text using phonenumbers matcher
    best_display_phone, best_e164_phone = "", ""
    for ph in found_phones:
        disp, e164 = normalize_phone(ph, default_region)
        if disp:
            best_display_phone, best_e164_phone = disp, e164
            break

    if not best_display_phone:
        region = default_region.upper() if default_region else None
        try:
            for match in phonenumbers.PhoneNumberMatcher(text, region):
                if phonenumbers.is_valid_number(match.number):
                    e164 = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
                    disp = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
                    best_display_phone, best_e164_phone = disp, e164
                    break
        except Exception:
            pass

    # 5. Discover subpages (contact, about)
    subpages: List[str] = []
    base_domain = clean_domain(base_url)
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        href_lower = href.lower()
        if any(keyword in href_lower for keyword in ["contact", "about", "reach", "connect", "get-in-touch"]):
            if not is_non_html_url(href) and not any(ext in href_lower for ext in [".css", ".js"]):
                full_url = urljoin(base_url, href)
                if clean_domain(full_url) == base_domain and full_url != base_url:
                    if full_url not in subpages:
                        subpages.append(full_url)

    return found_emails, best_display_phone, best_e164_phone, subpages[:2]


def crawl_website_contacts(
    url: str,
    default_region: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: Tuple[float, float] = (8.0, 15.0),
    total_deadline: float = 30.0,
) -> CrawlResult:
    """
    Crawls official business website and candidate subpages for email and phone.
    Returns: CrawlResult(best_email, display_phone, e164_phone, crawl_diagnostic, source_url).
    Supports 4-tuple unpacking for backwards compatibility, with .source_url property.
    Diagnostics: 'email found', 'fetch failed', 'no email on page', 'contact-form only',
                 'blocked', 'redirected to external domain: ...', 'contact page disallowed by robots.txt',
                 'linked file, not a website'.
    Enforces per-site total deadline (default 30s), separate connect (8s) / read (15s) timeouts,
    one retry, max 5 redirects, robots.txt compliance, and strict SSL verification.
    """
    if not url or is_directory_domain(url):
        return CrawlResult("", "", "", "directory domain skipped", "")

    if is_non_html_url(url):
        logger.info(f"Crawl {url}: linked file, not a website")
        return CrawlResult("", "", "", "linked file, not a website", "")

    target_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
    req_headers = headers or config.BROWSER_HEADERS

    all_emails: List[str] = []
    email_url_map: Dict[str, str] = {}
    display_phone, e164_phone = "", ""
    phone_found_url = ""
    form_detected = False
    robots_disallowed_contact = False

    start_time = time.perf_counter()

    def get_remaining_timeout(connect_limit: float = 8.0, read_limit: float = 15.0) -> Tuple[float, float]:
        elapsed = time.perf_counter() - start_time
        remaining = total_deadline - elapsed
        if remaining <= 0:
            raise requests.exceptions.Timeout("Per-site total deadline exceeded")
        c_to = min(connect_limit, max(0.5, remaining))
        r_to = min(read_limit, max(0.5, remaining - c_to))
        return (c_to, r_to)

    def fetch_url(u: str) -> requests.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(2):
            if (time.perf_counter() - start_time) >= total_deadline:
                raise requests.exceptions.Timeout("Per-site total deadline exceeded")
            c_to, r_to = get_remaining_timeout(timeout[0], timeout[1])
            try:
                return requests.get(u, headers=req_headers, timeout=(c_to, r_to), verify=True)
            except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout) as err:
                last_exc = err
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise err
            except requests.exceptions.RequestException as err:
                raise err
        if last_exc:
            raise last_exc
        raise requests.exceptions.RequestException("Fetch failed")

    # 1. Fetch homepage
    resp: Optional[requests.Response] = None
    try:
        resp = fetch_url(target_url)
    except (requests.exceptions.SSLError, requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as err:
        # Try www / non-www variant ONLY on DNS / Connect / SSL errors
        # (NOT on ReadTimeout or HTTP errors)
        parsed = urlparse(target_url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            variant_netloc = netloc[4:]
        else:
            variant_netloc = f"www.{netloc}"
        variant_url = f"{parsed.scheme}://{variant_netloc}{parsed.path}"
        if parsed.query:
            variant_url += f"?{parsed.query}"

        try:
            resp = fetch_url(variant_url)
            target_url = variant_url
        except Exception:
            # If initial https:// scheme failed with SSLError or Connect/Connection error,
            # probe http:// on port 80 to check if server redirects to canonical HTTPS or new domain.
            # verify=True is still strictly enforced on the response / redirect destination.
            if target_url.startswith("https://"):
                http_candidate = f"http://{parsed.netloc}{parsed.path}"
                if parsed.query:
                    http_candidate += f"?{parsed.query}"
                try:
                    resp = fetch_url(http_candidate)
                    target_url = http_candidate
                except Exception:
                    logger.info(f"Crawl {target_url}: homepage fetch failed ({err.__class__.__name__})")
                    return CrawlResult("", "", "", "fetch failed", "")
            else:
                logger.info(f"Crawl {target_url}: homepage fetch failed ({err.__class__.__name__})")
                return CrawlResult("", "", "", "fetch failed", "")
    except Exception as err:
        logger.info(f"Crawl {target_url}: homepage fetch failed ({err.__class__.__name__})")
        return CrawlResult("", "", "", "fetch failed", "")

    if resp is None:
        return CrawlResult("", "", "", "fetch failed", "")

    # Check max 5 redirects
    history = getattr(resp, "history", [])
    if isinstance(history, list) and len(history) > 5:
        logger.info(f"Crawl {target_url}: exceeded 5 redirects ({len(history)})")
        return CrawlResult("", "", "", "fetch failed", "")

    # Check blocked
    if resp.status_code in (403, 429) or (resp.status_code == 503 and "cloudflare" in str(getattr(resp, "text", "")).lower()):
        logger.info(f"Crawl {target_url}: blocked (HTTP {resp.status_code})")
        return CrawlResult("", "", "", "blocked", "")

    # If homepage failed (status != 200), skip contact-page fetches
    if resp.status_code != 200:
        logger.info(f"Crawl {target_url}: fetch failed (HTTP {resp.status_code})")
        return CrawlResult("", "", "", "fetch failed", "")

    # Determine effective final URL
    raw_resp_url = getattr(resp, "url", None)
    if raw_resp_url and isinstance(raw_resp_url, str):
        effective_url = raw_resp_url
    else:
        effective_url = target_url

    # Check cross-domain redirect:
    # Treat www/subdomain redirects on the same registrable domain as the same site.
    # Only flag a different registrable domain.
    orig_reg_dom = get_registrable_domain(target_url)
    final_reg_dom = get_registrable_domain(effective_url)
    if orig_reg_dom and final_reg_dom and orig_reg_dom != final_reg_dom:
        diag = f"redirected to external domain: {clean_domain(effective_url)}"
        logger.info(f"Crawl {target_url}: {diag}")
        return CrawlResult("", "", "", diag, "")

    # Extract contacts from homepage
    html_text = str(getattr(resp, "text", ""))
    emails, ph_disp, ph_e164, subpages = extract_contacts_from_html(html_text, effective_url, default_region)
    for em in emails:
        all_emails.append(em)
        if em not in email_url_map:
            email_url_map[em] = effective_url
    if ph_disp:
        display_phone, e164_phone = ph_disp, ph_e164
        phone_found_url = effective_url

    form_detected = detect_contact_form(BeautifulSoup(html_text, "html.parser"))

    # 2. Fetch candidate subpages if contacts missing and time permits
    if (not all_emails or not display_phone) and subpages:
        for sub_url in subpages:
            if (time.perf_counter() - start_time) >= total_deadline:
                logger.info(f"Crawl {target_url}: per-site deadline reached, stopping subpage crawl")
                break

            # Check robots.txt per domain (cached) before fetching contact pages
            if not is_path_allowed_by_robots(sub_url, user_agent=req_headers.get("User-Agent")):
                logger.info(f"Skipping contact subpage {sub_url}: disallowed by robots.txt")
                robots_disallowed_contact = True
                continue

            time.sleep(0.5)
            try:
                c_to, r_to = get_remaining_timeout(timeout[0], timeout[1])
                sub_resp = requests.get(sub_url, headers=req_headers, timeout=(c_to, r_to), verify=True)
                if sub_resp.status_code == 200:
                    sub_effective_url = str(getattr(sub_resp, "url", sub_url))
                    sub_reg_dom = get_registrable_domain(sub_effective_url)
                    if orig_reg_dom and sub_reg_dom and sub_reg_dom != orig_reg_dom:
                        logger.info(f"Subpage {sub_url} redirected to external domain {sub_effective_url}, skipping")
                        continue
                    sub_text = str(getattr(sub_resp, "text", ""))
                    sub_emails, sub_disp, sub_e164, _ = extract_contacts_from_html(sub_text, sub_effective_url, default_region)
                    for em in sub_emails:
                        all_emails.append(em)
                        if em not in email_url_map:
                            email_url_map[em] = sub_effective_url
                    if sub_disp and not display_phone:
                        display_phone, e164_phone = sub_disp, sub_e164
                        phone_found_url = sub_effective_url
                    if not form_detected:
                        form_detected = detect_contact_form(BeautifulSoup(sub_text, "html.parser"))
                if all_emails and display_phone:
                    break
            except Exception:
                pass

    best_email = select_best_email(all_emails, target_url)
    source_url = ""
    if best_email:
        source_url = email_url_map.get(best_email, effective_url)
    elif display_phone:
        source_url = phone_found_url or effective_url

    if best_email:
        diagnostic = "email found"
    elif form_detected:
        diagnostic = "contact-form only"
        logger.info(f"Crawl {target_url}: contact-form only (no visible email address)")
    elif robots_disallowed_contact:
        diagnostic = "contact page disallowed by robots.txt"
        logger.info(f"Crawl {target_url}: {diagnostic}")
    else:
        diagnostic = "no email on page"
        logger.info(f"Crawl {target_url}: no email on page")

    return CrawlResult(best_email, display_phone, e164_phone, diagnostic, source_url)


# =====================================================================
# 5. Brave Search Fallbacks
# =====================================================================

def search_website_via_brave(business_name: str, city_name: str, headers: Optional[Dict[str, str]] = None) -> str:
    """
    Optional web search fallback to find business website when missing in OSM.
    Discards results on directory domains.
    Detects captchas / rate limits gracefully with polite delays.
    """
    query = f"{business_name} {city_name} official website"
    url = "https://search.brave.com/search"
    params = {"q": query}
    req_headers = headers or config.BROWSER_HEADERS

    try:
        resp = requests.get(url, params=params, headers=req_headers, timeout=8)
        if resp.status_code in (429, 403) or "captcha" in resp.text.lower() or "challenge" in resp.text.lower():
            time.sleep(1.5)
            return ""
        if resp.status_code == 200:
            links = re.findall(r'href="([^"]+)"', resp.text)
            for link in links:
                if link.startswith("http") and not is_directory_domain(link):
                    parsed_domain = clean_domain(link)
                    if parsed_domain and not any(x in parsed_domain for x in ["brave.com", "microsoft", "apple"]):
                        return link
        time.sleep(1.0)
    except Exception:
        pass
    return ""


def search_email_via_brave(
    business_name: str,
    city_name: str,
    business_website: str,
    headers: Optional[Dict[str, str]] = None
) -> str:
    """
    Search snippet email fallback.
    ONLY accepts an email if its domain matches the business website domain.
    """
    website_domain = clean_domain(business_website)
    if not website_domain or is_directory_domain(website_domain):
        return ""

    query = f'"{business_name}" "{city_name}" "@{website_domain}"'
    url = "https://search.brave.com/search"
    params = {"q": query}
    req_headers = headers or config.BROWSER_HEADERS

    try:
        resp = requests.get(url, params=params, headers=req_headers, timeout=8)
        if resp.status_code in (429, 403) or "captcha" in resp.text.lower():
            time.sleep(1.5)
            return ""
        if resp.status_code == 200:
            emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", resp.text)
            for em in emails:
                clean_em = em.strip().rstrip(".")
                if validate_email(clean_em):
                    em_domain = clean_domain(clean_em.split("@", 1)[1])
                    if em_domain == website_domain or em_domain.endswith("." + website_domain):
                        return clean_em
        time.sleep(1.0)
    except Exception:
        pass
    return ""


# =====================================================================
# 6. Geocoding & OpenStreetMap Overpass Client
# =====================================================================

_last_nominatim_call_time = 0.0

def geocode_location(area_name: str, city_name: str, user_agent: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Geocodes area and city using Nominatim with addressdetails=1.
    Derives country code (e.g. 'US', 'IN', 'GB').
    Respects OpenStreetMap's mandatory 1 request/second rate limit.
    Retries on 429/502/503/504 with exponential backoff.

    Returns:
        (latitude, longitude, country_code_upper)
    """
    global _last_nominatim_call_time

    # Rate limiting: ensure at least 1.05s has passed since last request
    now = time.time()
    elapsed = now - _last_nominatim_call_time
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)

    query_str = f"{area_name}, {city_name}" if area_name else city_name
    params = {
        "q": query_str,
        "format": "json",
        "addressdetails": 1,
        "limit": 1
    }
    headers = {"User-Agent": user_agent}

    retries = 3
    backoff = 1.5

    for attempt in range(retries):
        try:
            _last_nominatim_call_time = time.time()
            resp = requests.get(config.NOMINATIM_URL, params=params, headers=headers, timeout=12)
            if resp.status_code in (429, 502, 503, 504):
                time.sleep(backoff * (attempt + 1))
                continue
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None, None, None
            first = data[0]
            lat = float(first["lat"])
            lon = float(first["lon"])
            country_code = first.get("address", {}).get("country_code", "").upper() or None
            return lat, lon, country_code
        except Exception as e:
            if attempt == retries - 1:
                logger.error(f"Nominatim geocoding failed for {query_str}: {e}")
                return None, None, None
            time.sleep(backoff * (attempt + 1))

    return None, None, None


def validate_custom_osm_tag(tag: str) -> Tuple[bool, str]:
    """
    Validates custom OSM tag input before building Overpass QL queries.
    Rejects dangerous characters (quotes, semicolons, backslashes, braces, control chars)
    and enforces maximum length of 64 characters.
    Valid format: 'key=value' or 'key' with alphanumeric, colons, underscores, or hyphens.
    """
    if not tag or not tag.strip():
        return False, "Custom tag cannot be empty."

    raw = tag.strip()
    if len(raw) > 64:
        return False, f"Custom tag exceeds maximum length of 64 characters (got {len(raw)})."

    forbidden_chars = {'"', "'", ';', '\\', '{', '}', '(', ')', '<', '>', '\n', '\r', '\t', '`'}
    found_forbidden = [c for c in forbidden_chars if c in raw]
    if found_forbidden:
        return False, f"Custom tag contains invalid character: {found_forbidden[0]}"

    if "=" in raw:
        parts = raw.split("=", 1)
        k, v = parts[0].strip(), parts[1].strip()
        if not k or not v:
            return False, "Custom tag must be in 'key=value' format with non-empty key and value."
        if not re.match(r"^[a-zA-Z0-9_:\-]+$", k) or not re.match(r"^[a-zA-Z0-9_:\-]+$", v):
            return False, "Custom tag key and value may only contain letters, numbers, underscores, hyphens, and colons."
    else:
        if not re.match(r"^[a-zA-Z0-9_:\-]+$", raw):
            return False, "Custom tag key may only contain letters, numbers, underscores, hyphens, and colons."

    return True, ""


def format_overpass_filter(tag: str) -> str:
    """
    Formats an individual tag or compound tag expression for Overpass QL.
    Handles simple 'k=v', 'key', and compound expressions with existing brackets:
    e.g. 'leisure=sports_centre["sport"~"fitness|yoga|pilates|crossfit|gym",i]'
    """
    tag = tag.strip()
    if not tag:
        return ""
    if "[" in tag:
        bracket_idx = tag.index("[")
        base = tag[:bracket_idx].strip()
        extra = tag[bracket_idx:].strip()
        if "=" in base:
            k, v = base.split("=", 1)
            return f'["{k.strip()}"="{v.strip()}"]{extra}'
        else:
            return f'["{base.strip()}"]{extra}'
    elif "=" in tag:
        k, v = tag.split("=", 1)
        return f'["{k.strip()}"="{v.strip()}"]'
    else:
        return f'["{tag}"]'


def build_overpass_query(tags: List[str], lat: float, lon: float, radius_m: int) -> str:
    """Builds an Overpass QL query string supporting simple and compound tag clauses."""
    parts = []
    for tag in tags:
        flt = format_overpass_filter(tag)
        if flt:
            parts.append(f'node(around:{radius_m},{lat},{lon}){flt};')
            parts.append(f'way(around:{radius_m},{lat},{lon}){flt};')
    return f"[out:json][timeout:25];(" + "".join(parts) + ");out center tags;"


def query_overpass(
    tags: List[str],
    lat: float,
    lon: float,
    radius_m: int,
    user_agent: str,
    mirrors: Optional[List[str]] = None,
    default_region: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Executes Overpass query with exponential backoff (3 attempts) on 429/502/503/504
    and automatic failover across alternate OVERPASS_URLS mirrors.
    """
    query = build_overpass_query(tags, lat, lon, radius_m)
    endpoint_mirrors = mirrors or config.OVERPASS_URLS
    headers = {"User-Agent": user_agent}

    last_err: Optional[Exception] = None

    for mirror_url in endpoint_mirrors:
        for attempt in range(3):
            try:
                resp = requests.post(
                    mirror_url,
                    data={"data": query},
                    headers=headers,
                    timeout=(8, 25)
                )
                if resp.status_code in (429, 502, 503, 504):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                data = resp.json()
                elements = data.get("elements", [])
                results = []

                for el in elements:
                    tags_dict = el.get("tags", {})
                    name = tags_dict.get("name")
                    if not name:
                        continue

                    osm_type = el.get("type", "node")
                    osm_id = el.get("id", 0)
                    elem_lat = el.get("lat") or el.get("center", {}).get("lat", lat)
                    elem_lon = el.get("lon") or el.get("center", {}).get("lon", lon)

                    address = format_osm_address(tags_dict)
                    maps_url = build_google_maps_url(name, address, elem_lat, elem_lon)

                    raw_phone = (
                        tags_dict.get("phone")
                        or tags_dict.get("contact:phone")
                        or tags_dict.get("mobile")
                        or tags_dict.get("contact:mobile")
                        or ""
                    )
                    phone_disp, phone_e164 = normalize_phone(raw_phone, default_region)

                    website = (
                        tags_dict.get("website")
                        or tags_dict.get("contact:website")
                        or ""
                    )
                    if is_directory_domain(website):
                        website = ""

                    clean_email = validate_email(
                        tags_dict.get("email") or tags_dict.get("contact:email") or ""
                    )

                    results.append({
                        "osm_type": osm_type,
                        "osm_id": osm_id,
                        "latitude": elem_lat,
                        "longitude": elem_lon,
                        "business_name": name.strip(),
                        "address": address,
                        "phone": phone_disp,
                        "phone_e164": phone_e164,
                        "phone_source": "osm_tag" if phone_disp else "",
                        "website": website,
                        "maps_url": maps_url,
                        "email": clean_email,
                        "email_source": "osm_tag" if clean_email else "",
                        "source_url": "",
                    })
                return results
            except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as e:
                last_err = e
                break
            except Exception as e:
                last_err = e
                time.sleep(1.0 * (attempt + 1))

    raise RuntimeError(f"All Overpass mirrors failed. Last error: {last_err}")


# =====================================================================
# 7. ZeroBounce Email Deliverability Client
# =====================================================================

class ZeroBounceHaltException(Exception):
    """Raised when ZeroBounce encounters an invalid key, 401, or exhausted credits."""
    pass


def check_zerobounce_credits(api_key: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Queries ZeroBounce getcredits endpoint.
    Returns:
        {"success": True, "credits": int} or {"success": False, "error": str}
    """
    if not api_key:
        return {"success": False, "error": "API Key is empty."}

    req_headers = headers or config.BROWSER_HEADERS
    try:
        resp = requests.get(
            config.ZEROBOUNCE_CREDITS_URL,
            params={"api_key": api_key.strip()},
            headers=req_headers,
            timeout=10
        )
        if resp.status_code == 401 or resp.status_code == 403:
            return {"success": False, "error": f"Unauthorized (HTTP {resp.status_code}): Invalid ZeroBounce API Key."}
        if resp.status_code == 200:
            try:
                data = resp.json()
                if "error" in data:
                    return {"success": False, "error": str(data["error"])}
                # Field can be 'Credits' or 'credits'
                raw_credits = data.get("Credits", data.get("credits"))
                if raw_credits is not None:
                    credits_int = int(raw_credits)
                    return {"success": True, "credits": credits_int}
            except Exception:
                pass
        return {"success": False, "error": f"HTTP {resp.status_code}: Unable to read credits balance."}
    except Exception as e:
        return {"success": False, "error": f"Connection error: {e}"}


def verify_email_zerobounce(
    email: str,
    api_key: str,
    cache: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None
) -> Tuple[str, bool]:
    """
    Verifies email deliverability using ZeroBounce API.
    Returns:
        (status, is_cached)
    Taxonomy:
        valid (Deliverable)
        risky (catch-all)
        invalid (invalid, spamtrap, abuse, do_not_mail)
        unknown (API error)
        unverified (not checked)

    Does NOT cache 'unknown' results.
    Raises ZeroBounceHaltException on invalid key, 401, or zero credits.
    """
    if not email:
        return "unverified", False

    clean_em = email.strip().lower()

    # 1. Check local cache
    if clean_em in cache:
        cached_status = cache[clean_em].get("status", "unknown")
        if cached_status in ("valid", "risky", "invalid"):
            return cached_status, True

    if not api_key:
        return "unverified", False

    req_headers = headers or config.BROWSER_HEADERS
    params = {
        "api_key": api_key.strip(),
        "email": clean_em,
        "ip_address": ""
    }

    try:
        resp = requests.get(config.ZEROBOUNCE_API_URL, params=params, headers=req_headers, timeout=10)
        if resp.status_code == 401 or resp.status_code == 403:
            raise ZeroBounceHaltException(f"ZeroBounce returned HTTP {resp.status_code}: Invalid API Key.")

        if resp.status_code == 200:
            data = resp.json()
            if "error" in data:
                err_msg = str(data["error"]).lower()
                if "zero credits" in err_msg or "no credits" in err_msg or "invalid api key" in err_msg:
                    raise ZeroBounceHaltException(f"ZeroBounce error: {data['error']}")
                return "unknown", False

            api_status = data.get("status")
            if api_status == "valid":
                status = "valid"
            elif api_status in ("invalid", "spamtrap", "abuse", "do_not_mail"):
                status = "invalid"
            elif api_status == "catch-all":
                status = "risky"
            else:
                status = "unknown"

            # Cache ONLY reliable statuses (never cache unknown)
            if status in ("valid", "risky", "invalid"):
                cache[clean_em] = {
                    "status": status,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                }
            return status, False

        elif resp.status_code == 429:
            time.sleep(2.0)
            return "unknown", False
    except ZeroBounceHaltException:
        raise
    except Exception as e:
        logger.warning(f"ZeroBounce verification error for {clean_em}: {e}")
        return "unknown", False

    return "unknown", False


# =====================================================================
# 8. Deduplication, Storage & Formula Injection Safety
# =====================================================================

def get_lead_key(osm_type: Any, osm_id: Any) -> str:
    """Unique deduplication key based on OpenStreetMap element ID."""
    return f"{safe_clean_str(osm_type)}_{safe_clean_str(osm_id)}"


def sanitize_csv_value(val: Any) -> str:
    """
    Prevents CSV formula injection by prepending a single quote (')
    if the string value starts with =, +, -, @, \t, or \r.
    Handles None and float('nan') safely.
    """
    if val is None:
        return ""
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return ""
    s = str(val)
    if s.lower() == "nan":
        return ""
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def save_json_atomic(filepath: str, data: Any) -> None:
    """Atomically saves data to a JSON file with retry backoff for Windows file locks."""
    temp_file = filepath + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    for attempt in range(5):
        try:
            os.replace(temp_file, filepath)
            return
        except PermissionError:
            if attempt == 4:
                try:
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                    return
                except Exception:
                    pass
                raise
            time.sleep(0.05 * (attempt + 1))


def load_json(filepath: str, default: Any = None) -> Any:
    """Safely loads data from a JSON file."""
    if not os.path.exists(filepath):
        return default if default is not None else {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def migrate_lead_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes a lead record from older CSV or history format to the latest schema.
    Ensures all canonical CSV_FIELDS exist, migrates status and sources,
    safely handles NaN/None values, and computes missing maps_url.
    """
    migrated = {}
    for k in CSV_FIELDS:
        migrated[k] = safe_clean_str(record.get(k, ""))

    # Migrate status
    migrated["verification_status"] = migrate_lead_status(
        record.get("verification_status", ""),
        record.get("context_notes", ""),
        record.get("email", "")
    )

    # Migrate sources to standard machine values
    migrated["email_source"] = normalize_source_value(record.get("email_source", ""))
    migrated["phone_source"] = normalize_source_value(record.get("phone_source", ""))

    # If email exists but email_source was empty in an old file, infer from notes/status
    if migrated["email"] and not migrated["email_source"]:
        notes = safe_clean_str(record.get("context_notes")).lower()
        if "osm" in notes:
            migrated["email_source"] = "osm_tag"
        elif "crawl" in notes:
            migrated["email_source"] = "website_crawl"
        elif migrated["verification_status"] == "guessed":
            migrated["email_source"] = "guessed_domain"
        else:
            migrated["email_source"] = "website_crawl"

    if migrated["phone"] and not migrated["phone_source"]:
        migrated["phone_source"] = "osm_tag"

    # Compute missing maps_url
    if not migrated["maps_url"]:
        lat_val = record.get("latitude")
        lon_val = record.get("longitude")
        try:
            lat = float(lat_val) if lat_val not in ("", None) else None
            lon = float(lon_val) if lon_val not in ("", None) else None
        except (ValueError, TypeError):
            lat, lon = None, None
        migrated["maps_url"] = build_google_maps_url(
            business_name=migrated["business_name"],
            address_or_area=migrated["address"],
            lat=lat,
            lon=lon
        )

    return migrated


def save_csv_atomic(filepath: str, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    """Atomically writes rows to a CSV file with formula injection protection and schema resilience."""
    temp_file = filepath + ".tmp"
    with open(temp_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            migrated_row = migrate_lead_record(row) if row else {}
            sanitized = {k: sanitize_csv_value(migrated_row.get(k, "")) for k in fieldnames}
            writer.writerow(sanitized)
    for attempt in range(5):
        try:
            os.replace(temp_file, filepath)
            return
        except PermissionError:
            if attempt == 4:
                try:
                    with open(filepath, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                        writer.writeheader()
                        for row in rows:
                            migrated_row = migrate_lead_record(row) if row else {}
                            sanitized = {k: sanitize_csv_value(migrated_row.get(k, "")) for k in fieldnames}
                            writer.writerow(sanitized)
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                    return
                except Exception:
                    pass
                raise
            time.sleep(0.05 * (attempt + 1))


def migrate_lead_status(raw_status: Any, context_notes: Any = "", email: Any = "") -> str:
    """
    Migrates old legacy CSV statuses to exact taxonomy:
    Rows with no email must use 'no_email', never 'unknown'.
    'unknown' only means ZeroBounce returned no verdict.
    """
    email_clean = safe_clean_str(email)
    has_email = bool(email_clean)
    s = safe_clean_str(raw_status).lower()
    notes = safe_clean_str(context_notes).lower()

    if not has_email and s in ("", "none", "unknown", "no_email"):
        return "no_email"

    if "domain placeholder" in notes or s == "domain placeholder" or s == "guessed":
        return "guessed"
    if s in ("unverified (format valid)", "format valid", "unverified"):
        return "unverified"
    if s in ("valid", "deliverable"):
        return "valid"
    if s in ("risky", "catch-all"):
        return "risky"
    if s in ("invalid", "spamtrap"):
        return "invalid"
    if s == "unknown":
        return "unknown" if has_email else "no_email"
    if s in ("no_email", "none"):
        return "no_email"

    if not has_email:
        return "no_email"
    return "unverified" if s else "no_email"


# =====================================================================
# 9. Segmented CSV Export Handlers
# =====================================================================

def export_leads_ready_for_email(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Returns ONLY deliverable ('valid') emails.
    Deduplicates by email address so cold email tools do not email the same address twice.
    """
    ready_leads = []
    seen_emails: Set[str] = set()

    for r in rows:
        status = safe_clean_str(r.get("verification_status")).lower()
        email = safe_clean_str(r.get("email")).lower()
        if status == "valid" and email and validate_email(email):
            if email not in seen_emails:
                seen_emails.add(email)
                ready_leads.append(r)

    return ready_leads


def export_leads_unverified(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Returns leads with unverified or guessed emails."""
    return [
        r for r in rows
        if safe_clean_str(r.get("verification_status")).lower() in ("unverified", "guessed")
        and bool(safe_clean_str(r.get("email")))
    ]


def export_leads_phones(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Returns leads with valid phone numbers."""
    return [r for r in rows if bool(safe_clean_str(r.get("phone")))]


def export_leads_risky(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Returns leads with catch-all / risky emails."""
    return [
        r for r in rows
        if safe_clean_str(r.get("verification_status")).lower() == "risky"
        and bool(safe_clean_str(r.get("email")))
    ]


# =====================================================================
# 10. High-Throughput Concurrent Lead Enrichment
# =====================================================================

def enrich_single_lead(
    biz: Dict[str, Any],
    city_name: str,
    default_region: Optional[str],
    web_fallback: bool,
    include_guessed: bool,
    headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Enriches a single business lead by finding website, crawling contacts,
    and resolving email/phone and provenance.
    """
    req_headers = headers or config.BROWSER_HEADERS
    address = safe_clean_str(biz.get("address", ""))
    maps_url = safe_clean_str(biz.get("maps_url", ""))
    if not maps_url:
        lat_val = biz.get("latitude")
        lon_val = biz.get("longitude")
        try:
            lat = float(lat_val) if lat_val not in ("", None) else None
            lon = float(lon_val) if lon_val not in ("", None) else None
        except (ValueError, TypeError):
            lat, lon = None, None
        maps_url = build_google_maps_url(
            business_name=biz.get("business_name", ""),
            address_or_area=address,
            lat=lat,
            lon=lon
        )
    source_url = safe_clean_str(biz.get("source_url", ""))
    website = safe_clean_str(biz.get("website", ""))
    phone = safe_clean_str(biz.get("phone", ""))
    phone_e164 = safe_clean_str(biz.get("phone_e164", ""))
    phone_source = normalize_source_value(biz.get("phone_source", ""))
    email = safe_clean_str(biz.get("email", ""))
    email_source = normalize_source_value(biz.get("email_source", ""))

    # 1. Fallback website search via Brave if missing and toggle enabled
    if not website and web_fallback:
        found_site = search_website_via_brave(biz.get("business_name", ""), city_name, req_headers)
        if found_site:
            website = found_site

    crawl_diagnostic = ""
    # 2. Crawl website contacts if website exists
    if website and not is_directory_domain(website):
        crawl_res = crawl_website_contacts(
            website, default_region=default_region, headers=req_headers
        )
        crawled_em = crawl_res[0] if len(crawl_res) > 0 else ""
        crawled_ph = crawl_res[1] if len(crawl_res) > 1 else ""
        crawled_e164 = crawl_res[2] if len(crawl_res) > 2 else ""
        crawl_diagnostic = crawl_res[3] if len(crawl_res) > 3 else ""
        crawled_source_url = getattr(crawl_res, "source_url", "") or (crawl_res[4] if len(crawl_res) > 4 else "")

        if crawled_em and not email:
            email = crawled_em
            email_source = "website_crawl"
            source_url = crawled_source_url or website
        if crawled_ph and not phone:
            phone = crawled_ph
            phone_e164 = crawled_e164
            phone_source = "website_crawl"
            if not source_url:
                source_url = crawled_source_url or website

    # 3. Brave search snippet email fallback (only accepted if matching domain)
    if not email and website and web_fallback:
        snippet_em = search_email_via_brave(biz.get("business_name", ""), city_name, website, req_headers)
        if snippet_em:
            email = snippet_em
            email_source = "search_snippet"

    # 4. Domain placeholder guess (info@domain) - default OFF
    is_guessed = False
    if not email and website and include_guessed and not is_directory_domain(website) and not is_non_html_url(website):
        clean_dom = clean_domain(website)
        if clean_dom:
            guessed_em = f"info@{clean_dom}"
            if validate_email(guessed_em):
                email = guessed_em
                email_source = "guessed_domain"
                is_guessed = True

    # Validate final email
    if email and not validate_email(email):
        email = ""
        email_source = ""

    # Initial status: rows with no email must use 'no_email', never 'unknown'
    if email:
        initial_status = "guessed" if is_guessed else "unverified"
    else:
        initial_status = "no_email"

    # Contact method determination
    if email:
        contact_method = "email"
    elif phone:
        contact_method = "phone"
    else:
        contact_method = "none"

    return {
        "osm_type": biz.get("osm_type", "node"),
        "osm_id": biz.get("osm_id", 0),
        "latitude": biz.get("latitude", 0.0),
        "longitude": biz.get("longitude", 0.0),
        "business_name": biz.get("business_name", ""),
        "address": address,
        "email": email,
        "phone": phone,
        "phone_e164": phone_e164,
        "website": website,
        "maps_url": maps_url,
        "email_source": email_source,
        "phone_source": phone_source,
        "source_url": source_url,
        "verification_status": initial_status,
        "contact_method": contact_method,
        "crawl_diagnostic": crawl_diagnostic,
    }


def enrich_leads_concurrently(
    leads: List[Dict[str, Any]],
    city_name: str,
    default_region: Optional[str],
    web_fallback: bool,
    include_guessed: bool,
    max_workers: int = 5,
    headers: Optional[Dict[str, str]] = None,
    progress_callback: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """
    Enriches multiple business listings concurrently using ThreadPoolExecutor (max 5 workers).
    Yields or calls progress_callback after each lead completes.
    """
    results: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_lead = {
            executor.submit(
                enrich_single_lead,
                biz,
                city_name,
                default_region,
                web_fallback,
                include_guessed,
                headers
            ): biz
            for biz in leads
        }

        for idx, future in enumerate(as_completed(future_to_lead)):
            try:
                enriched = future.result()
                results.append(enriched)
                if progress_callback:
                    progress_callback(idx + 1, len(leads), enriched)
            except Exception as e:
                logger.error(f"Error enriching lead: {e}")

    return results
