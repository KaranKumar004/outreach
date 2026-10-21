"""
live_quick_test.py — Verify live Nominatim and Overpass query with polite rate limits.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import leadcore

def run_live_quick_test():
    city = "Austin, Texas"
    area = "Downtown"
    user_email = "testrunner@gmail.com"
    ua = f"LocalLeadsKit/1.0.1 (contact: {user_email})"
    
    print(f"1. Testing live Nominatim geocoding for '{area}, {city}'...")
    lat, lon, country_code = leadcore.geocode_location(area, city, ua)
    print(f"   -> Result: lat={lat}, lon={lon}, country_code={country_code}")
    assert lat is not None and lon is not None, "Live Nominatim geocoding failed!"
    assert country_code == "US", f"Expected US country code, got {country_code}"
    
    print(f"2. Testing live Overpass query for amenity=dentist near {lat},{lon} (radius 1000m)...")
    tags = ["amenity=dentist"]
    leads = leadcore.query_overpass(tags, lat, lon, radius_m=1000, user_agent=ua)
    print(f"   -> Overpass returned {len(leads)} raw leads.")
    assert len(leads) > 0, "Overpass returned 0 leads!"
    
    # Check structure of first lead
    lead = leads[0]
    print(f"   -> Sample lead: {lead.get('business_name')} | Phone: {lead.get('phone')} | Website: {lead.get('website')}")
    assert "osm_id" in lead and "osm_type" in lead, "Lead missing OSM identifiers"
    
    print("LIVE QUICK TEST PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_live_quick_test()
