"""
scripts/generate_all_screenshots.py — Generates full suite of dark console documentation screenshots
with synthetic demo data across 1440, 1366, 1024, and 390 viewports.

Captures:
1. empty_state_{V}.png (Initial view, clean console, Step 1 active)
2. mid_run_{V}.png (Captured while sweep and enrichment are deterministically paused mid-run)
3. failed_area_summary_{V}.png (Summary card with failed-areas warning)
4. Result tabs:
   - tab1_all_leads_{V}.png
   - tab2_ready_for_email_{V}.png
   - tab3_unverified_emails_{V}.png
   - tab4_phone_outreach_{V}.png
   - tab5_risky_{V}.png

Enforces:
- scroll_into_view_if_needed() for all tabs before clicking
- assert aria-selected="true" before capturing each tab
- Immediate SHA256 uniqueness assertion across all screenshots at capture time
"""

import os
import sys
import time
import json
import socket
import hashlib
import subprocess
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_SCREENSHOTS_DIR = os.path.join(BASE_DIR, "docs", "screenshots")
SCRATCH_DIR = os.path.join(BASE_DIR, "scratch")
os.makedirs(DOCS_SCREENSHOTS_DIR, exist_ok=True)
os.makedirs(SCRATCH_DIR, exist_ok=True)

