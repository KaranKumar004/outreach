#!/usr/bin/env python3
"""
scripts/crawl_check.py — Website Crawler Diagnostic & Verification Tool.

Accepts a list of URLs via CLI or defaults to 15 representative business websites:
- 5 Austin dentists from live Overpass data
- 10 real small-business websites (WordPress, Wix, Squarespace, Cloudflare)

For each URL:
- Measures connect time (TCP/TLS) and read time separately
- Inspects redirect chain and final URL
- Reports HTTP status code
- Identifies exact exceptions (SSL, ConnectTimeout, ReadTimeout, DNS)
- Evaluates robots.txt compliance
- Extracts emails and phone numbers via leadcore extraction engine
- Compares failures against curl -I and plain urllib to isolate code vs. network issues
- Supports --json output flag for programmatic consumption

Usage:
    python scripts/crawl_check.py [url1 url2 ...] [--json]
"""

import os
import sys
import time
import json
import socket
import ssl
import subprocess
import urllib.request
from typing import Dict, List, Tuple, Optional, Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import leadcore
import config

DEFAULT_SITES = [
    # --- 5 Austin Dentists from Live Overpass ---
    {"name": "Kunik Orthodontics", "platform": "Austin Dentist (OSM)", "url": "https://www.kunikorthodontics.com/"},
    {"name": "Union Dental Salon", "platform": "Austin Dentist (OSM)", "url": "https://www.takeheartshop.com"},
    {"name": "Gordon Dental", "platform": "Austin Dentist (OSM)", "url": "https://www.drdavidgordon.com/"},
    {"name": "Downtown Dental Design", "platform": "Austin Dentist (OSM)", "url": "https://downtowndentaldesign.com/"},
    {"name": "Austin Cosmetic Dentistry", "platform": "Austin Dentist (OSM)", "url": "https://austincosmetic.com"},

    # --- 10 Small Businesses (WordPress, Wix, Squarespace, Cloudflare) ---
    {"name": "Austin Dental Spa", "platform": "WordPress", "url": "https://austindentalspa.com"},
    {"name": "Picnik Restaurants", "platform": "WordPress", "url": "https://www.picnikrestaurants.com"},
    {"name": "Cedar Park Dental", "platform": "WordPress", "url": "https://www.cedarparkdental.com"},
    {"name": "Cute Nail Studio", "platform": "Wix", "url": "https://www.cutenailstudio.com"},
    {"name": "Robbie Price Therapy", "platform": "Squarespace", "url": "https://robbiepricetherapy.com"},
    {"name": "Alex Hartley Music", "platform": "Squarespace", "url": "https://www.alexhartleymusic.com"},
    {"name": "Austin Navrkal Art", "platform": "Squarespace", "url": "https://austinnavrkalart.com"},
    {"name": "Austin Pets Alive", "platform": "Cloudflare", "url": "https://austinpetsalive.org"},
    {"name": "Kerbey Lane Cafe", "platform": "Cloudflare", "url": "https://www.kerbeylanecafe.com"},
    {"name": "Torchy's Tacos", "platform": "Cloudflare", "url": "https://www.torchystacos.com"},
]


def measure_connect_time(target_url: str, timeout: float = 8.0) -> Tuple[float, Optional[str]]:
    """Measures low-level TCP + TLS handshake connect time."""
    parsed = urlparse(target_url if target_url.startswith(("http://", "https://")) else f"https://{target_url}")
    host = parsed.netloc or parsed.path
    port = 443 if parsed.scheme == "https" else 80
    if ":" in host:
        host, p_str = host.split(":", 1)
        port = int(p_str)

    start = time.perf_counter()
    try:
        addr_info = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        family, socktype, proto, canonname, sockaddr = addr_info[0]
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        sock.connect(sockaddr)
        if parsed.scheme == "https":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)
        elapsed = time.perf_counter() - start
        sock.close()
        return elapsed, None
    except socket.gaierror as e:
        return time.perf_counter() - start, f"DNS Error ({e})"
    except socket.timeout:
        return time.perf_counter() - start, "ConnectTimeout (TCP/TLS handshake timed out)"
    except ssl.SSLError as e:
        return time.perf_counter() - start, f"SSLError ({e})"
    except Exception as e:
        return time.perf_counter() - start, f"{e.__class__.__name__} ({e})"


def run_curl_diagnostic(url: str) -> str:
    """Runs curl -I to test response headers from the operating system shell."""
    try:
        res = subprocess.run(
            ["curl.exe", "-I", "-sL", "--connect-timeout", "6", "--max-time", "12", url],
            capture_output=True, text=True, timeout=14
        )
        if res.returncode == 0:
            status_lines = [line.strip() for line in res.stdout.splitlines() if line.startswith("HTTP/")]
            return f"curl OK: {' -> '.join(status_lines)}"
        return f"curl failed (exit {res.returncode}): {res.stderr.strip()[:100]}"
    except Exception as e:
        return f"curl error: {e}"


