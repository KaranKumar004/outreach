"""
test_version_consistency.py — Verifies that config.VERSION (1.0.2) is strictly synchronized across:
- Rendered header in ui.render_header
- User-Agent strings in app.py, places.py, and scripts/yield_benchmark.py
- Benchmark banner in scripts/yield_benchmark.py
- README.md (title, User-Agent documentation, footer)
- CHANGELOG.md (top release entry)
- make_zip.ZIP_FILENAME
- Shipped files contain zero stale version strings (v1.0.1, v1.0.0). Older history in CHANGELOG is allowed.
"""

import os
import sys
import re
import pytest

REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

import config
import make_zip
import ui


def test_version_value():
    assert config.VERSION == "1.0.2", f"Expected version 1.0.2, found {config.VERSION}"


def test_zip_filename_matches_version():
    expected_zip = f"LocalLeads-Kit-v{config.VERSION}.zip"
    assert make_zip.ZIP_FILENAME == expected_zip, (
        f"make_zip.ZIP_FILENAME ({make_zip.ZIP_FILENAME}) does not match expected {expected_zip}"
    )


def test_rendered_header_matches_version():
    from unittest.mock import patch
    with patch("streamlit.markdown") as mock_md:
        ui.render_header(config.VERSION, config.SUPPORT_EMAIL)
        header_html = mock_md.call_args[0][0]
        assert f"v{config.VERSION}" in header_html, f"Header HTML does not contain v{config.VERSION}"


def test_user_agent_strings_match_version():
    expected_ua_prefix = f"LocalLeadsKit/{config.VERSION}"

    # 1. app.py User-Agent
    app_path = os.path.join(REPO_DIR, "app.py")
    with open(app_path, "r", encoding="utf-8") as f:
        app_content = f.read()
    assert f"LocalLeadsKit/{{config.VERSION}}" in app_content or expected_ua_prefix in app_content

    # 2. places.py User-Agent
    places_path = os.path.join(REPO_DIR, "places.py")
    with open(places_path, "r", encoding="utf-8") as f:
        places_content = f.read()
    assert f"LocalLeadsKit/{{config.VERSION}}" in places_content or expected_ua_prefix in places_content

    # 3. scripts/yield_benchmark.py User-Agent and Banner
    bench_path = os.path.join(REPO_DIR, "scripts", "yield_benchmark.py")
    with open(bench_path, "r", encoding="utf-8") as f:
        bench_content = f.read()
    assert f"LocalLeadsKit/{{config.VERSION}}" in bench_content or expected_ua_prefix in bench_content
    assert f"LocalLeads Kit Yield Benchmark — v{{config.VERSION}}" in bench_content or f"v{config.VERSION}" in bench_content


def test_readme_matches_version():
    readme_path = os.path.join(REPO_DIR, "README.md")
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert f"# LocalLeads Kit v{config.VERSION}" in content, "README title missing current version"
    assert f"LocalLeadsKit/{config.VERSION}" in content, "README User-Agent missing current version"
    assert f"<b>LocalLeads Kit v{config.VERSION}</b>" in content, "README footer missing current version"

    # Ensure no stale version references exist in README
    assert "1.0.1" not in content, "Stale version 1.0.1 found in README.md"
    assert "1.0.0" not in content, "Stale version 1.0.0 found in README.md"


def test_changelog_top_entry_matches_version():
    changelog_path = os.path.join(REPO_DIR, "CHANGELOG.md")
    with open(changelog_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Find the first release section (## [version])
    first_release = None
    for line in lines:
        m = re.match(r"^##\s*\[([0-9.]+)\]", line.strip())
        if m:
            first_release = m.group(1)
            break

    assert first_release == config.VERSION, (
        f"Top CHANGELOG entry version [{first_release}] does not match config.VERSION [{config.VERSION}]"
    )


def test_no_stale_versions_in_shipped_files():
    """
    Scans all shipped files (per make_zip.should_include, excluding CHANGELOG history and binary files)
    and asserts that stale version references (v1.0.1, v1.0.0) do not exist.
    """
    stale_patterns = [
        re.compile(r"v1\.0\.[01]\b", re.IGNORECASE),
        re.compile(r"LocalLeadsKit/1\.0\.[01]\b"),
        re.compile(r"LocalLeads-Kit-v1\.0\.[01]\.zip"),
    ]

    shipped_files = []
    for root, _, files in os.walk(REPO_DIR):
        for f in files:
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, REPO_DIR)
            if make_zip.should_include(rel_path):
                shipped_files.append((full_path, rel_path))

    for full_path, rel_path in shipped_files:
        # CHANGELOG history is permitted to mention older versions
        if rel_path == "CHANGELOG.md":
            continue
        # Skip binary files
        if rel_path.endswith((".woff2", ".gz", ".png", ".jpg", ".jpeg", ".ico")):
            continue

        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, start=1):
                # Allow comments specifically mentioning backwards-compatibility migration from v1.0.0/v1.0.1
                if "v1.0.0/v1.0.1" in line or ("v1.0.0" in line and "migration" in line.lower()):
                    continue
                for pat in stale_patterns:
                    match = pat.search(line)
                    assert not match, (
                        f"Stale version string '{match.group(0)}' found in shipped file "
                        f"{rel_path}:{line_no} -> {line.strip()}"
                    )
