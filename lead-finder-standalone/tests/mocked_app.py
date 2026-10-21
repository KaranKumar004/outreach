"""
mocked_app.py — Streamlit test runner with mocked network calls for Playwright browser testing.

TEST HOOKS (Only in tests/mocked_app.py, never in shipped code):
- Atomic file redirection: writes to a temporary directory so demo runs never touch root files.
- LOCALLEADS_SIMULATE_FAIL: simulates an Overpass failure on an area to verify failed-area summary card.
- Deterministic pause: responds to signal files in scratch/ to pause execution mid-run for screenshots.
"""

import sys
import os
import time
import tempfile

# Add standalone folder to path
standalone_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if standalone_dir not in sys.path:
    sys.path.insert(0, standalone_dir)

import leadcore
import places

os.environ["LOCALLEADS_DEMO"] = "1"

# 1. Temp directory isolation: when LOCALLEADS_DEMO_TEMP_DIR is set, demo runs never write to real repo files
DEMO_TEMP_DIR = os.environ.get("LOCALLEADS_DEMO_TEMP_DIR")
if DEMO_TEMP_DIR:
    orig_save_json = leadcore.save_json_atomic
    orig_save_csv = leadcore.save_csv_atomic
    orig_load_json = leadcore.load_json

    def safe_demo_save_json(filepath, data):
        fn = os.path.basename(filepath)
        return orig_save_json(os.path.join(DEMO_TEMP_DIR, fn), data)

    def safe_demo_save_csv(filepath, fieldnames, rows):
        fn = os.path.basename(filepath)
        return orig_save_csv(os.path.join(DEMO_TEMP_DIR, fn), fieldnames, rows)

    def safe_demo_load_json(filepath, default=None):
        fn = os.path.basename(filepath)
        target = os.path.join(DEMO_TEMP_DIR, fn)
        if os.path.exists(target):
            return orig_load_json(target, default)
        return orig_load_json(filepath, default)

    leadcore.save_json_atomic = safe_demo_save_json
    leadcore.save_csv_atomic = safe_demo_save_csv
    leadcore.load_json = safe_demo_load_json

# 2. Nominatim Geocode Mock
leadcore.geocode_location = lambda area, city, ua: (30.2672, -97.7431, "US")

# 3. Overpass Mock with Synthetic Demo Data (.example.com domains)
DEMO_LEADS = [
    {
        "osm_type": "node", "osm_id": 901, "latitude": 30.267, "longitude": -97.743,
        "business_name": "Austin Dental Arts", "address": "100 Congress Ave, Austin",
        "phone": "(512) 555-0101", "phone_e164": "+15125550101", "phone_source": "osm_tag",
        "website": "https://austindentalarts.example.com",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=Austin+Dental+Arts%2C+100+Congress+Ave%2C+Austin",
        "email": "", "email_source": "", "source_url": ""
    },
    {
        "osm_type": "node", "osm_id": 902, "latitude": 30.268, "longitude": -97.744,
        "business_name": "Capitol Family Dental", "address": "200 E 6th St, Austin",
        "phone": "+1 512 555 0102", "phone_e164": "+15125550102", "phone_source": "osm_tag",
        "website": "https://capitoldental.example.com",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=Capitol+Family+Dental%2C+200+E+6th+St%2C+Austin",
        "email": "", "email_source": "", "source_url": ""
    },
    {
        "osm_type": "node", "osm_id": 903, "latitude": 30.269, "longitude": -97.745,
        "business_name": "Downtown Tooth Care", "address": "300 Lavaca St, Austin",
        "phone": "+1 512 555 0103", "phone_e164": "+15125550103", "phone_source": "osm_tag",
        "website": "",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=Downtown+Tooth+Care%2C+300+Lavaca+St%2C+Austin",
        "email": "", "email_source": "", "source_url": ""
    }
]

def mock_query_overpass(tags, lat, lon, rad, ua, **kw):
    if os.environ.get("LOCALLEADS_SIMULATE_FAIL") and abs(lat - 30.2500) < 0.001:
        raise RuntimeError("Overpass 504 Gateway Timeout")
    return [dict(l) for l in DEMO_LEADS]

leadcore.query_overpass = mock_query_overpass

# 4. Website Crawler Mock with Deterministic Pause Hook
scratch_dir = os.path.join(standalone_dir, "scratch")
os.makedirs(scratch_dir, exist_ok=True)
pause_signal = os.path.join(scratch_dir, "mid_run_pause.signal")
paused_ack = os.path.join(scratch_dir, "mid_run_paused.ack")
release_signal = os.path.join(scratch_dir, "mid_run_release.signal")

def mock_crawl(url, **kwargs):
    # Respond to pause signal for deterministic mid-run capture
    if os.path.exists(pause_signal):
        with open(paused_ack, "w") as f:
            f.write("paused")
        while os.path.exists(pause_signal) and not os.path.exists(release_signal):
            time.sleep(0.1)
    time.sleep(0.5)
    if "austindentalarts" in url:
        return leadcore.CrawlResult(
            "contact@austindentalarts.example.com", "+1 512 555 0101", "+15125550101", "email found", "https://austindentalarts.example.com"
        )
    return leadcore.CrawlResult("", "", "", "no email on page", "")

leadcore.crawl_website_contacts = mock_crawl
leadcore.search_website_via_brave = lambda b, c, **kw: ""
leadcore.search_email_via_brave = lambda b, c, w, **kw: ""

# 5. Neighborhoods Mock
places.load_or_fetch_neighborhoods = lambda city_dict, contact_email: [
    {"id": "1", "name": "Downtown", "type": "suburb", "latitude": 30.2672, "longitude": -97.7431},
    {"id": "2", "name": "South Congress", "type": "suburb", "latitude": 30.2500, "longitude": -97.7500}
]

import runpy
runpy.run_path(os.path.join(standalone_dir, "app.py"), run_name="__main__")
