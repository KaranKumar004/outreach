"""
make_zip.py — Packages LocalLeads Kit into distribution zip archive.

Includes:
- app.py, leadcore.py, places.py, ui.py, config.py
- .streamlit/config.toml
- data/ (countries.csv, admin1.csv, aliases.csv, cities.csv.gz)
- static/fonts/ (manrope-latin.woff2, jetbrains-mono-latin.woff2, license texts)
- sample/ (sample_leads_fictional.csv)
- run.bat, run.sh, run.command
- requirements.txt, README.md, CHANGELOG.md, LICENSE.txt, THIRD_PARTY_NOTICES.md

Excludes:
- .gitignore
- .venv, venv, __pycache__, .pytest_cache
- tests/, scripts/, marketing/, assets/
- requirements-dev.txt, make_zip.py
- lead_history.json, verified_emails_cache.json, settings.json, places_cache/
- exported CSVs (*.csv at root)
- .env, .env.local, dist/, build/

Preserves executable permissions (0o755) for run.sh and run.command.
"""

import os
import sys
import zipfile
import stat

import config

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

KIT_NAME = "LocalLeads-Kit"
ZIP_FILENAME = f"{KIT_NAME}-v{config.VERSION}.zip"

EXCLUDED_DIRS = {
    ".venv", "venv", "env",
    "__pycache__", ".pytest_cache",
    "tests", "dist", "build",
    "scripts", "bin", "marketing", "assets",
    "test-results", "playwright-report",
    ".agent", "skills", "screenshots",
    "places_cache", ".places_cache",
    "scratch", "docs",
}

EXCLUDED_FILES = {
    ".gitignore",
    "lead_history.json",
    "verified_emails_cache.json",
    "settings.json",
    "requirements-dev.txt",
    "make_zip.py",
    ".env",
    ".env.local",
    "localleads_thumbnail.jpg",
    "localleads_cover.jpg",
}


def should_include(rel_path: str) -> bool:
    clean_path = rel_path.replace("\\", "/")
    parts = clean_path.split("/")
    filename = parts[-1]

    if filename in EXCLUDED_FILES:
        return False

    # Check directory exclusions
    for p in parts[:-1]:
        if p in EXCLUDED_DIRS:
            return False
        if p.startswith(".") and p != ".streamlit":
            return False

    # Bundled data files
    if parts[0] == "data":
        return filename in ("countries.csv", "admin1.csv", "aliases.csv", "cities.csv.gz")

    # Sample dataset
    if parts[0] == "sample":
        return filename == "sample_leads_fictional.csv"

    # Root level exported CSVs or build files
    _, ext = os.path.splitext(filename)
    if ext.lower() in (".csv", ".pyc", ".pyo", ".tmp", ".zip"):
        return False

    # Exclude hidden files
    if len(parts) == 1 and filename.startswith("."):
        return False

    return True


def package_kit():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(base_dir, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    zip_path = os.path.join(dist_dir, ZIP_FILENAME)

    print(f"[PACKAGING] {KIT_NAME} into {zip_path}...")

    files_added = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(base_dir):
            # Prune excluded directories in-place
            dirs[:] = [
                d for d in dirs
                if d not in EXCLUDED_DIRS and (not d.startswith(".") or d == ".streamlit")
            ]

            for file in sorted(files):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, base_dir)

                if should_include(rel_path):
                    clean_rel_path = rel_path.replace("\\", "/")
                    archive_path = f"{KIT_NAME}/{clean_rel_path}"
                    zinfo = zipfile.ZipInfo.from_file(full_path, arcname=archive_path)
                    zinfo.compress_type = zipfile.ZIP_DEFLATED

                    # Preserve executable permissions (0o755) for POSIX launchers
                    if clean_rel_path in ("run.sh", "run.command"):
                        zinfo.external_attr = (stat.S_IFREG | 0o755) << 16

                    with open(full_path, "rb") as f:
                        zf.writestr(zinfo, f.read())
                    files_added.append(archive_path)

    print(f"[SUCCESS] Packaged {len(files_added)} files:")
    for f in sorted(files_added):
        print(f"  + {f}")

    total_size = os.path.getsize(zip_path)
    print(f"\nFinal archive size: {total_size:,} bytes\n")
    return zip_path, files_added, total_size


if __name__ == "__main__":
    package_kit()
