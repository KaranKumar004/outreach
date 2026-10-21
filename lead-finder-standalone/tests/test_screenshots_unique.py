"""
tests/test_screenshots_unique.py — Verification that documentation screenshots have unique SHA256 hashes.

Skips cleanly if docs/screenshots is absent.
Verifies:
1. All 5 tab screenshots per viewport (1440, 1366, 1024, 390) are distinct.
2. Across all screenshots in docs/screenshots/, only explicitly allow-listed duplicates exist.
"""

import os
import hashlib
import pytest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS_SCREENSHOTS_DIR = os.path.join(BASE_DIR, "docs", "screenshots")


VIEWPORTS = ["1440", "1366", "1024", "390"]
TAB_PREFIXES = [
    "tab1_all_leads",
    "tab2_ready_for_email",
    "tab3_unverified_emails",
    "tab4_phone_outreach",
    "tab5_risky",
]


def file_sha256(filepath: str) -> str:
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_screenshots_unique_and_tab_distinct():
    """Verify that all documentation screenshots have distinct hashes (with clean skip if absent)."""
    if not os.path.exists(DOCS_SCREENSHOTS_DIR):
        pytest.skip(f"docs/screenshots directory not found at {DOCS_SCREENSHOTS_DIR}")

    files = [f for f in os.listdir(DOCS_SCREENSHOTS_DIR) if f.endswith(".png")]
    if not files:
        pytest.skip("docs/screenshots contains no png files")

    # 1. Verify that the 5 tab screenshots are distinct for each viewport
    for vp in VIEWPORTS:
        tab_hashes = {}
        for tab_pre in TAB_PREFIXES:
            fn = f"{tab_pre}_{vp}.png"
            fp = os.path.join(DOCS_SCREENSHOTS_DIR, fn)
            assert os.path.exists(fp), f"Missing expected tab screenshot: {fn}"
            h = file_sha256(fp)
            assert h not in tab_hashes, (
                f"Duplicate tab screenshot on viewport {vp}! "
                f"{fn} has identical hash to {tab_hashes[h]} ({h})"
            )
            tab_hashes[h] = fn

    # 2. Verify all screenshots in docs/screenshots/ are 100% unique (zero duplicates)
    all_hashes = {}
    duplicates = []
    for fn in sorted(files):
        fp = os.path.join(DOCS_SCREENSHOTS_DIR, fn)
        h = file_sha256(fp)
        if h in all_hashes:
            prev_fn = all_hashes[h]
            duplicates.append((fn, prev_fn, h))
        else:
            all_hashes[h] = fn

    assert len(duplicates) == 0, (
        f"Found {len(duplicates)} duplicate screenshots in docs/screenshots/:\n"
        + "\n".join(f"  - {f1} == {f2} ({h})" for f1, f2, h in duplicates)
    )
