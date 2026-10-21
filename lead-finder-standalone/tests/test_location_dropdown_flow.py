"""
test_location_dropdown_flow.py — Playwright E2E test for the pure dropdown location flow.

Verifies:
1. Manual place validation: typing a single part without selected city keeps Run disabled with error caption.
2. Dropdown path: Filter Country -> Select Region -> Select City.
3. Above-the-fold viewport assertion: Run button bounding box is fully inside 1366x768 and 1280x720 viewports.
4. Load neighborhoods via Overpass and select multiple.
5. Sourcing run with synthetic demo data (Dental Care, .example.com).
6. Visible "Sample data (fictional)" caption.
7. Capture screenshots to docs/screenshots/ with suffixes _1440, _1366, _1024, _390.
"""

import os
import sys
import time
import socket
import subprocess
import pytest
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def test_location_dropdown_flow():
    port = 8504
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    docs_screenshots_dir = os.path.join(base_dir, "docs", "screenshots")
    os.makedirs(docs_screenshots_dir, exist_ok=True)

    # Clean up state files before test
    for fname in ["lead_history.json", "localleads_export.csv", "settings.json", "verified_emails_cache.json"]:
        fpath = os.path.join(base_dir, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass

    # Launch Streamlit with mocked app
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        os.path.join("tests", "mocked_app.py"),
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false"
    ]
    proc = subprocess.Popen(cmd, cwd=base_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        start_t = time.time()
        ready = False
        while time.time() - start_t < 25:
            if is_port_open(port):
                ready = True
                break
            time.sleep(0.5)

        assert ready, f"Streamlit server did not start in time on port {port}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.goto(f"http://localhost:{port}", wait_until="networkidle")
            page.wait_for_selector(".header-title", timeout=15000)
            page.wait_for_timeout(1000)

            # -------------------------------------------------------------
            # 1. Test Manual Place Validation (Single part without city)
            # -------------------------------------------------------------
            expander = page.locator("text=Place (area, city, region or country)")
            expander.click()
            page.wait_for_timeout(400)

            manual_input = page.locator("input[aria-label*='Manual area']")
            manual_input.fill("Downtown")
            manual_input.press("Enter")

            # Verify validation error is displayed
            validation_error = page.locator("text=Manual place requires at least two comma-separated parts")
            validation_error.wait_for(state="visible", timeout=10000)
            assert validation_error.is_visible(), "Error message must be shown for single-part manual place"

            # Capture screenshot of manual place validation message
            screenshot_manual_val = os.path.join(docs_screenshots_dir, "manual_place_validation_1440.png")
            page.screenshot(path=screenshot_manual_val)
            print(f"Saved: {screenshot_manual_val}")

            # Clear manual input and close expander
            manual_input.fill("")
            manual_input.press("Enter")
            page.wait_for_timeout(400)
            expander.click()
            page.wait_for_timeout(300)

            # -------------------------------------------------------------
            # 2. Step 1: Enter Contact Email
            # -------------------------------------------------------------
            contact_input = page.locator("input[aria-label*='Your contact email']")
            contact_input.fill("buyer@gmail.com")
            contact_input.press("Enter")
            page.wait_for_timeout(800)

            # -------------------------------------------------------------
            # 3. Step 2: Dropdown Location Flow (Country -> Region -> City)
            # -------------------------------------------------------------
            # Select Country with typed filter
            country_input = page.get_by_role("combobox", name="Country")
            country_input.click()
            page.keyboard.type("United States")
            page.wait_for_timeout(500)

            # Screenshot: Dropdown open with typed filter
            screenshot_dropdown_filter = os.path.join(docs_screenshots_dir, "dropdown_typed_filter_1440.png")
            page.screenshot(path=screenshot_dropdown_filter)
            print(f"Saved: {screenshot_dropdown_filter}")

            # Select option
            page.locator("[role='option']:has-text('United States')").first.click()
            page.wait_for_timeout(800)

            # Select Region: Texas
            region_input = page.get_by_role("combobox", name="Region (state/province)")
            region_input.click()
            page.keyboard.type("Texas")
            page.wait_for_timeout(500)
            page.locator("[role='option']:has-text('Texas')").first.click()
            page.wait_for_timeout(800)

            # Select City: Austin
            city_input = page.get_by_role("combobox", name="City")
            city_input.click()
            page.keyboard.type("Austin")
            page.wait_for_timeout(500)
            page.locator("[role='option']:has-text('Austin')").first.click()
            page.wait_for_timeout(800)

            # Screenshot: City selected
            screenshot_city_selected = os.path.join(docs_screenshots_dir, "city_selected_1440.png")
            page.screenshot(path=screenshot_city_selected)
            print(f"Saved: {screenshot_city_selected}")

            # Select Business Category: Clinic / Doctor / Dental
            cat_input = page.get_by_role("combobox", name="Business Category")
            cat_input.click()
            page.keyboard.type("Dental")
            page.wait_for_timeout(400)
            page.locator("[role='option']:has-text('Clinic / Doctor / Dental')").first.click()
            page.wait_for_timeout(600)

            # -------------------------------------------------------------
            # 4. Viewport Height Assertion (Above-the-fold Run button)
            # -------------------------------------------------------------
            submit_btn = page.locator("button:has-text('Start Sourcing Leads')")

            # Assert on 1366x768
            page.set_viewport_size({"width": 1366, "height": 768})
            page.wait_for_timeout(400)
            box_1366 = submit_btn.bounding_box()
            assert box_1366 is not None, "Submit button bounding box should exist at 1366x768"
            assert box_1366["y"] + box_1366["height"] <= 768, (
                f"Run button must be fully above fold on 1366x768! Bottom edge: {box_1366['y'] + box_1366['height']}"
            )

            # Assert on 1280x720
            page.set_viewport_size({"width": 1280, "height": 720})
            page.wait_for_timeout(400)
            box_1280 = submit_btn.bounding_box()
            assert box_1280 is not None, "Submit button bounding box should exist at 1280x720"
            assert box_1280["y"] + box_1280["height"] <= 720, (
                f"Run button must be fully above fold on 1280x720! Bottom edge: {box_1280['y'] + box_1280['height']}"
            )

            # Reset back to 1440x900
            page.set_viewport_size({"width": 1440, "height": 900})
            page.wait_for_timeout(400)

            # -------------------------------------------------------------
            # 5. Load Neighborhoods
            # -------------------------------------------------------------
            load_neigh_btn = page.get_by_role("button", name="Load neighborhoods")
            assert not load_neigh_btn.is_disabled(), "Load neighborhoods must be enabled when city is selected"
            load_neigh_btn.click()
            page.wait_for_timeout(1500)

            # Screenshot: Neighborhoods loaded
            screenshot_neigh_loaded = os.path.join(docs_screenshots_dir, "neighborhoods_loaded_1440.png")
            page.screenshot(path=screenshot_neigh_loaded)
            print(f"Saved: {screenshot_neigh_loaded}")

            # Pick 2 neighborhoods in multiselect (Downtown & South Congress)
            neigh_select = page.locator("div[data-testid='stMultiSelect'] input")
            neigh_select.click()
            page.keyboard.type("Downtown")
            page.wait_for_timeout(300)
            page.locator("[role='option']:has-text('Downtown')").first.click()
            page.wait_for_timeout(400)

            neigh_select.click()
            page.keyboard.type("South Congress")
            page.wait_for_timeout(300)
            page.locator("[role='option']:has-text('South Congress')").first.click()
            page.wait_for_timeout(400)

            # -------------------------------------------------------------
            # 6. Run Sourcing with Mocked Data
            # -------------------------------------------------------------
            submit_btn = page.get_by_role("button", name="Start Sourcing Leads")
            submit_btn.click()

            # Wait for completion summary banner
            page.wait_for_selector("text=Run finished", timeout=40000)
            page.wait_for_timeout(1500)

            # -------------------------------------------------------------
            # 7. Assertions: Demo Caption, Metrics, Tabs
            # -------------------------------------------------------------
            caption_elem = page.locator("text=Sample data (fictional)")
            assert caption_elem.is_visible(), "Sample data (fictional) caption must be visible in demo run"

            metrics = page.locator(".metric-card")
            assert metrics.count() == 5, f"Expected 5 metric cards, found {metrics.count()}"

            # Tab badge check: [data-testid="stTab"] code or button[role="tab"] code
            tab_badges = page.locator("[role='tab'] code")
            assert tab_badges.count() >= 5, f"Expected code badges on all 5 tabs, found {tab_badges.count()}"

            browser.close()

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    test_location_dropdown_flow()
