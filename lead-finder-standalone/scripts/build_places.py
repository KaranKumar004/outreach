"""
build_places.py — Build-time geographic data pipeline for LocalLeads Kit.

Downloads raw gazetteer data from GeoNames:
- countryInfo.txt -> data/countries.csv
- admin1CodesASCII.txt -> data/admin1.csv
- cities5000.zip -> data/cities.csv.gz

Sorts cities by population descending within each region.
Builds data/aliases.csv with 50+ verified alias pairs (India first, then global).
Calculates and reports data footprints, load times, and max cities per region.
"""

import os
import io
import csv
import gzip
import time
import zipfile
import urllib.request
from typing import Dict, List, Tuple, Set, Optional

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

GEONAMES_BASE = "https://download.geonames.org/export/dump"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LocalLeadsKitPlacesBuilder/1.0"


def download_file(url: str) -> bytes:
    print(f"[DOWNLOAD] Fetching {url}...")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    print(f"[DOWNLOAD] Fetched {len(data):,} bytes.")
    return data


# Hand-curated major aliases (canonical_name, alias, country_code)
RAW_ALIASES = [
    # India (primary)
    ("Bengaluru", "Bangalore", "IN"),
    ("Mumbai", "Bombay", "IN"),
    ("Kolkata", "Calcutta", "IN"),
    ("Chennai", "Madras", "IN"),
    ("Pune", "Poona", "IN"),
    ("Gurugram", "Gurgaon", "IN"),
    ("Mysuru", "Mysore", "IN"),
    ("Thiruvananthapuram", "Trivandrum", "IN"),
    ("Visakhapatnam", "Vizag", "IN"),
    ("Kochi", "Cochin", "IN"),
    ("Vadodara", "Baroda", "IN"),
    ("Puducherry", "Pondicherry", "IN"),
    ("Prayagraj", "Allahabad", "IN"),
    ("Varanasi", "Benares", "IN"),
    ("Varanasi", "Banaras", "IN"),
    ("Kozhikode", "Calicut", "IN"),
    ("Mangaluru", "Mangalore", "IN"),
    ("Belagavi", "Belgaum", "IN"),
    ("Kalaburagi", "Gulbarga", "IN"),
    ("Ballari", "Bellary", "IN"),
    ("Vijayapura", "Bijapur", "IN"),
    ("Shivamogga", "Shimoga", "IN"),
    ("Tumakuru", "Tumkur", "IN"),
    ("Hubballi", "Hubli", "IN"),
    ("Hosapete", "Hospet", "IN"),
    ("Tiruchirappalli", "Trichy", "IN"),
    ("Thanjavur", "Tanjore", "IN"),
    ("Tirunelveli", "Tinnevelly", "IN"),
    ("Udhagamandalam", "Ooty", "IN"),
    ("Kannur", "Cannanore", "IN"),
    ("Kollam", "Quilon", "IN"),
    ("Alappuzha", "Alleppey", "IN"),
    ("Thrissur", "Trichur", "IN"),
    ("Palakkad", "Palghat", "IN"),
    ("Thalassery", "Tellicherry", "IN"),
    ("Panaji", "Panjim", "IN"),
    ("Guwahati", "Gauhati", "IN"),
    ("Cuttack", "Kataka", "IN"),
    ("Bhubaneswar", "Bhubaneshwar", "IN"),
    ("Jalandhar", "Jullundur", "IN"),
    ("Ayodhya", "Faizabad", "IN"),
    ("Chhatrapati Sambhajinagar", "Aurangabad", "IN"),
    ("Dharashiv", "Osmanabad", "IN"),
    ("Narmadapuram", "Hoshangabad", "IN"),
    ("Secunderabad", "Sikandarabad", "IN"),
    # Global Major Aliases
    ("Beijing", "Peking", "CN"),
    ("Guangzhou", "Canton", "CN"),
    ("Ho Chi Minh City", "Saigon", "VN"),
    ("Yangon", "Rangoon", "MM"),
    ("Kyiv", "Kiev", "UA"),
    ("Saint Petersburg", "Leningrad", "RU"),
    ("Gdansk", "Danzig", "PL"),
    ("Wroclaw", "Breslau", "PL"),
    ("Izmir", "Smyrna", "TR"),
    ("Istanbul", "Constantinople", "TR"),
    ("Kinshasa", "Leopoldville", "CD"),
    ("Harare", "Salisbury", "ZW"),
    ("Maputo", "Lourenco Marques", "MZ"),
    ("Banjul", "Bathurst", "GM"),
    ("Jakarta", "Batavia", "ID"),
    ("Tokyo", "Edo", "JP"),
    ("The Hague", "'s-Gravenhage", "NL"),
]


