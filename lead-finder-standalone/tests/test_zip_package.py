"""
test_zip_package.py — Tests zip packaging structure, permissions, exact file list, and strict email hygiene.
"""

import os
import re
import sys
import zipfile
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import make_zip
import config

EXPECTED_FILES = {
    "LocalLeads-Kit/app.py",
    "LocalLeads-Kit/leadcore.py",
    "LocalLeads-Kit/places.py",
    "LocalLeads-Kit/ui.py",
    "LocalLeads-Kit/config.py",
    "LocalLeads-Kit/.streamlit/config.toml",
    "LocalLeads-Kit/data/countries.csv",
    "LocalLeads-Kit/data/admin1.csv",
    "LocalLeads-Kit/data/aliases.csv",
    "LocalLeads-Kit/data/cities.csv.gz",
    "LocalLeads-Kit/static/fonts/manrope-latin.woff2",
    "LocalLeads-Kit/static/fonts/jetbrains-mono-latin.woff2",
    "LocalLeads-Kit/static/fonts/OFL-Manrope.txt",
    "LocalLeads-Kit/static/fonts/OFL-JetBrainsMono.txt",
    "LocalLeads-Kit/sample/sample_leads_fictional.csv",
    "LocalLeads-Kit/run.bat",
    "LocalLeads-Kit/run.sh",
    "LocalLeads-Kit/run.command",
    "LocalLeads-Kit/requirements.txt",
    "LocalLeads-Kit/README.md",
    "LocalLeads-Kit/CHANGELOG.md",
    "LocalLeads-Kit/LICENSE.txt",
    "LocalLeads-Kit/THIRD_PARTY_NOTICES.md",
}


def test_zip_contents_and_email_hygiene():
    """
    Builds and tests dist/LocalLeads-Kit-v1.0.2.zip:
    1. Verifies exact expected file list (23 files, including LICENSE.txt, THIRD_PARTY_NOTICES.md, sample CSV; no .gitignore).
    2. Verifies excluded files are absent (tests, venv, caches, marketing, scripts, assets, export csvs, .gitignore).
    3. Verifies run.sh and run.command have executable permission bits.
    4. Scans all text files in zip for email addresses.
    5. Asserts that the ONLY permitted emails are supportlocalleadskit@gmail.com and reserved .example.com / .example.org.
    """
    zip_path, files_added, total_size = make_zip.package_kit()
    assert os.path.exists(zip_path)

    # Email pattern
    email_regex = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    found_emails = {}

    with zipfile.ZipFile(zip_path, "r") as zf:
        infolist = zf.infolist()
        filenames = set(info.filename for info in infolist)

        # 1. Exact expected file list assertion
        assert filenames == EXPECTED_FILES, (
            f"Package file list mismatch!\n"
            f"Missing: {sorted(EXPECTED_FILES - filenames)}\n"
            f"Extra: {sorted(filenames - EXPECTED_FILES)}"
        )

        # 2. Strict exclusions assertion
        for fn in filenames:
            assert ".gitignore" not in fn, f".gitignore should NOT be in zip: {fn}"
            assert "tests/" not in fn, f"tests found in zip: {fn}"
            assert "scripts/" not in fn, f"scripts found in zip: {fn}"
            assert "marketing/" not in fn, f"marketing found in zip: {fn}"
            assert "assets/" not in fn, f"assets found in zip: {fn}"
            assert "places_cache" not in fn, f"places_cache found in zip: {fn}"
            assert "__pycache__" not in fn, f"pycache found in zip: {fn}"
            assert ".venv" not in fn, f"venv found in zip: {fn}"
            assert "lead_history" not in fn, f"lead_history found in zip: {fn}"
            assert "settings.json" not in fn, f"settings.json found in zip: {fn}"
            assert "verified_emails_cache.json" not in fn, f"verified_emails_cache found in zip: {fn}"
            assert ".agent" not in fn, f".agent found in zip: {fn}"
            assert "skills" not in fn, f"skills found in zip: {fn}"
            assert "screenshots" not in fn, f"screenshots found in zip: {fn}"
            assert "scratch" not in fn, f"scratch found in zip: {fn}"
            assert "docs" not in fn, f"docs found in zip: {fn}"
            assert ".env" not in fn, f"Env file found in zip: {fn}"
            assert "localleads_thumbnail.jpg" not in fn, f"Thumbnail should be excluded: {fn}"
            assert "localleads_cover.jpg" not in fn, f"Cover image should be excluded: {fn}"
            if fn.endswith(".csv"):
                assert fn.startswith("LocalLeads-Kit/data/") or fn.startswith("LocalLeads-Kit/sample/"), f"Unauthorized CSV found in zip: {fn}"

        # 3. Check permissions for executable scripts and ZIP_DEFLATED compression
        for info in infolist:
            assert info.compress_type == zipfile.ZIP_DEFLATED, f"File {info.filename} is not ZIP_DEFLATED compressed!"
            if info.filename.endswith(("run.sh", "run.command")):
                mode = info.external_attr >> 16
                assert (mode & 0o111) != 0, f"Script {info.filename} is not marked executable! mode={oct(mode)}"

        # 4. Strict email hygiene scan across all text files
        for info in infolist:
            # Skip binary images, fonts, and gzip archives
            if info.filename.endswith((".jpg", ".png", ".jpeg", ".ico", ".svg", ".woff2", ".gz")):
                continue

            content = zf.read(info).decode("utf-8", errors="ignore")

            for line_no, line in enumerate(content.splitlines(), start=1):
                if "re.compile" in line or "BASE_EMAIL_PATTERN" in line or "r\"^[" in line or "r'^[" in line:
                    continue

                matches = email_regex.findall(line)
                for match in matches:
                    clean_match = match.strip().lower()
                    if "+" in clean_match and "[" in clean_match:
                        continue
                    found_emails.setdefault(clean_match, []).append((info.filename, line_no))

    # Strict assertion: ONLY supportlocalleadskit@gmail.com and reserved .example.com / .example.org
    allowed_support = config.SUPPORT_EMAIL.lower()
    for email_found, locations in found_emails.items():
        is_support = (email_found == allowed_support)
        is_reserved_example = (email_found.endswith(".example.com") or email_found.endswith(".example.org"))
        assert is_support or is_reserved_example, (
            f"Unauthorized email address '{email_found}' found in package at {locations}! "
            f"Only {allowed_support} and reserved RFC 2606 .example.com / .example.org are permitted."
        )

    assert allowed_support in found_emails, f"Expected {allowed_support} to be present in package."
    print(f"\n[EMAIL AUDIT] Checked {len(found_emails)} distinct email addresses across all package files:")
    for email, locs in sorted(found_emails.items()):
        print(f"  - {email} ({len(locs)} occurrences)")


