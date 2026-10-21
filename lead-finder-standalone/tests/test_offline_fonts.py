"""
tests/test_offline_fonts.py — End-to-end verification of bundled offline typography.

Verifies:
1. document.fonts.load("16px Manrope") returns FontFace objects with status "loaded".
2. document.fonts.load("14px 'JetBrains Mono'") returns FontFace objects with status "loaded".
3. Font woff2 assets are served directly from localhost (/app/static/fonts/).
4. Zero requests are sent to external font CDNs (fonts.googleapis.com or fonts.gstatic.com).
"""

import os
import sys
import time
import socket
import subprocess
import pytest
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def test_offline_fonts_load_and_zero_cdn():
    port = 8511

    # Run app.py directly so Streamlit locates static/ relative to root
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        "app.py",
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

        requested_urls = []
        font_responses = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            def handle_request(req):
                requested_urls.append(req.url)

            def handle_response(resp):
                if resp.url.endswith(".woff2"):
                    font_responses.append({
                        "url": resp.url,
                        "status": resp.status,
                    })

            page.on("request", handle_request)
            page.on("response", handle_response)

            # Block any external requests to ensure 100% offline isolation
            def route_handler(route):
                url = route.request.url
                if "localhost" in url or "127.0.0.1" in url:
                    route.continue_()
                else:
                    route.abort()

            page.route("**/*", route_handler)

            page.goto(f"http://localhost:{port}", wait_until="networkidle")
            page.wait_for_selector(".header-title", timeout=15000)

            # 1. Assert zero requests to external font CDNs
            google_fonts_requests = [u for u in requested_urls if "fonts.googleapis.com" in u or "fonts.gstatic.com" in u]
            assert len(google_fonts_requests) == 0, f"Found unexpected Google Fonts requests: {google_fonts_requests}"

            # 2. Evaluate document.fonts.load() in the browser
            load_result = page.evaluate("""async () => {
                const manropeFaces = await document.fonts.load("16px Manrope");
                const jbFaces = await document.fonts.load("14px 'JetBrains Mono'");
                return {
                    manropeCount: manropeFaces.length,
                    manropeStatuses: manropeFaces.map(f => f.status),
                    jbCount: jbFaces.length,
                    jbStatuses: jbFaces.map(f => f.status),
                };
            }""")

            # 3. Assert FontFace objects are successfully loaded
            assert load_result["manropeCount"] > 0, "No FontFace returned for Manrope"
            assert all(s == "loaded" for s in load_result["manropeStatuses"]), f"Manrope status not loaded: {load_result['manropeStatuses']}"

            assert load_result["jbCount"] > 0, "No FontFace returned for JetBrains Mono"
            assert all(s == "loaded" for s in load_result["jbStatuses"]), f"JetBrains Mono status not loaded: {load_result['jbStatuses']}"

            # 4. Assert woff2 font files were served from localhost with status 200
            local_woff2 = [f for f in font_responses if "localhost" in f["url"] and f["url"].endswith(".woff2")]
            assert len(local_woff2) >= 2, f"Expected at least 2 local woff2 responses, got: {font_responses}"
            assert all(f["status"] == 200 for f in local_woff2), f"Non-200 font response: {local_woff2}"

            browser.close()

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
