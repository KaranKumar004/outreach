"""
test_places.py — Comprehensive unit tests for places.py engine and cascading location system.

Verifies:
1. Data files load properly (countries, admin1, cities, aliases).
2. Exact cascade relationships:
   - India -> Karnataka -> Bengaluru
   - US -> Texas -> Austin
3. City-states (e.g. Singapore 'SG', Monaco 'MC') and blank admin1 regions ('00').
4. Alias search ('Bangalore' -> 'Bengaluru (Bangalore)').
5. Overpass neighborhood query builder & radius scaling by population.
6. Overpass response parser (name:en fallback, unnamed skipped, duplicates merged, ways/relations center coordinates).
7. Cache TTL expiration and corrupt-cache recovery.
8. AreaTarget objects creation with direct preset coordinates.
9. Proof that zero Nominatim requests are triggered while selecting locations or loading neighborhoods.
"""

import os
import sys
import time
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import places
import config


def test_data_files_exist_and_load():
    """Verify that countries, admin1, cities, and aliases files load successfully."""
    countries = places.load_countries()
    assert len(countries) >= 200, f"Expected >= 200 countries, got {len(countries)}"
    assert any(c[0] == "IN" and c[1] == "India" for c in countries)
    assert any(c[0] == "US" and "United States" in c[1] for c in countries)

    # Aliases
    aliases_path = os.path.join(places.DATA_DIR, "aliases.csv")
    assert os.path.exists(aliases_path)
    with open(aliases_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) >= 51, f"Expected >= 50 alias rows, got {len(lines) - 1}"


def test_cascade_relationships_india_and_us():
    """Verify exact cascade: India -> Karnataka -> Bengaluru, and US -> Texas -> Austin."""
    # 1. India -> Karnataka -> Bengaluru
    in_regions = places.load_regions("IN")
    karnataka = next((r for r in in_regions if r[1] == "Karnataka"), None)
    assert karnataka is not None, "Karnataka not found in India regions"
    karnataka_code = karnataka[0]

    karnataka_cities = places.load_cities("IN", karnataka_code)
    assert len(karnataka_cities) > 0, "Expected cities in Karnataka"

    bengaluru = next((c for c in karnataka_cities if "Bengaluru" in c["name"]), None)
    assert bengaluru is not None, "Bengaluru not found in Karnataka"
    assert bengaluru["country_code"] == "IN"
    assert bengaluru["admin1_code"] == karnataka_code
    assert bengaluru["alias"] == "Bangalore"
    assert bengaluru["display_name"] == "Bengaluru (Bangalore)"

    # 2. US -> Texas -> Austin
    us_regions = places.load_regions("US")
    texas = next((r for r in us_regions if r[1] == "Texas"), None)
    assert texas is not None, "Texas not found in US regions"
    texas_code = texas[0]

    texas_cities = places.load_cities("US", texas_code)
    austin = next((c for c in texas_cities if c["name"] == "Austin"), None)
    assert austin is not None, "Austin not found in Texas"
    assert austin["country_code"] == "US"
    assert austin["admin1_code"] == "TX"
    assert austin["population"] > 500_000


def test_city_state_and_blank_admin1():
    """
    If a country has no admin1 regions (city-state), or a city has a blank/'00' admin1,
    skip the Region dropdown (show 'All regions') so the user can still reach the City dropdown.
    """
    # Singapore has no admin1 divisions in gazetteer
    sg_regions = places.load_regions("SG")
    assert len(sg_regions) == 1
    assert sg_regions[0] == ("00", "All regions")

    sg_cities = places.load_cities("SG", "00")
    assert len(sg_cities) > 0
    singapore_city = next((c for c in sg_cities if "Singapore" in c["name"]), None)
    assert singapore_city is not None

    # Blank admin1 filter loads all cities for country
    all_sg_cities = places.load_cities("SG", "")
    assert len(all_sg_cities) == len(sg_cities)