def test_third_party_notices_and_readme_geonames_attribution():
    """
    Verifies that GeoNames attribution in THIRD_PARTY_NOTICES.md, README.md, and config.py
    uses the accurate unversioned CC BY wording without misattributing CC BY deed text to geonames.org.
    """
    repo_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    expected_attribution = "Contains data from GeoNames (https://www.geonames.org), used under the Creative Commons Attribution license (CC BY). See https://www.geonames.org/export/ for terms."

    # 1. config.py
    assert config.GEONAMES_ATTRIBUTION == expected_attribution, (
        f"config.GEONAMES_ATTRIBUTION mismatch: {config.GEONAMES_ATTRIBUTION}"
    )

    # 2. THIRD_PARTY_NOTICES.md
    notices_path = os.path.join(repo_dir, "THIRD_PARTY_NOTICES.md")
    assert os.path.exists(notices_path), "THIRD_PARTY_NOTICES.md must exist"
    with open(notices_path, "r", encoding="utf-8") as f:
        notices_text = f.read()

    assert expected_attribution in notices_text, (
        f"THIRD_PARTY_NOTICES.md must contain exact attribution: '{expected_attribution}'"
    )
    assert '> - **Share** — copy' not in notices_text and '> You are free to:' not in notices_text, (
        "THIRD_PARTY_NOTICES.md must NOT frame generic CC deed text as a quote from geonames.org"
    )

    # 3. README.md
    readme_path = os.path.join(repo_dir, "README.md")
    assert os.path.exists(readme_path), "README.md must exist"
    with open(readme_path, "r", encoding="utf-8") as f:
        readme_text = f.read()

    assert "used under the Creative Commons Attribution license (CC BY)" in readme_text, (
        "README.md must contain unversioned CC BY license reference"
    )
    assert '> You are free to:' not in readme_text, (
        "README.md must NOT frame generic CC deed text as a quote from geonames.org"
    )


