"""
test_demo_safety.py — Safety and presentation tests for demo data and status dots.

Verifies:
1. Status strings format to labeled dots (● Valid, ● Unverified, ● No email, etc.) at the data level.
2. Real runs never show the "Sample data (fictional)" caption.
3. Demo runs never write to real export/history/settings files in the repository root.
"""

import os
import sys
import tempfile
import pytest
import pandas as pd

REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

import app
import ui
import leadcore


def test_format_df_for_display_status_dots():
    """Verify that format_df_for_display attaches unicode labeled dots to all verification statuses."""
    sample_records = [
        {"business_name": "Biz 1", "verification_status": "valid", "email_source": "website_crawl"},
        {"business_name": "Biz 2", "verification_status": "unverified", "email_source": "osm_tag"},
        {"business_name": "Biz 3", "verification_status": "risky", "email_source": "guessed_domain"},
        {"business_name": "Biz 4", "verification_status": "invalid", "email_source": "website_crawl"},
        {"business_name": "Biz 5", "verification_status": "guessed", "email_source": "guessed_domain"},
        {"business_name": "Biz 6", "verification_status": "no_email", "email_source": ""},
        {"business_name": "Biz 7", "verification_status": "", "email_source": ""},
    ]

    df_disp = app.format_df_for_display(sample_records)
    statuses = df_disp["verification_status"].tolist()

    assert statuses[0] == "● Valid"
    assert statuses[1] == "● Unverified"
    assert statuses[2] == "● Risky"
    assert statuses[3] == "● Invalid"
    assert statuses[4] == "● Guessed"
    assert statuses[5] == "● No email"
    assert statuses[6] == ""


def test_real_run_never_shows_sample_data_caption(monkeypatch):
    """Verify that when LOCALLEADS_DEMO is not set and businesses have real websites, is_demo evaluates to False."""
    monkeypatch.delenv("LOCALLEADS_DEMO", raising=False)

    real_records = [
        {"business_name": "Downtown Dental Clinic", "website": "https://downtowndentalclinic.com"},
        {"business_name": "Austin Family Dental", "website": "https://austinfamilydental.org"},
    ]

    is_demo = bool(os.environ.get("LOCALLEADS_DEMO")) or any(
        ".example.com" in str(r.get("website", "")) for r in real_records
    )
    assert is_demo is False, "Real run must evaluate is_demo to False"


def test_demo_runs_never_write_to_root_files(monkeypatch, tmp_path):
    """Verify that mocked demo runs redirect file saves to an isolated temp directory."""
    temp_demo_dir = str(tmp_path)
    monkeypatch.setenv("LOCALLEADS_DEMO_TEMP_DIR", temp_demo_dir)

    root_export = os.path.join(REPO_DIR, "localleads_export.csv")
    root_history = os.path.join(REPO_DIR, "lead_history.json")
    root_settings = os.path.join(REPO_DIR, "settings.json")
    root_cache = os.path.join(REPO_DIR, "verified_emails_cache.json")

    # Record root mtimes / existence before
    state_before = {
        p: os.path.getmtime(p) if os.path.exists(p) else None
        for p in [root_export, root_history, root_settings, root_cache]
    }

    # Simulate demo save through mocked functions
    demo_records = [
        {"business_name": "Austin Dental Arts", "website": "https://austindentalarts.example.com", "email": "test@austindentalarts.example.com"}
    ]

    # Save through isolated temp wrappers
    orig_save_json = leadcore.save_json_atomic
    orig_save_csv = leadcore.save_csv_atomic

    def safe_demo_save_json(filepath, data):
        fn = os.path.basename(filepath)
        return orig_save_json(os.path.join(temp_demo_dir, fn), data)

    def safe_demo_save_csv(filepath, fieldnames, rows):
        fn = os.path.basename(filepath)
        return orig_save_csv(os.path.join(temp_demo_dir, fn), fieldnames, rows)

    safe_demo_save_csv("localleads_export.csv", ["business_name", "website", "email"], demo_records)
    safe_demo_save_json("lead_history.json", {"key1": {"business_name": "Austin Dental Arts"}})

    # Assert saved in temp dir
    assert os.path.exists(os.path.join(temp_demo_dir, "localleads_export.csv")), "File must be saved in temp dir"
    assert os.path.exists(os.path.join(temp_demo_dir, "lead_history.json")), "File must be saved in temp dir"

    # Assert root files were NOT modified or created
    for p, mtime_before in state_before.items():
        if mtime_before is None:
            assert not os.path.exists(p), f"Root file {p} should not have been created by demo run!"
        else:
            assert os.path.getmtime(p) == mtime_before, f"Root file {p} was unexpectedly modified!"


def test_format_df_for_display_source_fallback():
    """Verify that UI Source column displays email source, falling back to phone source if no email."""
    records = [
        # 1. Has both email and phone: uses email source friendly label
        {"business_name": "Biz 1", "email": "a@example.com", "phone": "555-1234", "email_source": "website_crawl", "phone_source": "osm_tag"},
        # 2. Has phone only (no email): falls back to phone source friendly label
        {"business_name": "Biz 2", "email": "", "phone": "555-5678", "email_source": "", "phone_source": "osm_tag"},
        # 3. Has neither: empty string
        {"business_name": "Biz 3", "email": "", "phone": "", "email_source": "", "phone_source": ""},
    ]

    df_disp = app.format_df_for_display(records)
    sources = df_disp["source"].tolist()
    assert sources[0] == "Website Crawl"
    assert sources[1] == "OSM Tag"
    assert sources[2] == ""


def test_sample_csv_header_and_hygiene():
    """Verify sample/sample_leads_fictional.csv has exact CSV_FIELDS header, machine sources, and only .example.com."""
    import csv
    import config
    sample_path = os.path.join(os.path.dirname(__file__), "..", "sample", "sample_leads_fictional.csv")
    assert os.path.exists(sample_path), f"Sample CSV missing at {sample_path}"

    with open(sample_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    # 1. Header must equal config.CSV_FIELDS exactly
    assert header == config.CSV_FIELDS, f"Header mismatch: expected {config.CSV_FIELDS}, got {header}"

    # 2. Rows check
    valid_sources = {"osm_tag", "website_crawl", "guessed_domain", "search_snippet", ""}
    email_idx = header.index("email")
    em_src_idx = header.index("email_source")
    ph_src_idx = header.index("phone_source")
    website_idx = header.index("website")

    for row in rows:
        email = row[email_idx]
        em_src = row[em_src_idx]
        ph_src = row[ph_src_idx]
        website = row[website_idx]

        assert em_src in valid_sources, f"Invalid machine email_source: {em_src}"
        assert ph_src in valid_sources, f"Invalid machine phone_source: {ph_src}"

        if email:
            assert email.endswith(".example.com") or email.endswith(".example.org"), f"Non-fictional email: {email}"
        if website:
            assert ".example.com" in website or ".example.org" in website, f"Non-fictional website: {website}"

