"""
scripts/yield_benchmark.py — Development Benchmark Tool for Lead Yield & Recall.

Evaluates recall and crawl diagnostics across representative global cities and categories.
Features:
- Sequential execution with polite delays (1.5s) between network requests
- Full robots.txt compliance via leadcore
- Disk caching for Overpass API responses in scratch/overpass_benchmark_cache/
- CLI argument --email and env var LOCALLEADS_CONTACT_EMAIL
- Exports detailed summary metrics to JSON and CSV
- Strictly excluded from commercial release ZIP
"""

import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True, encoding="utf-8")

import time
import json
import csv
import hashlib
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
import leadcore

DEFAULT_LOCATIONS = [
    {"name": "Austin TX", "country_code": "US", "lat": 30.2672, "lon": -97.7431},
    {"name": "London UK", "country_code": "GB", "lat": 51.5074, "lon": -0.1278},
    {"name": "Sydney AU", "country_code": "AU", "lat": -33.8688, "lon": 151.2093},
    {"name": "Toronto CA", "country_code": "CA", "lat": 43.6532, "lon": -79.3832},
    {"name": "Bengaluru (Banaswadi)", "country_code": "IN", "lat": 13.0142, "lon": 77.6519},
    {"name": "Bengaluru (Indiranagar)", "country_code": "IN", "lat": 12.9784, "lon": 77.6408},
    {"name": "Mumbai", "country_code": "IN", "lat": 19.0760, "lon": 72.8777},
]

DEFAULT_CATEGORIES = [
    "Clinic / Doctor / Dental",
    "Gym / Fitness / Yoga",
    "Salon / Hairdresser / Spa",
]


def get_cache_path(cache_dir: str, city_name: str, category: str, radius: int) -> str:
    key = f"{city_name}_{category}_{radius}"
    h = hashlib.md5(key.encode("utf-8")).hexdigest()[:10]
    safe_city = "".join(c if c.isalnum() else "_" for c in city_name)
    safe_cat = "".join(c if c.isalnum() else "_" for c in category)
    return os.path.join(cache_dir, f"{safe_city}_{safe_cat}_{h}.json")


