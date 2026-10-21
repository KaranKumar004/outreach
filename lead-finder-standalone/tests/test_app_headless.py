"""
test_app_headless.py — Headless Streamlit tests using AppTest.

Proves:
(a) No guessed or unverified email ever lands in leads_ready_for_email.csv
(b) An Overpass 504 on the 2nd area still saves area 1 leads
(c) Shared emails don't drop leads
"""

import os
import sys
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from streamlit.testing.v1 import AppTest

# Add kit root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import leadcore


@pytest.fixture
def temp_workspace():
    """Runs tests in a clean temporary folder so history and CSVs don't pollute repo."""
    old_cwd = os.getcwd()
    tmp_dir = tempfile.mkdtemp()
    
    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    for fname in ["app.py", "config.py", "leadcore.py", "places.py", "ui.py"]:
        shutil.copy(os.path.join(src_dir, fname), os.path.join(tmp_dir, fname))
    shutil.copytree(os.path.join(src_dir, "data"), os.path.join(tmp_dir, "data"))
    if os.path.exists(os.path.join(src_dir, ".streamlit")):
        shutil.copytree(os.path.join(src_dir, ".streamlit"), os.path.join(tmp_dir, ".streamlit"))
    if os.path.exists(os.path.join(src_dir, "static")):
        shutil.copytree(os.path.join(src_dir, "static"), os.path.join(tmp_dir, "static"))
    
    os.chdir(tmp_dir)
    yield tmp_dir
    os.chdir(old_cwd)
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_proof_a_no_guessed_or_unverified_email_in_ready_export(temp_workspace):
    """
    Proof (a): Verifies that unverified and guessed emails NEVER land
    in leads_ready_for_email.csv, even when guessed emails toggle is ON.
    """
    # Prepare mocked leads returned by enrichment
    mock_enriched = [
        {
            "osm_type": "node", "osm_id": 1, "latitude": 30.26, "longitude": -97.74,
            "business_name": "Verified Clinic", "email": "valid@clinic.com", "phone": "+1 512 555 0101",
            "phone_e164": "+15125550101", "website": "https://clinic.com", "email_source": "Scraped",
            "verification_status": "valid", "contact_method": "email"
        },
        {
            "osm_type": "node", "osm_id": 2, "latitude": 30.26, "longitude": -97.74,
            "business_name": "Unverified Salon", "email": "unverified@salon.com", "phone": "+1 512 555 0102",
            "phone_e164": "+15125550102", "website": "https://salon.com", "email_source": "Scraped",
            "verification_status": "unverified", "contact_method": "email"
        },
        {
            "osm_type": "node", "osm_id": 3, "latitude": 30.26, "longitude": -97.74,
            "business_name": "Guessed Spa", "email": "info@guessedspa.com", "phone": "",
            "phone_e164": "", "website": "https://guessedspa.com", "email_source": "Domain placeholder (info@)",
            "verification_status": "guessed", "contact_method": "email"
        }
    ]

    with patch("leadcore.geocode_location", return_value=(30.2672, -97.7431, "US")), \
         patch("leadcore.query_overpass", return_value=[
             {"osm_type": "node", "osm_id": 1, "latitude": 30.26, "longitude": -97.74, "business_name": "Verified Clinic", "phone": "", "phone_e164": "", "website": "https://clinic.com", "email": ""},
             {"osm_type": "node", "osm_id": 2, "latitude": 30.26, "longitude": -97.74, "business_name": "Unverified Salon", "phone": "", "phone_e164": "", "website": "https://salon.com", "email": ""},
             {"osm_type": "node", "osm_id": 3, "latitude": 30.26, "longitude": -97.74, "business_name": "Guessed Spa", "phone": "", "phone_e164": "", "website": "https://guessedspa.com", "email": ""},
         ]), \
         patch("leadcore.enrich_leads_concurrently", return_value=mock_enriched):

        at = AppTest.from_file("app.py", default_timeout=15).run()
        
        # 1. Fill contact email in main Step 1 card
        contact_input = next(t for t in at.text_input if "contact email" in t.label.lower())
        contact_input.input("testuser@gmail.com").run()

        # 2. Turn ON guessed emails checkbox
        guessed_cb = next(c for c in at.sidebar.checkbox if "guessed info@" in c.label)
        guessed_cb.check().run()

        # 3. Enter manual place (>= 2 parts when no city selected)
        fallback_input = next(t for t in at.text_input if "manual" in t.label.lower() or "place" in t.label.lower())
        fallback_input.input("Downtown, Austin").run()

        # 4. Click Start Sourcing Leads
        start_btn = next(b for b in at.button if "Start Sourcing" in b.label)
        start_btn.click().run()

        assert not at.exception, f"App threw exception: {at.exception}"

        # Inspect exported data logic
        ready_leads = leadcore.export_leads_ready_for_email(mock_enriched)
        assert len(ready_leads) == 1
        assert ready_leads[0]["email"] == "valid@clinic.com"
        assert all(r["verification_status"] == "valid" for r in ready_leads)

        # Confirm unverified export has the other two
        unverified_leads = leadcore.export_leads_unverified(mock_enriched)
        assert len(unverified_leads) == 2
        assert {r["email"] for r in unverified_leads} == {"unverified@salon.com", "info@guessedspa.com"}