def build():
    start_time = time.time()

    # 1. Countries
    country_bytes = download_file(f"{GEONAMES_BASE}/countryInfo.txt")
    country_rows = []
    for line in country_bytes.decode("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) > 4:
            code = parts[0].strip().upper()
            name = parts[4].strip()
            if code and name:
                country_rows.append((code, name))

    country_rows.sort(key=lambda x: x[1])
    countries_csv_path = os.path.join(DATA_DIR, "countries.csv")
    with open(countries_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["country_code", "country_name"])
        writer.writerows(country_rows)
    print(f"[DATA] Wrote {len(country_rows)} countries to {countries_csv_path}")

    # 2. Admin1
    admin1_bytes = download_file(f"{GEONAMES_BASE}/admin1CodesASCII.txt")
    admin1_rows = []
    for line in admin1_bytes.decode("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            full_code = parts[0].strip()
            name = parts[1].strip()
            ascii_name = parts[2].strip()
            if "." in full_code:
                c_code, a1_code = full_code.split(".", 1)
                admin1_rows.append((c_code.upper(), a1_code, name, ascii_name))

    admin1_rows.sort(key=lambda x: (x[0], x[2]))
    admin1_csv_path = os.path.join(DATA_DIR, "admin1.csv")
    with open(admin1_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["country_code", "admin1_code", "name", "ascii_name"])
        writer.writerows(admin1_rows)
    print(f"[DATA] Wrote {len(admin1_rows)} admin1 records to {admin1_csv_path}")

    # 3. Cities 5000
    cities_zip_bytes = download_file(f"{GEONAMES_BASE}/cities5000.zip")
    with zipfile.ZipFile(io.BytesIO(cities_zip_bytes)) as zf:
        with zf.open("cities5000.txt") as cf:
            cities_text = cf.read().decode("utf-8", errors="ignore")

    raw_city_lines = cities_text.splitlines()
    print(f"[DATA] Parsing {len(raw_city_lines):,} raw cities from cities5000...")

    # Build quick lookup of city names in GeoNames for alias verification
    geoname_city_names = set()
    parsed_cities = []

    for line in raw_city_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 15:
            continue
        try:
            geonameid = parts[0].strip()
            name = parts[1].strip()
            ascii_name = parts[2].strip()
            lat = float(parts[4].strip())
            lon = float(parts[5].strip())
            country_code = parts[8].strip().upper()
            admin1_code = parts[10].strip()
            population = int(parts[14].strip()) if parts[14].strip().isdigit() else 0

            geoname_city_names.add(name.lower())
            geoname_city_names.add(ascii_name.lower())

            parsed_cities.append({
                "geonameid": geonameid,
                "name": name,
                "ascii_name": ascii_name,
                "country_code": country_code,
                "admin1_code": admin1_code,
                "latitude": lat,
                "longitude": lon,
                "population": population,
                "alias": ""
            })
        except Exception:
            continue

    # 4. Verify and build aliases.csv
    verified_aliases = []
    alias_map: Dict[Tuple[str, str], str] = {}  # (canonical_name_lower, country_code) -> alias

    for canonical, alias, c_code in RAW_ALIASES:
        can_lower = canonical.lower()
        alias_lower = alias.lower()

        # Check if canonical exists in GeoNames
        if can_lower in geoname_city_names:
            verified_aliases.append((canonical, alias, c_code))
            alias_map[(can_lower, c_code)] = alias
        elif alias_lower in geoname_city_names:
            # If GeoNames had the alias as primary name, swap them!
            verified_aliases.append((alias, canonical, c_code))
            alias_map[(alias_lower, c_code)] = canonical
        else:
            print(f"[ALIAS] Warning: '{canonical}' / '{alias}' not found in cities5000. Skipping.")

    print(f"[DATA] Verified {len(verified_aliases)} aliases (target >= 50).")

    # Write aliases.csv
    aliases_csv_path = os.path.join(DATA_DIR, "aliases.csv")
    with open(aliases_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["canonical_name", "alias", "country_code"])
        writer.writerows(verified_aliases)
    print(f"[DATA] Wrote {len(verified_aliases)} aliases to {aliases_csv_path}")

    # Attach aliases to parsed cities
    for city in parsed_cities:
        key = (city["name"].lower(), city["country_code"])
        key_ascii = (city["ascii_name"].lower(), city["country_code"])
        if key in alias_map:
            city["alias"] = alias_map[key]
        elif key_ascii in alias_map:
            city["alias"] = alias_map[key_ascii]

    # Sort cities by population descending within each region (country_code, admin1_code)
    parsed_cities.sort(key=lambda c: (c["country_code"], c["admin1_code"], -c["population"]))

    # Write data/cities.csv.gz
    cities_gz_path = os.path.join(DATA_DIR, "cities.csv.gz")
    fieldnames = [
        "geonameid", "name", "ascii_name", "alias",
        "country_code", "admin1_code", "latitude", "longitude", "population"
    ]
    with gzip.open(cities_gz_path, "wt", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in parsed_cities:
            writer.writerow(c)

    # 5. Measure load time & metrics
    load_start = time.time()
    loaded_count = 0
    region_city_counts: Dict[Tuple[str, str], int] = {}
    with gzip.open(cities_gz_path, "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            loaded_count += 1
            reg_key = (r["country_code"], r["admin1_code"])
            region_city_counts[reg_key] = region_city_counts.get(reg_key, 0) + 1
    load_time = time.time() - load_start

    max_region, max_cities = max(region_city_counts.items(), key=lambda x: x[1])

    # Sizes
    countries_sz = os.path.getsize(countries_csv_path)
    admin1_sz = os.path.getsize(admin1_csv_path)
    aliases_sz = os.path.getsize(aliases_csv_path)
    cities_gz_sz = os.path.getsize(cities_gz_path)
    total_data_sz = countries_sz + admin1_sz + aliases_sz + cities_gz_sz

    print("\n" + "=" * 60)
    print("GEONAMES DATA PIPELINE REPORT")
    print("=" * 60)
    print(f"Total Countries: {len(country_rows)}")
    print(f"Total Admin1 Regions: {len(admin1_rows)}")
    print(f"Total Cities: {loaded_count:,}")
    print(f"Total Verified Aliases: {len(verified_aliases)}")
    print(f"Largest single region: {max_region[0]}.{max_region[1]} with {max_cities:,} cities")
    print(f"Load time for cities.csv.gz: {load_time * 1000:.1f} ms ({load_time:.3f} s)")
    print(f"countries.csv size: {countries_sz:,} bytes")
    print(f"admin1.csv size: {admin1_sz:,} bytes")
    print(f"aliases.csv size: {aliases_sz:,} bytes")
    print(f"cities.csv.gz size: {cities_gz_sz:,} bytes ({cities_gz_sz / 1024 / 1024:.2f} MB)")
    print(f"Total bundled data size: {total_data_sz:,} bytes ({total_data_sz / 1024 / 1024:.2f} MB)")
    print(f"Pipeline finished in {time.time() - start_time:.2f} s")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    build()