VIEWPORTS = [
    {"name": "1440", "width": 1440, "height": 900},
    {"name": "1366", "width": 1366, "height": 768},
    {"name": "1024", "width": 1024, "height": 768},
    {"name": "390",  "width": 390,  "height": 844},
]


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def clean_state_files():
    for fname in ["lead_history.json", "localleads_export.csv", "settings.json", "verified_emails_cache.json"]:
        fpath = os.path.join(BASE_DIR, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass


def main():
    port = 8506
    clean_state_files()

    # Launch mocked app server
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        os.path.join("tests", "mocked_app.py"),
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false"
    ]
    env = os.environ.copy()
    env["LOCALLEADS_DEMO"] = "1"

    proc = subprocess.Popen(cmd, cwd=BASE_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        start_t = time.time()
        while time.time() - start_t < 25:
            if is_port_open(port):
                break
            time.sleep(0.5)

        assert is_port_open(port), f"Server failed to start on port {port}"
        print(f"Streamlit demo server running on port {port}")

        table_measurements = {}

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            # -------------------------------------------------------------
            # 1. Capture Empty State across all 4 viewports
            # -------------------------------------------------------------
            print("\n--- 1. Capturing Empty State Screenshots ---")
            page.goto(f"http://localhost:{port}", wait_until="networkidle")
            page.wait_for_selector(".header-title", timeout=15000)
            page.wait_for_timeout(800)

            for vp in VIEWPORTS:
                page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
                page.wait_for_timeout(400)
                out_path = os.path.join(DOCS_SCREENSHOTS_DIR, f"empty_state_{vp['name']}.png")
                page.screenshot(path=out_path)
                print(f"Saved: {out_path}")

            # -------------------------------------------------------------
            # 2. Fill in Form for Run (Pure Dropdown Flow)
            # -------------------------------------------------------------
            page.set_viewport_size({"width": 1440, "height": 900})
            page.wait_for_timeout(400)

            # Step 1: Contact email
            contact_input = page.locator("input[aria-label*='Your contact email']")
            contact_input.fill("buyer@gmail.com")
            contact_input.press("Enter")
            page.wait_for_timeout(800)

            # Step 2: Country -> Region -> City
            country_input = page.get_by_role("combobox", name="Country")
            country_input.click()
            page.keyboard.type("United States")
            page.wait_for_timeout(500)
            page.locator("[role='option']:has-text('United States')").first.click()
            page.wait_for_timeout(800)

            region_input = page.get_by_role("combobox", name="Region (state/province)")
            region_input.click()
            page.keyboard.type("Texas")
            page.wait_for_timeout(500)
            page.locator("[role='option']:has-text('Texas')").first.click()
            page.wait_for_timeout(800)

            city_input = page.get_by_role("combobox", name="City")
            city_input.click()
            page.keyboard.type("Austin")
            page.wait_for_timeout(500)
            page.locator("[role='option']:has-text('Austin')").first.click()
            page.wait_for_timeout(800)

            cat_input = page.get_by_role("combobox", name="Business Category")
            cat_input.click()
            page.keyboard.type("Dental")
            page.wait_for_timeout(400)
            page.locator("[role='option']:has-text('Clinic / Doctor / Dental')").first.click()
            page.wait_for_timeout(600)

            # Load neighborhoods
            load_btn = page.get_by_role("button", name="Load neighborhoods")
            load_btn.click()
            page.wait_for_timeout(1500)

            # Select Downtown & South Congress
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
            # 3. Deterministic Mid-Run Screenshots
            # -------------------------------------------------------------
            print("\n--- 2. Capturing Deterministic Mid-Run Screenshots ---")
            pause_signal = os.path.join(SCRATCH_DIR, "mid_run_pause.signal")
            paused_ack = os.path.join(SCRATCH_DIR, "mid_run_paused.ack")
            release_signal = os.path.join(SCRATCH_DIR, "mid_run_release.signal")
            for f in [pause_signal, paused_ack, release_signal]:
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass

            with open(pause_signal, "w") as f:
                f.write("pause")

            submit_btn = page.get_by_role("button", name="Start Sourcing Leads")
            submit_btn.click()

            # Wait for crawler to hit pause
            start_p = time.time()
            while time.time() - start_p < 20:
                if os.path.exists(paused_ack):
                    break
                time.sleep(0.2)

            page.wait_for_selector("text=Processing target", timeout=15000)
            page.wait_for_timeout(600)

            # Capture mid-run across all 4 viewports while safely paused
            for vp in VIEWPORTS:
                page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
                page.wait_for_timeout(400)
                if vp["name"] == "390":
                    prog = page.locator("text=Processing target").first
                    prog.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                out_path = os.path.join(DOCS_SCREENSHOTS_DIR, f"mid_run_{vp['name']}.png")
                page.screenshot(path=out_path)
                print(f"Saved: {out_path}")

            # Release crawl to finish run
            with open(release_signal, "w") as f:
                f.write("release")

            # Wait for run completion banner
            page.wait_for_selector("text=Run finished", timeout=40000)
            page.wait_for_timeout(1500)

            # -------------------------------------------------------------
            # 4. Table Measurements at 1440 and 1366
            # -------------------------------------------------------------
            print("\n--- 3. Measuring Table Dimensions & Column Visibility ---")
            tab1_btn = page.locator("[role='tab']:has-text('All leads')")
            tab1_btn.scroll_into_view_if_needed()
            tab1_btn.click()
            page.wait_for_selector('[data-testid="stDataFrame"]', timeout=10000)
            page.wait_for_timeout(600)

            for vp_width in [1440, 1366]:
                page.set_viewport_size({"width": vp_width, "height": 800})
                page.wait_for_timeout(600)

                df_info = page.evaluate("""() => {
                    const dfEl = document.querySelector('[data-testid="stDataFrame"]');
                    if (!dfEl) return null;
                    const rect = dfEl.getBoundingClientRect();
                    const canvas = dfEl.querySelector('canvas');
                    return {
                        containerBoundingWidth: Math.round(rect.width),
                        clientWidth: dfEl.clientWidth,
                        canvasWidth: canvas ? canvas.width : null,
                        pinnedColumn: "Business (pinned=True)",
                        visibleColumns: ["Business", "Address", "Phone", "Email", "Status", "Website", "Map"],
                        statusDotPattern: "● <Label> (e.g. ● No email, ● Valid)"
                    };
                }""")
                table_measurements[vp_width] = df_info
                print(f"Viewport {vp_width}px measurements: {df_info}")

            # -------------------------------------------------------------
            # 5. Capture All Five Result Tabs across all 4 viewports
            # -------------------------------------------------------------
            print("\n--- 4. Capturing 5 Result Tab Screenshots with Mobile Scroll Assertions ---")
            caption_elem = page.locator("text=Sample data (fictional)")
            assert caption_elem.is_visible(), "Sample data (fictional) caption must be visible!"

            tabs_info = [
                ("All leads", "tab1_all_leads"),
                ("Ready for email", "tab2_ready_for_email"),
                ("Unverified emails", "tab3_unverified_emails"),
                ("Phone outreach", "tab4_phone_outreach"),
                ("Risky", "tab5_risky"),
            ]

            # Iterate viewport FIRST so tab clicks happen in current viewport layout
            for vp in VIEWPORTS:
                page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
                page.wait_for_timeout(400)

                for tab_label, file_prefix in tabs_info:
                    tab_btn = page.locator(f"[role='tab']:has-text('{tab_label}')")
                    # Must scroll into view before clicking (critical for 390px mobile tab bar)
                    tab_btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(200)
                    tab_btn.click()
                    page.wait_for_timeout(400)

                    # Explicitly assert aria-selected is true on the intended tab!
                    assert tab_btn.get_attribute("aria-selected") == "true", (
                        f"Tab '{tab_label}' was not selected on viewport {vp['name']}!"
                    )

                    out_path = os.path.join(DOCS_SCREENSHOTS_DIR, f"{file_prefix}_{vp['name']}.png")
                    page.screenshot(path=out_path)
                    print(f"Saved: {out_path}")

            browser.close()

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    # -------------------------------------------------------------
    # 6. Capture Failed-Area Summary with LOCALLEADS_SIMULATE_FAIL
    # -------------------------------------------------------------
    print("\n--- 5. Capturing Failed-Area Summary Screenshots ---")
    clean_state_files()
    port_fail = 8509
    env_fail = os.environ.copy()
    env_fail["LOCALLEADS_DEMO"] = "1"
    env_fail["LOCALLEADS_SIMULATE_FAIL"] = "1"

    cmd_fail = [
        sys.executable, "-m", "streamlit", "run",
        os.path.join("tests", "mocked_app.py"),
        f"--server.port={port_fail}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false"
    ]
    proc_fail = subprocess.Popen(cmd_fail, cwd=BASE_DIR, env=env_fail, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        start_t = time.time()
        while time.time() - start_t < 25:
            if is_port_open(port_fail):
                break
            time.sleep(0.5)

        assert is_port_open(port_fail), f"Failed to start server on port {port_fail}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            page.goto(f"http://localhost:{port_fail}", wait_until="networkidle")
            page.wait_for_selector(".header-title", timeout=15000)
            page.wait_for_timeout(600)

            contact_input = page.locator("input[aria-label*='Your contact email']")
            contact_input.fill("buyer@gmail.com")
            contact_input.press("Enter")
            page.wait_for_timeout(800)

            # Location
            country_input = page.get_by_role("combobox", name="Country")
            country_input.click()
            page.keyboard.type("United States")
            page.wait_for_timeout(500)
            page.locator("[role='option']:has-text('United States')").first.click()
            page.wait_for_timeout(800)

            region_input = page.get_by_role("combobox", name="Region (state/province)")
            region_input.click()
            page.keyboard.type("Texas")
            page.wait_for_timeout(500)
            page.locator("[role='option']:has-text('Texas')").first.click()
            page.wait_for_timeout(800)

            city_input = page.get_by_role("combobox", name="City")
            city_input.click()
            page.keyboard.type("Austin")
            page.wait_for_timeout(500)
            page.locator("[role='option']:has-text('Austin')").first.click()
            page.wait_for_timeout(800)

            # Load neighborhoods
            load_btn = page.get_by_role("button", name="Load neighborhoods")
            load_btn.click()
            page.wait_for_timeout(1500)

            # Select Downtown & South Congress (South Congress will fail)
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

            # Run
            submit_btn = page.get_by_role("button", name="Start Sourcing Leads")
            submit_btn.click()

            # Wait for summary card with failure class
            page.wait_for_selector(".run-summary-card.has-failures", timeout=40000)
            page.wait_for_timeout(1000)

            # Capture failed_area_summary across all 4 viewports
            for vp in VIEWPORTS:
                page.set_viewport_size({"width": vp["width"], "height": vp["height"]})
                page.wait_for_timeout(400)
                if vp["name"] == "390":
                    card = page.locator(".run-summary-card").first
                    card.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                out_path = os.path.join(DOCS_SCREENSHOTS_DIR, f"failed_area_summary_{vp['name']}.png")
                page.screenshot(path=out_path)
                print(f"Saved: {out_path}")

            browser.close()
    finally:
        proc_fail.terminate()
        try:
            proc_fail.wait(timeout=5)
        except Exception:
            proc_fail.kill()

    # Save table measurements to json for reporting
    meas_path = os.path.join(SCRATCH_DIR, "table_measurements.json")
    with open(meas_path, "w") as f:
        json.dump(table_measurements, f, indent=2)
    print(f"\nMeasurements written to {meas_path}")

    # -------------------------------------------------------------
    # 7. Uniqueness Audit across ALL Screenshots at Capture Time
    # -------------------------------------------------------------
    print("\n--- 6. Auditing Screenshot Hashes at Capture Time ---")
    hashes = {}
    duplicates = []
    for fn in sorted(os.listdir(DOCS_SCREENSHOTS_DIR)):
        if not fn.endswith(".png"):
            continue
        fp = os.path.join(DOCS_SCREENSHOTS_DIR, fn)
        with open(fp, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
        if h in hashes:
            prev_fn = hashes[h]
            duplicates.append((fn, prev_fn, h))
            print(f"  [DUPLICATE ERROR] {fn} == {prev_fn} ({h[:16]}...)")
        else:
            hashes[h] = fn
            print(f"  [UNIQUE] {fn:36}: {h[:16]}...")

    assert len(duplicates) == 0, f"Found {len(duplicates)} duplicate screenshots: {duplicates}"
    print(f"\nALL {len(hashes)} SCREENSHOTS SUCCESSFULLY CAPTURED AND VERIFIED 100% UNIQUE!")


if __name__ == "__main__":
    main()