def run_benchmark(
    contact_email: str,
    radius: int = 2500,
    cap: int = 30,
    quick: bool = False,
    output_dir: str = "scratch"
) -> Dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    cache_dir = os.path.join(output_dir, "overpass_benchmark_cache")
    os.makedirs(cache_dir, exist_ok=True)

    locations = DEFAULT_LOCATIONS[:1] if quick else DEFAULT_LOCATIONS
    categories = DEFAULT_CATEGORIES[:1] if quick else DEFAULT_CATEGORIES
    cap = 5 if quick else cap

    user_agent = f"LocalLeadsKit/{config.VERSION} (contact: {contact_email})"
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    results = []

    print("=" * 80)
    print(f"LocalLeads Kit Yield Benchmark — v{config.VERSION}")
    print(f"Contact Email: {contact_email}")
    print(f"Sweep Radius: {radius}m | Cap per Target: {cap}")
    print(f"Locations: {len(locations)} | Categories: {len(categories)}")
    print("=" * 80)

    for loc in locations:
        for cat in categories:
            print(f"\nEvaluating: {loc['name']} | Category: {cat}")
            cache_file = get_cache_path(cache_dir, loc["name"], cat, radius)
            raw_leads = []

            # 1. Overpass fetch (cached to prevent hammering public mirrors)
            if os.path.exists(cache_file):
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        raw_leads = json.load(f)
                    print(f"  [Overpass] Loaded {len(raw_leads)} raw nodes/ways from disk cache.")
                except Exception:
                    raw_leads = []

            if not raw_leads:
                tags = config.BUSINESS_TAG_MAP.get(cat, [])
                print(f"  [Overpass] Querying live Overpass API ({len(tags)} tag clauses)...")
                try:
                    raw_leads = leadcore.query_overpass(
                        tags=tags,
                        lat=loc["lat"],
                        lon=loc["lon"],
                        radius_m=radius,
                        user_agent=user_agent,
                        default_region=loc["country_code"]
                    )
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(raw_leads, f, indent=2)
                    print(f"  [Overpass] Found {len(raw_leads)} listings (cached).")
                except Exception as e:
                    print(f"  [Overpass ERROR] Query failed: {e}")
                    raw_leads = []
                time.sleep(1.5)

            # Seeded random sampling for reproducible recall benchmarking
            import random
            rng = random.Random(42)
            if len(raw_leads) > cap:
                leads_to_eval = rng.sample(raw_leads, cap)
            else:
                leads_to_eval = list(raw_leads)

            # 2. Sequential lead enrichment & website crawl
            diag_counts = {
                "ok": 0,
                "fetch failed": 0,
                "blocked": 0,
                "contact-form only": 0,
                "no email on page": 0,
                "robots disallowed": 0,
                "no website": 0,
                "other": 0,
            }
            osm_emails = 0
            crawled_emails = 0
            osm_phones = 0
            crawled_phones = 0
            websites_count = 0

            for idx, biz in enumerate(leads_to_eval):
                site = biz.get("website", "")
                if site:
                    websites_count += 1

                enriched = leadcore.enrich_single_lead(
                    biz=biz,
                    city_name=loc["name"],
                    default_region=loc["country_code"],
                    web_fallback=False,
                    include_guessed=False,
                    headers=headers
                )

                em = enriched.get("email", "")
                em_src = enriched.get("email_source", "")
                ph = enriched.get("phone", "")
                ph_src = enriched.get("phone_source", "")
                diag = enriched.get("crawl_diagnostic", "")

                if em:
                    if em_src == "osm_tag":
                        osm_emails += 1
                    elif em_src == "website_crawl":
                        crawled_emails += 1

                if ph:
                    if ph_src == "osm_tag":
                        osm_phones += 1
                    elif ph_src == "website_crawl":
                        crawled_phones += 1

                # Tally diagnostics
                if not site:
                    diag_counts["no website"] += 1
                elif diag == "email found":
                    diag_counts["ok"] += 1
                elif "fetch failed" in diag:
                    diag_counts["fetch failed"] += 1
                elif "blocked" in diag:
                    diag_counts["blocked"] += 1
                elif "contact-form only" in diag:
                    diag_counts["contact-form only"] += 1
                elif "no email" in diag:
                    diag_counts["no email on page"] += 1
                elif "robots" in diag:
                    diag_counts["robots disallowed"] += 1
                else:
                    diag_counts["other"] += 1

                # Polite delay between website crawls
                if site:
                    time.sleep(1.5)

            n = len(leads_to_eval)
            row_summary = {
                "timestamp": timestamp,
                "version": config.VERSION,
                "location": loc["name"],
                "country": loc["country_code"],
                "category": cat,
                "radius_m": radius,
                "total_overpass_found": len(raw_leads),
                "evaluated_n": n,
                "websites_count": websites_count,
                "website_pct": round(websites_count / n * 100, 1) if n else 0.0,
                "osm_emails": osm_emails,
                "crawled_emails": crawled_emails,
                "total_emails": osm_emails + crawled_emails,
                "email_yield_pct": round((osm_emails + crawled_emails) / n * 100, 1) if n else 0.0,
                "osm_phones": osm_phones,
                "crawled_phones": crawled_phones,
                "total_phones": osm_phones + crawled_phones,
                "phone_yield_pct": round((osm_phones + crawled_phones) / n * 100, 1) if n else 0.0,
                "diag_email_found": diag_counts["ok"],
                "diag_no_email": diag_counts["no email on page"],
                "diag_contact_form": diag_counts["contact-form only"],
                "diag_fetch_failed": diag_counts["fetch failed"],
                "diag_blocked": diag_counts["blocked"],
                "diag_robots_disallowed": diag_counts["robots disallowed"],
                "diag_no_website": diag_counts["no website"],
            }
            results.append(row_summary)

            print(f"  Found: {len(raw_leads)} | Evaluated: {n} | Websites: {websites_count}/{n} ({row_summary['website_pct']}%)")
            print(f"  Emails: {row_summary['total_emails']}/{n} ({row_summary['email_yield_pct']}%) [OSM: {osm_emails}, Crawled: {crawled_emails}]")
            print(f"  Phones: {row_summary['total_phones']}/{n} ({row_summary['phone_yield_pct']}%) [OSM: {osm_phones}, Crawled: {crawled_phones}]")
            print(f"  Diagnostics: {diag_counts}")

    # Write output JSON & CSV
    json_path = os.path.join(output_dir, f"benchmark_{timestamp}.json")
    csv_path = os.path.join(output_dir, f"benchmark_{timestamp}.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    if results:
        fieldnames = list(results[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

    print("\n" + "=" * 80)
    print(f"Benchmark Complete! Reports written to:")
    print(f"  JSON: {json_path}")
    print(f"  CSV:  {csv_path}")
    print("=" * 80)

    return {"json_path": json_path, "csv_path": csv_path, "results": results}


def main():
    parser = argparse.ArgumentParser(description="LocalLeads Kit Yield & Recall Benchmark")
    parser.add_argument("--email", default=os.getenv("LOCALLEADS_CONTACT_EMAIL", config.SUPPORT_EMAIL),
                        help="Contact email for User-Agent compliance")
    parser.add_argument("--radius", type=int, default=config.DEFAULT_RADIUS_METERS,
                        help="Search radius in meters (default 2500)")
    parser.add_argument("--cap", type=int, default=30,
                        help="Maximum leads to evaluate per target (default 30)")
    parser.add_argument("--quick", action="store_true",
                        help="Quick test run with 1 location and 5 leads")
    parser.add_argument("--output", default="scratch",
                        help="Output directory for benchmark results")

    args = parser.parse_args()
    run_benchmark(
        contact_email=args.email,
        radius=args.radius,
        cap=args.cap,
        quick=args.quick,
        output_dir=args.output
    )


if __name__ == "__main__":
    main()
