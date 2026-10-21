"""
test_browser_clickthrough.py — Automated browser UI test using Playwright.
Verifies:
- Launch app
- Check guessed emails is OFF by default
- Check contact email validation blocks sourcing until filled
- Run sourcing pass
- Inspect tabs & downloads
- Confirm no guessed or unverified email in Ready-for-Email
- Capture screenshots
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


def test_browser_clickthrough():
    port = 8503
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    screenshots_dir = os.path.join(base_dir, "tests", "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    # Clean up state files before run
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
        # Wait up to 25s for server to start
        start_t = time.time()
        ready = False
        while time.time() - start_t < 25:
            if is_port_open(port):
                ready = True
                break
            time.sleep(0.5)

        assert ready, "Streamlit server did not start in time on port 8503"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()

            page.goto(f"http://localhost:{port}", wait_until="networkidle")
            page.wait_for_selector(".header-title", timeout=15000)
            page.wait_for_timeout(1000)

            # 1. Screenshot initial state (first load)
            screenshot_1 = os.path.join(screenshots_dir, "01_first_load.png")
            page.screenshot(path=screenshot_1)
            print(f"Saved: {screenshot_1}")

            # 2. Verify "Include guessed info@ addresses" is OFF by default
            checkbox_guessed = page.locator("label:has-text('Include guessed info@ addresses') input[type='checkbox']")
            assert not checkbox_guessed.is_checked(), "Guessed emails checkbox must be unchecked (OFF) by default!"

            # 3. Check "Start Sourcing Leads" button is disabled when contact email is empty
            submit_btn = page.locator("button:has-text('Start Sourcing Leads')")
            assert submit_btn.is_disabled(), "Start button must be disabled until contact email is provided"

            # 4. Enter contact email in main Step 1 card
            contact_input = page.locator("input[aria-label*='Your contact email']")
            contact_input.fill("buyer@gmail.com")
            contact_input.press("Enter")
            page.wait_for_timeout(1000)

            # 5. Open manual area fallback and enter place
            expander = page.locator("text=Place (area, city, region or country)")
            expander.click()
            page.wait_for_timeout(500)

            areas_input = page.locator("input[aria-label*='Manual area']")
            areas_input.fill("Downtown, Austin, Texas")
            areas_input.press("Enter")
            page.wait_for_timeout(1000)

            screenshot_2 = os.path.join(screenshots_dir, "02_form_filled.png")
            page.screenshot(path=screenshot_2)
            print(f"Saved: {screenshot_2}")

            # 6. Click Start Sourcing Leads & Capture Mid-Run Screenshot
            submit_btn = page.locator("button:has-text('Start Sourcing Leads'):not([disabled])")
            submit_btn.click()
            page.wait_for_timeout(400)
            screenshot_mid = os.path.join(screenshots_dir, "03_mid_run.png")
            page.screenshot(path=screenshot_mid)
            print(f"Saved: {screenshot_mid}")

            # 7. Wait for run completion banner
            page.wait_for_selector("text=Run finished", timeout=40000)
            page.wait_for_timeout(1500)

            screenshot_completed = os.path.join(screenshots_dir, "04_results_completed_banner.png")
            page.screenshot(path=screenshot_completed)
            print(f"Saved: {screenshot_completed}")

            # 8. Verify Metric Cards
            metrics = page.locator(".metric-card")
            assert metrics.count() == 5, f"Expected 5 metric cards, found {metrics.count()}"

            # 9. Check All 5 Tabs
            # Tab 1: All leads
            tab_all = page.locator("[role='tab']:has-text('All leads')")
            tab_all.click()
            page.wait_for_timeout(800)
            screenshot_all = os.path.join(screenshots_dir, "05_results_tab1_all.png")
            page.screenshot(path=screenshot_all)
            print(f"Saved: {screenshot_all}")

            df_all = page.locator("[role='tabpanel']:not([hidden]) [data-testid='stDataFrame']")
            assert df_all.is_visible(), "DataFrame must be visible in All leads tab"
            download_all = page.locator("[role='tabpanel']:not([hidden]) [data-testid='stDownloadButton']")
            assert download_all.is_visible(), "Download button for All leads must be visible"
            assert "all leads" in download_all.inner_text().lower()

            # Tab 2: Ready for email
            tab_ready = page.locator("[role='tab']:has-text('Ready for email')")
            tab_ready.click()
            page.wait_for_timeout(800)
            screenshot_ready = os.path.join(screenshots_dir, "06_results_tab2_ready.png")
            page.screenshot(path=screenshot_ready)
            print(f"Saved: {screenshot_ready}")

            # Confirm stepper is rendered with aria-current="step"
            stepper = page.locator(".stepper-container[role='navigation']")
            assert stepper.is_visible(), "Stepper container must be visible"
            assert stepper.locator("[aria-current='step']").count() == 1, "Exactly one step must have aria-current='step'"

            # Confirm no unverified or guessed email appears in this tab!
            tab_panel = page.locator("[role='tabpanel']:not([hidden])")
            ready_text = tab_panel.inner_text()
            assert "contact@austindentalarts" not in ready_text, "Unverified email must not appear in Ready for email tab!"
            assert "No verified emails yet" in ready_text or "No deliverable" in ready_text, "Info message should state no verified emails yet"

            # Tab 3: Unverified emails
            tab_unverified = page.locator("[role='tab']:has-text('Unverified emails')")
            tab_unverified.click()
            page.wait_for_timeout(800)
            screenshot_unverified = os.path.join(screenshots_dir, "07_results_tab3_unverified.png")
            page.screenshot(path=screenshot_unverified)
            print(f"Saved: {screenshot_unverified}")

            # Verify dataframe and download button are visible
            df_unverified = page.locator("[role='tabpanel']:not([hidden]) [data-testid='stDataFrame']")
            assert df_unverified.is_visible(), "DataFrame must be visible in Unverified tab"
            download_unverified = page.locator("[role='tabpanel']:not([hidden]) [data-testid='stDownloadButton']")
            assert download_unverified.is_visible(), "Download button for Unverified emails must be visible"
            assert "unverified emails" in download_unverified.inner_text().lower()

            # Tab 4: Phone outreach
            tab_phone = page.locator("[role='tab']:has-text('Phone outreach')")
            tab_phone.click()
            page.wait_for_timeout(800)
            screenshot_phone = os.path.join(screenshots_dir, "08_results_tab4_phone.png")
            page.screenshot(path=screenshot_phone)
            print(f"Saved: {screenshot_phone}")

            df_phone = page.locator("[role='tabpanel']:not([hidden]) [data-testid='stDataFrame']")
            assert df_phone.is_visible(), "DataFrame must be visible in Phone outreach tab"
            download_phone = page.locator("[role='tabpanel']:not([hidden]) [data-testid='stDownloadButton']")
            assert download_phone.is_visible(), "Download button for Phone outreach must be visible"
            assert "phone outreach" in download_phone.inner_text().lower()

            # Tab 5: Risky
            tab_risky = page.locator("[role='tab']:has-text('Risky')")
            tab_risky.click()
            page.wait_for_timeout(800)
            screenshot_risky = os.path.join(screenshots_dir, "09_results_tab5_risky.png")
            page.screenshot(path=screenshot_risky)
            print(f"Saved: {screenshot_risky}")

            # 10. Multi-device responsive captures (1440px desktop, 1024px tablet, 390px mobile)
            page.set_viewport_size({"width": 1440, "height": 900})
            page.wait_for_timeout(800)
            page.screenshot(path=os.path.join(screenshots_dir, "10_desktop_1440px.png"))

            page.set_viewport_size({"width": 1024, "height": 768})
            page.wait_for_timeout(800)
            page.screenshot(path=os.path.join(screenshots_dir, "11_tablet_1024px.png"))

            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(800)
            page.screenshot(path=os.path.join(screenshots_dir, "12_mobile_390px.png"))
            print("Saved multi-device responsive screenshots (1440px, 1024px, 390px)")

            # Confirm exported CSV on disk
            csv_file = os.path.join(base_dir, "localleads_export.csv")
            assert os.path.exists(csv_file), "localleads_export.csv must be saved on disk"
            with open(csv_file, encoding="utf-8") as f:
                csv_content = f.read()
            assert "Austin Dental Arts" in csv_content
            assert "unverified" in csv_content

            browser.close()

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    test_browser_clickthrough()