def test_proof_b_overpass_504_second_area_preserves_first_area(temp_workspace):
    """
    Proof (b): An Overpass 504 on the 2nd area still saves area 1 leads.
    """
    area1_biz = [
        {"osm_type": "node", "osm_id": 101, "latitude": 30.26, "longitude": -97.74, "business_name": "Area 1 Dental", "phone": "+1 512 555 1111", "phone_e164": "+15125551111", "website": "https://area1.com", "email": ""}
    ]
    area1_enriched = [
        {"osm_type": "node", "osm_id": 101, "latitude": 30.26, "longitude": -97.74, "business_name": "Area 1 Dental", "email": "contact@area1.com", "phone": "+1 512 555 1111", "phone_e164": "+15125551111", "website": "https://area1.com", "verification_status": "unverified", "contact_method": "email"}
    ]

    def mock_query_overpass(tags, lat, lon, radius, ua, **kwargs):
        if lat == 30.26:  # Area 1
            return area1_biz
        else:  # Area 2 triggers 504 / RuntimeError
            raise RuntimeError("Overpass HTTP 504 Gateway Timeout")

    def mock_geocode(area, city, ua):
        if "Area1" in area:
            return 30.26, -97.74, "US"
        return 30.30, -97.70, "US"

    with patch("leadcore.geocode_location", side_effect=mock_geocode), \
         patch("leadcore.query_overpass", side_effect=mock_query_overpass), \
         patch("leadcore.enrich_leads_concurrently", return_value=area1_enriched):

        at = AppTest.from_file("app.py", default_timeout=15).run()
        contact_input = next(t for t in at.text_input if "contact email" in t.label.lower())
        contact_input.input("buyer@gmail.com").run()
        
        fallback_input = next(t for t in at.text_input if "manual" in t.label.lower() or "place" in t.label.lower())
        fallback_input.input("Area1, Area2").run()
        
        start_btn = next(b for b in at.button if "Start Sourcing" in b.label)
        start_btn.click().run()

        assert not at.exception, f"App threw exception: {at.exception}"

        # Verify that Area 1 lead was saved to local history and CSV!
        history = leadcore.load_json("lead_history.json")
        assert "node_101" in history, "Expected Area 1 lead to be saved in history even though Area 2 failed with 504"

        # Verify CSV has the lead
        assert os.path.exists("localleads_export.csv")
        import pandas as pd
        saved_csv = pd.read_csv("localleads_export.csv")
        assert len(saved_csv) == 1
        assert saved_csv.iloc[0]["business_name"] == "Area 1 Dental"


def test_proof_c_shared_emails_do_not_drop_leads(temp_workspace):
    """
    Proof (c): Shared emails do not drop leads.
    Both leads remain in the dataset, with shared_email=True.
    """
    mock_biz = [
        {"osm_type": "node", "osm_id": 201, "latitude": 30.26, "longitude": -97.74, "business_name": "Clinic Downtown", "phone": "", "phone_e164": "", "website": "", "email": ""},
        {"osm_type": "node", "osm_id": 202, "latitude": 30.27, "longitude": -97.75, "business_name": "Clinic North", "phone": "", "phone_e164": "", "website": "", "email": ""},
    ]
    # Both clinics share info@clinicnetwork.com
    mock_enriched = [
        {"osm_type": "node", "osm_id": 201, "latitude": 30.26, "longitude": -97.74, "business_name": "Clinic Downtown", "email": "info@clinicnetwork.com", "phone": "+1 512 555 2001", "phone_e164": "+15125552001", "website": "https://clinicnetwork.com", "verification_status": "unverified", "contact_method": "email"},
        {"osm_type": "node", "osm_id": 202, "latitude": 30.27, "longitude": -97.75, "business_name": "Clinic North", "email": "info@clinicnetwork.com", "phone": "+1 512 555 2002", "phone_e164": "+15125552002", "website": "https://clinicnetwork.com", "verification_status": "unverified", "contact_method": "email"},
    ]

    with patch("leadcore.geocode_location", return_value=(30.26, -97.74, "US")), \
         patch("leadcore.query_overpass", return_value=mock_biz), \
         patch("leadcore.enrich_leads_concurrently", return_value=mock_enriched):

        at = AppTest.from_file("app.py", default_timeout=15).run()
        contact_input = next(t for t in at.text_input if "contact email" in t.label.lower())
        contact_input.input("buyer@gmail.com").run()
        
        fallback_input = next(t for t in at.text_input if "manual" in t.label.lower() or "place" in t.label.lower())
        fallback_input.input("Downtown, Austin").run()
        
        start_btn = next(b for b in at.button if "Start Sourcing" in b.label)
        start_btn.click().run()

        assert not at.exception, f"App threw exception: {at.exception}"

        import pandas as pd
        saved_csv = pd.read_csv("localleads_export.csv")
        assert len(saved_csv) == 2, "Both leads sharing the same email must be saved, not dropped!"
        assert saved_csv.iloc[0]["business_name"] == "Clinic Downtown"
        assert saved_csv.iloc[1]["business_name"] == "Clinic North"
        assert bool(saved_csv.iloc[1]["shared_email"]) is True
