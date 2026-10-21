"""
scripts/run_live_austin.py — Run one full live end-to-end pass with website crawling ON,
web search fallback OFF, and no ZeroBounce key.
Parameters:
- City: Austin, Texas
- Area: Downtown
- Category: amenity=dentist
- Radius: 2500m
- Limit: 15 leads
- Fallback: OFF
- ZeroBounce: None
- Polite delays: True
"""

import os
import sys
import json
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import leadcore

def run_pass():
    city = "Austin, Texas"
    area = "Downtown"
    category_tags = ["amenity=dentist"]
    radius = 2500
    limit = 15
    user_email = "supportlocalleadskit@gmail.com"
    ua = f"LocalLeadsKit/1.0.1 (contact: {user_email})"

    print("================================================================================")
    print("           LIVE END-TO-END PASS: AUSTIN DENTISTS (15 LEADS)                     ")
    print("================================================================================")
    print(f"City:                 {city}")
    print(f"Area:                 {area}")
    print(f"Category Tags:        {category_tags}")
    print(f"Search Radius:        {radius} m")
    print(f"Lead Limit:           {limit}")
    print(f"Website Crawling:     ON")
    print(f"Web Search Fallback:  OFF")
    print(f"ZeroBounce Key:       None")
    print(f"User-Agent:           {ua}")
    print("--------------------------------------------------------------------------------\n")

    # 1. Geocode
    print(f"[1/4] Geocoding '{area}, {city}' via Nominatim...")
    lat, lon, country_code = None, None, None
    for attempt in range(3):
        try:
            lat, lon, country_code = leadcore.geocode_location(area, city, ua)
            if lat is not None and lon is not None:
                break
        except Exception as ge:
            print(f"      Attempt {attempt+1} failed: {ge}")
        time.sleep(2.0)

    if lat is None or lon is None:
        print("[ERROR] Geocoding failed!")
        return
    print(f"      Coordinates: ({lat:.4f}, {lon:.4f}), Country: {country_code}")
    time.sleep(1.0) # Polite delay

    # 2. Query Overpass
    print(f"[2/4] Querying OpenStreetMap via Overpass API (radius {radius}m)...")
    raw_listings = leadcore.query_overpass(category_tags, lat, lon, radius, ua, default_region=country_code)
    total_found = len(raw_listings)
    print(f"      Found {total_found} listings in OpenStreetMap.")

    # Deduplicate & cap to limit
    unique_listings = []
    seen_keys = set()
    for item in raw_listings:
        k = leadcore.get_lead_key(item["osm_type"], item["osm_id"])
        if k not in seen_keys:
            seen_keys.add(k)
            unique_listings.append(item)

    selected_leads = unique_listings[:limit]
    print(f"      Selected {len(selected_leads)} leads for enrichment.\n")

    # Count initial OSM data
    initial_websites = sum(1 for l in selected_leads if (l.get("website") or "").strip())
    initial_osm_emails = sum(1 for l in selected_leads if (l.get("email") or "").strip())
    initial_osm_phones = sum(1 for l in selected_leads if (l.get("phone") or "").strip())

    print(f"[3/4] Enriching {len(selected_leads)} leads (Crawling websites concurrently, max 5 workers)...")
    def on_progress(idx, total, enriched_lead):
        b = enriched_lead['business_name']
        em = enriched_lead.get('email') or 'no_email'
        ph = enriched_lead.get('phone') or 'no_phone'
        em_src = enriched_lead.get('email_source') or 'N/A'
        ph_src = enriched_lead.get('phone_source') or 'N/A'
        print(f"      [{idx:02d}/{total:02d}] {b[:30]:<30} | {em:<32} ({em_src}) | {ph:<16} ({ph_src})")

    enriched = leadcore.enrich_leads_concurrently(
        selected_leads,
        city_name=city,
        default_region=country_code,
        web_fallback=False,
        include_guessed=False,
        max_workers=5,
        progress_callback=on_progress
    )

    # 4. Metrics & Breakdown
    total_analyzed = len(enriched)
    has_website_count = sum(1 for l in enriched if (l.get("website") or "").strip())
    
    # Email breakdown
    emails_total = sum(1 for l in enriched if (l.get("email") or "").strip())
    emails_osm = sum(1 for l in enriched if (l.get("email") or "").strip() and "osm" in (l.get("email_source") or "").lower())
    emails_crawl = sum(1 for l in enriched if (l.get("email") or "").strip() and "crawl" in (l.get("email_source") or "").lower())
    
    # Phone breakdown
    phones_total = sum(1 for l in enriched if (l.get("phone") or "").strip())
    phones_osm = sum(1 for l in enriched if (l.get("phone") or "").strip() and "osm" in (l.get("phone_source") or "").lower())
    phones_crawl = sum(1 for l in enriched if (l.get("phone") or "").strip() and "crawl" in (l.get("phone_source") or "").lower())

    # Status split
    status_counts = {}
    for l in enriched:
        st = l.get("verification_status") or ("unverified" if l.get("email") else "no_email")
        status_counts[st] = status_counts.get(st, 0) + 1

    print("\n================================================================================")
    print("                               METRICS SUMMARY                                  ")
    print("================================================================================")
    print(f"Total businesses found in OSM:       {total_found}")
    print(f"Businesses analyzed (capped):        {total_analyzed}")
    print(f"Businesses with a website:           {has_website_count} / {total_analyzed} ({has_website_count/total_analyzed*100:.1f}%)")
    print(f"Total leads yielding an EMAIL:       {emails_total} / {total_analyzed} ({emails_total/total_analyzed*100:.1f}%)")
    print(f"  - From OSM tag:                    {emails_osm}")
    print(f"  - From Website crawl:              {emails_crawl}")
    print(f"Total leads yielding a PHONE:        {phones_total} / {total_analyzed} ({phones_total/total_analyzed*100:.1f}%)")
    print(f"  - From OSM tag:                    {phones_osm}")
    print(f"  - From Website crawl:              {phones_crawl}")
    print("\nStatus split:")
    for status, count in sorted(status_counts.items()):
        print(f"  - {status:<15}: {count:2d} ({count/total_analyzed*100:.1f}%)")
    print("--------------------------------------------------------------------------------\n")

    print("================================================================================")
    print("                        SAMPLE ROWS (FIRST 10 LEADS)                            ")
    print("================================================================================")
    for i, l in enumerate(enriched[:10], 1):
        name = l.get("business_name", "N/A")
        web = l.get("website") or "None"
        em = l.get("email") or "None"
        ph = l.get("phone") or "None"
        status = l.get("verification_status") or ("unverified" if l.get("email") else "no_email")
        em_src = l.get("email_source") or "-"
        ph_src = l.get("phone_source") or "-"
        diag = l.get("crawl_diagnostics") or "-"

        print(f"Row {i:02d}:")
        print(f"  Business:  {name}")
        print(f"  Website:   {web}")
        print(f"  Email:     {em} (Source: {em_src})")
        print(f"  Phone:     {ph} (Source: {ph_src})")
        print(f"  Status:    {status}")
        if diag != "-":
            print(f"  Crawl Log: {diag}")
        print()

    # Save results as JSON artifact for inspection
    out_path = os.path.join(os.path.dirname(__file__), "live_austin_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2)
    print(f"Detailed results saved to {out_path}")

if __name__ == "__main__":
    run_pass()