def test_alias_search_and_matching():
    """Typing 'Bangalore' or 'bangalore' must locate Bengaluru."""
    in_cities = places.load_cities("IN", "19")

    # Search function
    results = places.search_cities("Bangalore", in_cities)
    assert len(results) >= 1
    assert results[0]["name"] == "Bengaluru"

    # Exact alias locator
    found = places.find_city_by_alias("bangalore", in_cities)
    assert found is not None
    assert found["name"] == "Bengaluru"
    assert found["display_name"] == "Bengaluru (Bangalore)"

    # ASCII search
    ascii_results = places.search_cities("bengaluru", in_cities)
    assert any(c["name"] == "Bengaluru" for c in ascii_results)


def test_overpass_query_builder_and_radius():
    """Radius scales with population according to config: >5M -> 25km, >1M -> 15km, >250k -> 10km, else 6km."""
    assert places.get_city_radius(10_000_000) == 25_000
    assert places.get_city_radius(2_000_000) == 15_000
    assert places.get_city_radius(500_000) == 10_000
    assert places.get_city_radius(50_000) == 6_000

    q = places.build_neighborhood_overpass_query(30.2672, -97.7431, 15000)
    assert "around:15000,30.26720,-97.74310" in q
    assert 'node["place"~"^(suburb|neighbourhood|quarter)$"]' in q
    assert 'way["place"~"^(suburb|neighbourhood|quarter)$"]' in q
    assert 'relation["place"~"^(suburb|neighbourhood|quarter)$"]' in q
    assert "out center tags;" in q


def test_overpass_response_parser():
    """Parses elements with name:en fallback, unnamed skipped, duplicates merged, ways/relations center."""
    mock_elements = [
        # 1. Standard node with name
        {
            "type": "node", "id": 101, "lat": 30.26, "lon": -97.74,
            "tags": {"place": "suburb", "name": "Downtown"}
        },
        # 2. Way with center and name:en preference
        {
            "type": "way", "id": 102,
            "center": {"lat": 30.25, "lon": -97.75},
            "tags": {"place": "neighbourhood", "name": "South Congress Alt", "name:en": "South Congress"}
        },
        # 3. Unnamed element (must be skipped)
        {
            "type": "node", "id": 103, "lat": 30.27, "lon": -97.73,
            "tags": {"place": "quarter"}
        },
        # 4. Duplicate name with same rounded coordinates (must be merged)
        {
            "type": "node", "id": 104, "lat": 30.26001, "lon": -97.74002,
            "tags": {"place": "suburb", "name": "Downtown"}
        },
        # 5. Relation with center
        {
            "type": "relation", "id": 105,
            "center": {"lat": 30.30, "lon": -97.72},
            "tags": {"place": "suburb", "name": "Mueller"}
        }
    ]

    parsed = places.parse_neighborhood_elements(mock_elements)
    names = [p["name"] for p in parsed]

    assert names == ["Downtown", "Mueller", "South Congress"]
    assert len(parsed) == 3

    # Check way center coordinate extraction
    soco = next(p for p in parsed if p["name"] == "South Congress")
    assert soco["latitude"] == 30.25
    assert soco["longitude"] == -97.75


