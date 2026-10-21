"""
live_end_to_end_pass.py — Full live end-to-end pass:
- Austin, Texas + Dentists
- 1 area: Downtown
- 15 leads
- Website crawling ON
- Web search fallback OFF
- No ZeroBounce key
- Polite delays
"""

import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
import leadcore

def run_pass():
    city = "Austin, Texas"
    area = "Downtown"
    category = "Dentists"
    max_leads = 15
    user_email = "testbuyer@gmail.com"
    ua = f"LocalLeadsKit/{config.VERSION} (contact: {user_email})"
    
    tags = ["amenity=dentist"]
    print(f"=== Starting Live End-to-End Pass ===")
    print(f"Target: {area}, {city}")
    print(f"Category: Dentists ({tags})")
    print(f"Max leads: {max_leads}")
    print(f"Website crawling: ON | Web fallback: OFF | ZeroBounce: OFF")
    print(f"User-Agent: {ua}\n")

    # Step 1: Geocode
    print("1. Geocoding area with Nominatim (with polite delay)...")
    lat, lon, country_code = leadcore.geocode_location(area, city, ua)
    print(f"   -> Coordinates: {lat}, {lon} (Country: {country_code})")
    assert lat and lon, "Geocoding failed!"

    # Step 2: Query Overpass
    print("\n2. Querying OpenStreetMap via Overpass API...")
    raw_leads = leadcore.query_overpass(tags, lat, lon, radius_m=2500, user_agent=ua)
    total_found = len(raw_leads)
    print(f"   -> Found {total_found} business records from OSM.")

    # Slice to max_leads
    leads_to_process = raw_leads[:max_leads]

    # Step 3: Enrich with website crawling
    enriched_leads = []
    print(f"\n3. Processing & Crawling up to {len(leads_to_process)} leads with polite delays...")
    for idx, raw in enumerate(leads_to_process, 1):
        name = raw.get("business_name") or "Unknown Business"
        website = raw.get("website", "").strip()
        phone_raw = raw.get("phone", "").strip()
        email_raw = raw.get("email", "").strip()

        print(f"\n[{idx}/{len(leads_to_process)}] {name}")
        print(f"   OSM Data: Phone='{phone_raw}', Website='{website}', Email='{email_raw}'")

        time.sleep(0.5)  # Polite delay between website crawl requests
        lead = leadcore.enrich_single_lead(
            biz=raw,
            city_name=city,
            default_region=country_code,
            web_fallback=False,
            include_guessed=False
        )
        diag = lead.get('crawl_diagnostic')
        diag_str = f", CrawlDiag='{diag}'" if diag else ""
        print(f"   -> Result: Phone='{lead.get('phone')}', Email='{lead.get('email')}', Status='{lead.get('verification_status')}'{diag_str}")
        enriched_leads.append(lead)

    # Step 4: Aggregate Metrics
    print("\n" + "=" * 50)
    print("=== LIVE RUN METRICS SUMMARY ===")
    print("=" * 50)
    count_businesses = len(enriched_leads)
    count_website = sum(1 for l in enriched_leads if l["website"])
    count_email = sum(1 for l in enriched_leads if l["email"])
    count_phone = sum(1 for l in enriched_leads if l["phone"])
    
    status_counts = {}
    for l in enriched_leads:
        st = l.get("verification_status", "no_email")
        status_counts[st] = status_counts.get(st, 0) + 1

    crawl_diag_counts = {}
    for l in enriched_leads:
        if l["website"] and not l["email"]:
            d = l.get("crawl_diagnostic") or "unknown"
            crawl_diag_counts[d] = crawl_diag_counts.get(d, 0) + 1

    print(f"Total businesses found: {count_businesses}")
    print(f"Businesses with website: {count_website} ({count_website/count_businesses*100:.1f}%)")
    print(f"Businesses yielding email: {count_email} ({count_email/count_businesses*100:.1f}%)")
    print(f"Businesses yielding phone: {count_phone} ({count_phone/count_businesses*100:.1f}%)")
    print(f"Status split: {status_counts}")
    print(f"Crawl diagnostics (websites without email): {crawl_diag_counts}")

    print("\n" + "=" * 50)
    print("=== 10 SAMPLE ROWS ===")
    print("=" * 50)
    sample_leads = enriched_leads[:10]
    header = f"{'#':<3} | {'Business Name':<26} | {'Website':<30} | {'Email':<26} | {'Phone':<18} | {'Status':<10} | {'Crawl Diag':<18}"
    print(header)
    print("-" * len(header))
    for i, l in enumerate(sample_leads, 1):
        b_name = (l['business_name'][:24] + '..') if len(l['business_name']) > 26 else l['business_name']
        w_site = (l['website'][:28] + '..') if len(l['website']) > 30 else l['website']
        e_mail = (l['email'][:24] + '..') if len(l['email']) > 26 else l['email']
        phone = l['phone'] or "-"
        stat = l.get("verification_status", "no_email")
        diag = l.get("crawl_diagnostic") or "-"
        print(f"{i:<3} | {b_name:<26} | {w_site:<30} | {e_mail:<26} | {phone:<18} | {stat:<10} | {diag:<18}")

if __name__ == "__main__":
    run_pass()