def run_urllib_diagnostic(url: str) -> str:
    """Runs plain urllib request to isolate requests-library specific behaviors."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": config.BROWSER_HEADERS["User-Agent"]})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return f"urllib OK (HTTP {resp.status}, final: {resp.url})"
    except urllib.error.HTTPError as e:
        return f"urllib HTTPError {e.code}"
    except urllib.error.URLError as e:
        return f"urllib URLError: {e.reason}"
    except Exception as e:
        return f"urllib exception: {e.__class__.__name__}"


def check_single_url(target_url: str, site_name: str = "", platform: str = "") -> Dict[str, Any]:
    """Performs full diagnostic crawl check on a single website."""
    norm_url = target_url if target_url.startswith(("http://", "https://")) else f"https://{target_url}"

    result: Dict[str, Any] = {
        "name": site_name,
        "platform": platform,
        "input_url": target_url,
        "final_url": "",
        "redirect_chain": [],
        "cross_domain_redirect": False,
        "http_status": None,
        "connect_time_sec": None,
        "read_time_sec": None,
        "exception_type": None,
        "exception_message": None,
        "robots_allowed": True,
        "contact_pages_found": [],
        "emails_found": [],
        "phone_display": "",
        "phone_e164": "",
        "crawl_diagnostic": "",
        "diagnostic_curl": None,
        "diagnostic_urllib": None,
    }

    # Early exit for non-HTML files (.pdf, .docx, etc.)
    if leadcore.is_non_html_url(norm_url):
        result["crawl_diagnostic"] = "linked file, not a website"
        return result

    # 1. Measure TCP/TLS connect time
    conn_time, conn_err = measure_connect_time(norm_url, timeout=8.0)
    result["connect_time_sec"] = round(conn_time, 3)
    if conn_err:
        result["exception_type"] = "ConnectError"
        result["exception_message"] = conn_err

    # 2. Perform HTTP GET with redirect tracking
    session = requests.Session()
    session.max_redirects = 5

    t_get_start = time.perf_counter()
    try:
        resp = session.get(norm_url, headers=config.BROWSER_HEADERS, timeout=(8.0, 15.0), verify=True, stream=True)
        t_headers = time.perf_counter()
        
        # Read body
        body = resp.content
        t_body = time.perf_counter()

        result["read_time_sec"] = round(t_body - t_headers, 3)
        result["http_status"] = resp.status_code
        result["final_url"] = resp.url
        result["redirect_chain"] = [r.url for r in resp.history]

        # Cross-domain check
        orig_reg = leadcore.get_registrable_domain(norm_url)
        final_reg = leadcore.get_registrable_domain(resp.url)
        if orig_reg and final_reg and orig_reg != final_reg:
            result["cross_domain_redirect"] = True
            result["crawl_diagnostic"] = f"redirected to external domain: {leadcore.clean_domain(resp.url)}"

        if resp.status_code == 200 and not result["cross_domain_redirect"]:
            result["exception_type"] = None
            result["exception_message"] = None
            # Extract homepage contacts
            emails, ph_disp, ph_e164, subpages = leadcore.extract_contacts_from_html(
                resp.text, resp.url, default_region="US"
            )
            result["contact_pages_found"] = subpages
            result["emails_found"] = emails
            result["phone_display"] = ph_disp
            result["phone_e164"] = ph_e164

            # Subpage contact checking with robots.txt
            if (not emails or not ph_disp) and subpages:
                for sub in subpages:
                    allowed = leadcore.is_path_allowed_by_robots(sub, config.BROWSER_HEADERS["User-Agent"])
                    if not allowed:
                        result["robots_allowed"] = False
                        continue
                    try:
                        sub_r = session.get(sub, headers=config.BROWSER_HEADERS, timeout=(5.0, 10.0), verify=True)
                        if sub_r.status_code == 200:
                            s_em, s_ph, s_e164, _ = leadcore.extract_contacts_from_html(sub_r.text, sub, default_region="US")
                            for em in s_em:
                                if em not in result["emails_found"]:
                                    result["emails_found"].append(em)
                            if s_ph and not result["phone_display"]:
                                result["phone_display"] = s_ph
                                result["phone_e164"] = s_e164
                    except Exception:
                        pass

            # Diagnostic verdict
            best_em = leadcore.select_best_email(result["emails_found"], norm_url)
            if best_em:
                result["crawl_diagnostic"] = "email found"
            elif leadcore.detect_contact_form(BeautifulSoup(resp.text, "html.parser")):
                result["crawl_diagnostic"] = "contact-form only"
            elif not result["robots_allowed"]:
                result["crawl_diagnostic"] = "contact page disallowed by robots.txt"
            else:
                result["crawl_diagnostic"] = "no email on page"

        elif resp.status_code != 200:
            result["crawl_diagnostic"] = f"fetch failed (HTTP {resp.status_code})"

    except requests.exceptions.SSLError as err:
        result["exception_type"] = "SSLError"
        result["exception_message"] = str(err)[:120]
        result["crawl_diagnostic"] = "fetch failed (SSL error)"
    except requests.exceptions.ConnectTimeout as err:
        result["exception_type"] = "ConnectTimeout"
        result["exception_message"] = str(err)[:120]
        result["crawl_diagnostic"] = "fetch failed (connect timeout)"
    except requests.exceptions.ReadTimeout as err:
        result["exception_type"] = "ReadTimeout"
        result["exception_message"] = str(err)[:120]
        result["crawl_diagnostic"] = "fetch failed (read timeout)"
    except requests.exceptions.ConnectionError as err:
        result["exception_type"] = "ConnectionError"
        result["exception_message"] = str(err)[:120]
        result["crawl_diagnostic"] = "fetch failed (connection/DNS error)"
    except Exception as err:
        result["exception_type"] = err.__class__.__name__
        result["exception_message"] = str(err)[:120]
        result["crawl_diagnostic"] = "fetch failed"

    # If fetch failed or had exception, run diagnostics to compare with curl and urllib
    if result["exception_type"] or (result["http_status"] and result["http_status"] >= 400):
        result["diagnostic_curl"] = run_curl_diagnostic(norm_url)
        result["diagnostic_urllib"] = run_urllib_diagnostic(norm_url)

    return result


def main():
    args = sys.argv[1:]
    json_mode = "--json" in args
    cli_urls = [a for a in args if not a.startswith("--")]

    if cli_urls:
        sites_to_check = [{"name": f"Target {i+1}", "platform": "Custom", "url": u} for i, u in enumerate(cli_urls)]
    else:
        sites_to_check = DEFAULT_SITES

    if not json_mode:
        print("=" * 80)
        print("  LocalLeads Kit — Website Crawler Diagnostic & Verification Tool")
        print(f"  Testing {len(sites_to_check)} websites (Connect: 8s, Read: 15s, Max Redirects: 5)")
        print("=" * 80)
        print()

    results = []
    for idx, site in enumerate(sites_to_check):
        if not json_mode:
            print(f"[{idx+1:02d}/{len(sites_to_check):02d}] Probing: {site['name']} ({site['url']})...", flush=True)
        res = check_single_url(site["url"], site["name"], site.get("platform", ""))
        results.append(res)
        if not json_mode:
            status_str = f"HTTP {res['http_status']}" if res['http_status'] else f"ERROR ({res['exception_type']})"
            times_str = f"conn={res['connect_time_sec']}s, read={res['read_time_sec']}s" if res['read_time_sec'] is not None else f"conn={res['connect_time_sec']}s"
            contacts_str = f"Emails: {res['emails_found'] or 'None'} | Phone: {res['phone_display'] or 'None'}"
            print(f"       -> Result: {status_str} [{times_str}]")
            print(f"          Diagnostic: {res['crawl_diagnostic']}")
            print(f"          Contacts:   {contacts_str}")
            if res.get("cross_domain_redirect"):
                print(f"          WARNING:    Redirected across registrable domain to {res['final_url']}")
            if res.get("diagnostic_curl"):
                print(f"          curl test:  {res['diagnostic_curl']}")
                print(f"          urllib test:{res['diagnostic_urllib']}")
            print()

    if json_mode:
        print(json.dumps(results, indent=2))
    else:
        print("=" * 80)
        print("SUMMARY TABLE:")
        print(f"{'#':<3} {'Business Name':<24} {'Platform':<20} {'Status':<10} {'Email':<25} {'Phone':<18}")
        print("-" * 105)
        for i, r in enumerate(results):
            em_disp = r['emails_found'][0] if r['emails_found'] else "-"
            ph_disp = r['phone_display'] or "-"
            stat_disp = str(r['http_status']) if r['http_status'] else (r['exception_type'] or "Error")
            print(f"{i+1:<3} {r['name'][:23]:<24} {r['platform'][:19]:<20} {stat_disp:<10} {em_disp[:24]:<25} {ph_disp[:17]:<18}")
        print("=" * 80)


if __name__ == "__main__":
    main()