def test_cache_ttl_and_corrupt_cache_recovery(tmp_path):
    """Verifies cache reads fresh files, rejects expired TTL, and gracefully recovers from corrupt JSON."""
    geonameid = "9999999"

    # Mock cache path
    with patch("places._get_cache_filepath") as mock_path:
        cache_file = os.path.join(tmp_path, f"{geonameid}.json")
        mock_path.return_value = cache_file

        # 1. Fresh cache
        fresh_data = [
            {"name": "Fresh Suburb", "latitude": 12.34, "longitude": 56.78, "place_type": "suburb"}
        ]
        places.save_cached_neighborhoods(geonameid, "Test City", fresh_data)
        loaded = places.load_cached_neighborhoods(geonameid)
        assert loaded == fresh_data

        # 2. Expired TTL (31 days ago)
        expired_payload = {
            "geonameid": geonameid,
            "cached_at": time.time() - (31 * 86400),
            "neighborhoods": fresh_data
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(expired_payload, f)

        assert places.load_cached_neighborhoods(geonameid) is None, "Expired cache must return None!"

        # 3. Corrupted cache file
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write("{corrupt json text !@@#}")

        assert places.load_cached_neighborhoods(geonameid) is None, "Corrupt cache must recover and return None!"


def test_area_targets_preserves_coordinates_without_nominatim():
    """AreaTarget objects for city_center and osm_neighborhood carry coordinates directly."""
    mock_city = {
        "geonameid": "123", "name": "Austin", "country_code": "US",
        "latitude": 30.2672, "longitude": -97.7431
    }
    mock_neigh = {
        "name": "Barton Hills", "latitude": 30.2500, "longitude": -97.7800
    }

    center_target = places.create_city_center_target(mock_city)
    assert center_target.source == "city_center"
    assert center_target.latitude == 30.2672
    assert center_target.longitude == -97.7431
    assert center_target.country_code == "US"

    neigh_target = places.create_neighborhood_target(mock_neigh, "US")
    assert neigh_target.source == "osm_neighborhood"
    assert neigh_target.latitude == 30.2500
    assert neigh_target.longitude == -97.7800


def test_proof_no_nominatim_called_during_dropdowns_and_neighborhood_loading():
    """
    CRITICAL PROOF: Verify that OpenStreetMap Nominatim is NEVER invoked
    when loading countries, regions, cities, or discovering neighborhoods.
    """
    with patch("leadcore.geocode_location") as mock_nominatim:
        # 1. Load countries
        _ = places.load_countries()

        # 2. Load regions
        _ = places.load_regions("US")

        # 3. Load cities
        us_cities = places.load_cities("US", "TX")

        # 4. Search and filter by alias
        _ = places.search_cities("Austin", us_cities)

        # 5. Discover neighborhoods with mocked Overpass
        mock_city = {
            "geonameid": "4671654", "name": "Austin", "country_code": "US",
            "latitude": 30.2672, "longitude": -97.7431, "population": 974447
        }
        with patch("places.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "elements": [
                    {"type": "node", "id": 1, "lat": 30.26, "lon": -97.74, "tags": {"name": "Downtown"}}
                ]
            }
            mock_post.return_value = mock_resp

            _ = places.load_or_fetch_neighborhoods(mock_city, "test@domain.com")

        # Assert zero calls to Nominatim
        assert mock_nominatim.call_count == 0, (
            f"Nominatim geocode_location was called {mock_nominatim.call_count} times! "
            "Policy strictly forbids Nominatim calls during dropdown selection and neighborhood loading."
        )


def test_validate_manual_place():
    """Verifies manual place validation rules with and without selected city."""
    # 1. With selected city: can be empty or any string
    valid_empty_city, err = places.validate_manual_place("", has_selected_city=True)
    assert valid_empty_city is True
    assert err == ""

    valid_area_city, err = places.validate_manual_place("Downtown", has_selected_city=True)
    assert valid_area_city is True
    assert err == ""

    # 2. Without selected city: requires >= 2 comma-separated non-empty parts
    invalid_empty, err = places.validate_manual_place("", has_selected_city=False)
    assert invalid_empty is False
    assert "select a city or enter a place" in err.lower()

    invalid_single, err = places.validate_manual_place("Downtown", has_selected_city=False)
    assert invalid_single is False
    assert "at least two comma-separated parts" in err.lower()

    valid_two, err = places.validate_manual_place("Downtown, Austin", has_selected_city=False)
    assert valid_two is True
    assert err == ""

    valid_three, err = places.validate_manual_place("Downtown, Austin, Texas", has_selected_city=False)
    assert valid_three is True
    assert err == ""


def test_build_manual_geocode_query():
    """Verifies geocoding query synthesis and country code propagation."""
    city_dict = {"name": "Austin", "country_code": "US"}

    # City selected: combines manual area + city + region + country
    q1, cc1 = places.build_manual_geocode_query("Downtown", city=city_dict, region_name="Texas", country_name="United States")
    assert q1 == "Downtown, Austin, Texas, United States"
    assert cc1 == "US"

    # City selected without manual area
    q2, cc2 = places.build_manual_geocode_query("", city=city_dict, region_name="Texas", country_name="United States")
    assert q2 == "Austin, Texas, United States"
    assert cc2 == "US"

    # No city selected: preserves verbatim place query
    q3, cc3 = places.build_manual_geocode_query("Downtown, Austin, Texas")
    assert q3 == "Downtown, Austin, Texas"
    assert cc3 == ""
