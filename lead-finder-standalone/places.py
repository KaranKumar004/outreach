"""
places.py — Pure logic engine for geographic places, cascading lookups, and neighborhood discovery.

Zero Streamlit imports.
Includes:
- Bundled GeoNames data loaders (countries, admin1, cities with population sort & aliases)
- Handling of city-states and blank admin1 regions
- Local search matching by name, ascii_name, and alias (e.g. "Bangalore" -> "Bengaluru (Bangalore)")
- Overpass neighborhood query builder with population-scaled search radii
- Resilient Overpass neighborhood fetching with mirror failover and exponential backoff
- 30-day atomic file cache with corrupt file tolerance
- AreaTarget object factory with direct coordinate preservation (zero Nominatim calls for bundled places)
"""

import os
import csv
import gzip
import time
import json
import logging
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional, Any, Set

import requests
import config

logger = logging.getLogger("places")

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "data"))


@dataclass
class AreaTarget:
    """Represents a targeted geographical search location."""
    label: str
    latitude: float
    longitude: float
    country_code: str
    source: str  # "city_center", "osm_neighborhood", "fallback_nominatim"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# In-memory caches for fast sub-millisecond cascading dropdown operations
_COUNTRIES_CACHE: Optional[List[Tuple[str, str]]] = None
_ADMIN1_CACHE: Optional[Dict[str, List[Tuple[str, str]]]] = None  # country_code -> [(admin1_code, name)]
_CITIES_BY_COUNTRY: Optional[Dict[str, List[Dict[str, Any]]]] = None  # country_code -> [city_dict]


def load_countries() -> List[Tuple[str, str]]:
    """
    Returns sorted list of (country_code, country_name) tuples.
    Loaded once and cached in memory.
    """
    global _COUNTRIES_CACHE
    if _COUNTRIES_CACHE is not None:
        return _COUNTRIES_CACHE

    countries_path = os.path.join(DATA_DIR, "countries.csv")
    results = []
    if os.path.exists(countries_path):
        with open(countries_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                code = r.get("country_code", "").strip()
                name = r.get("country_name", "").strip()
                if code and name:
                    results.append((code, name))

    results.sort(key=lambda x: x[1])
    _COUNTRIES_CACHE = results
    return results


def load_regions(country_code: str) -> List[Tuple[str, str]]:
    """
    Returns sorted list of (admin1_code, region_name) tuples for the specified country.
    If the country has no admin1 regions or is a city-state, returns [("00", "All regions")].
    """
    global _ADMIN1_CACHE
    if _ADMIN1_CACHE is None:
        _ADMIN1_CACHE = {}
        admin1_path = os.path.join(DATA_DIR, "admin1.csv")
        if os.path.exists(admin1_path):
            with open(admin1_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    cc = r.get("country_code", "").strip().upper()
                    a1 = r.get("admin1_code", "").strip()
                    name = r.get("name", "").strip()
                    if cc and a1 and name:
                        if cc not in _ADMIN1_CACHE:
                            _ADMIN1_CACHE[cc] = []
                        _ADMIN1_CACHE[cc].append((a1, name))

        for cc in _ADMIN1_CACHE:
            _ADMIN1_CACHE[cc].sort(key=lambda x: x[1])

    c_upper = country_code.strip().upper()
    regions = _ADMIN1_CACHE.get(c_upper, [])
    if not regions:
        # City-state or country without admin1 divisions
        return [("00", "All regions")]
    return regions


def _ensure_cities_loaded() -> None:
    """Loads all cities from cities.csv.gz into in-memory partition dictionary."""
    global _CITIES_BY_COUNTRY
    if _CITIES_BY_COUNTRY is not None:
        return

    _CITIES_BY_COUNTRY = {}
    cities_path = os.path.join(DATA_DIR, "cities.csv.gz")
    if not os.path.exists(cities_path):
        return

    with gzip.open(cities_path, "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            cc = r.get("country_code", "").strip().upper()
            if not cc:
                continue

            name = r.get("name", "").strip()
            ascii_name = r.get("ascii_name", "").strip()
            alias = r.get("alias", "").strip()

            display_name = f"{name} ({alias})" if alias and alias.lower() != name.lower() else name

            try:
                pop = int(r.get("population", 0))
            except Exception:
                pop = 0

            try:
                lat = float(r.get("latitude", 0.0))
                lon = float(r.get("longitude", 0.0))
            except Exception:
                lat, lon = 0.0, 0.0

            city_obj = {
                "geonameid": r.get("geonameid", "").strip(),
                "name": name,
                "ascii_name": ascii_name,
                "alias": alias,
                "display_name": display_name,
                "country_code": cc,
                "admin1_code": r.get("admin1_code", "").strip(),
                "latitude": lat,
                "longitude": lon,
                "population": pop,
            }

            if cc not in _CITIES_BY_COUNTRY:
                _CITIES_BY_COUNTRY[cc] = []
            _CITIES_BY_COUNTRY[cc].append(city_obj)


def load_cities(country_code: str, admin1_code: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns cities in country_code, optionally filtered by admin1_code.
    If admin1_code is None, empty, or '00', returns all cities in the country.
    Cities are returned sorted by population descending.
    """
    _ensure_cities_loaded()
    if _CITIES_BY_COUNTRY is None:
        return []

    c_upper = country_code.strip().upper()
    country_cities = _CITIES_BY_COUNTRY.get(c_upper, [])

    if not admin1_code or admin1_code.strip() in ("", "00", "All regions"):
        return country_cities

    a1_target = admin1_code.strip()
    return [c for c in country_cities if c["admin1_code"] == a1_target or c["admin1_code"] in ("", "00")]


def search_cities(query: str, cities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filters cities matching query against name, ascii_name, and alias (case-insensitive).
    """
    q = query.strip().lower()
    if not q:
        return cities

    matches = []
    for c in cities:
        if (
            q in c["name"].lower()
            or q in c["ascii_name"].lower()
            or (c["alias"] and q in c["alias"].lower())
            or q in c["display_name"].lower()
        ):
            matches.append(c)
    return matches


def find_city_by_alias(query: str, cities: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Directly locates a city where query matches the alias or primary name exactly.
    """
    q = query.strip().lower()
    for c in cities:
        if c["alias"] and c["alias"].lower() == q:
            return c
        if c["name"].lower() == q or c["ascii_name"].lower() == q:
            return c
    return None


def get_city_radius(population: int) -> int:
    """Returns search radius in meters based on city population."""
    for min_pop, radius_m in config.POPULATION_RADIUS_MAP:
        if population >= min_pop:
            return radius_m
    return 6_000


def build_neighborhood_overpass_query(lat: float, lon: float, radius: int) -> str:
    """
    Constructs an Overpass QL query to fetch suburbs, neighbourhoods, and quarters
    with node, way, and relation center coordinates.
    """
    return f"""[out:json][timeout:25];
(
  node["place"~"^(suburb|neighbourhood|quarter)$"](around:{radius},{lat:.5f},{lon:.5f});
  way["place"~"^(suburb|neighbourhood|quarter)$"](around:{radius},{lat:.5f},{lon:.5f});
  relation["place"~"^(suburb|neighbourhood|quarter)$"](around:{radius},{lat:.5f},{lon:.5f});
);
out center tags;
"""


def parse_neighborhood_elements(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Parses Overpass elements into clean neighborhood dictionaries:
    - Prefers name:en then name
    - Skips unnamed elements
    - Resolves node coordinates and way/relation center coordinates
    - Deduplicates by normalized name and rounded coordinates
    - Sorts alphabetically
    - Caps at 1000 items
    """
    seen: Set[Tuple[str, float, float]] = set()
    neighborhoods = []

    for elem in elements:
        tags = elem.get("tags", {})
        name = tags.get("name:en") or tags.get("name")
        if not name:
            continue
        name = str(name).strip()
        if not name:
            continue

        # Extract coordinates
        if elem.get("type") == "node":
            lat = elem.get("lat")
            lon = elem.get("lon")
        else:
            center = elem.get("center", {})
            lat = center.get("lat")
            lon = center.get("lon")

        if lat is None or lon is None:
            continue

        try:
            f_lat = float(lat)
            f_lon = float(lon)
        except Exception:
            continue

        # Deduplicate on normalized name and rounded coordinates (~110m resolution)
        norm_key = (name.lower(), round(f_lat, 3), round(f_lon, 3))
        if norm_key in seen:
            continue
        seen.add(norm_key)

        neighborhoods.append({
            "name": name,
            "latitude": f_lat,
            "longitude": f_lon,
            "place_type": tags.get("place", "neighbourhood"),
        })

    neighborhoods.sort(key=lambda x: x["name"].lower())
    return neighborhoods[:1000]


def _get_cache_filepath(geonameid: str) -> str:
    """Returns absolute path to local cache file for a city's neighborhoods."""
    cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), config.PLACES_CACHE_DIR))
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{geonameid}.json")


def load_cached_neighborhoods(geonameid: str) -> Optional[List[Dict[str, Any]]]:
    """
    Loads cached neighborhoods if file exists, is valid JSON, and is within the 30-day TTL.
    Tolerates corrupt files safely.
    """
    fpath = _get_cache_filepath(geonameid)
    if not os.path.exists(fpath):
        return None

    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        cached_at = data.get("cached_at", 0)
        ttl_seconds = config.NEIGHBORHOOD_CACHE_TTL_DAYS * 86400
        if time.time() - cached_at > ttl_seconds:
            return None

        neighborhoods = data.get("neighborhoods")
        if isinstance(neighborhoods, list):
            return neighborhoods
        return None
    except Exception as err:
        logger.warning(f"Corrupt cache file for geonameid {geonameid}: {err}. Will refetch.")
        return None


def save_cached_neighborhoods(geonameid: str, city_name: str, neighborhoods: List[Dict[str, Any]]) -> None:
    """Atomically saves neighborhoods to disk cache."""
    fpath = _get_cache_filepath(geonameid)
    temp_path = fpath + ".tmp"
    data = {
        "geonameid": geonameid,
        "city_name": city_name,
        "cached_at": time.time(),
        "count": len(neighborhoods),
        "neighborhoods": neighborhoods
    }
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, fpath)
    except Exception as err:
        logger.error(f"Failed to write neighborhood cache for {geonameid}: {err}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


def fetch_neighborhoods_from_overpass(
    city: Dict[str, Any],
    contact_email: str
) -> List[Dict[str, Any]]:
    """
    Performs exactly ONE Overpass request to discover neighborhoods for the selected city.
    Uses population-scaled search radius, verified failover mirrors, and exponential backoff.
    """
    lat = city["latitude"]
    lon = city["longitude"]
    pop = city.get("population", 0)
    radius = get_city_radius(pop)

    query = build_neighborhood_overpass_query(lat, lon, radius)
    user_agent = f"LocalLeadsKit/{config.VERSION} (contact: {contact_email.strip()})"
    headers = {"User-Agent": user_agent}

    # Iterate through verified Overpass mirrors with backoff
    for attempt in range(len(config.OVERPASS_URLS)):
        url = config.OVERPASS_URLS[attempt % len(config.OVERPASS_URLS)]
        try:
            resp = requests.post(url, data={"data": query}, headers=headers, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                elements = result.get("elements", [])
                return parse_neighborhood_elements(elements)
            elif resp.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
            else:
                time.sleep(1.0)
        except Exception as err:
            logger.warning(f"Overpass mirror {url} failed: {err}")
            time.sleep(1.0)

    logger.error(f"All Overpass mirrors failed for city {city.get('name')}")
    return []


def load_or_fetch_neighborhoods(
    city: Dict[str, Any],
    contact_email: str
) -> List[Dict[str, Any]]:
    """
    Returns neighborhoods for a city, loading from local cache if fresh,
    otherwise querying Overpass and caching atomically.
    """
    geonameid = str(city.get("geonameid", ""))
    cached = load_cached_neighborhoods(geonameid)
    if cached is not None:
        return cached

    fetched = fetch_neighborhoods_from_overpass(city, contact_email)
    if fetched:
        save_cached_neighborhoods(geonameid, city.get("name", ""), fetched)
    return fetched


def create_city_center_target(city: Dict[str, Any]) -> AreaTarget:
    """Creates an AreaTarget for the city center using bundled coordinates directly."""
    return AreaTarget(
        label=f"{city['name']} (City center)",
        latitude=city["latitude"],
        longitude=city["longitude"],
        country_code=city["country_code"],
        source="city_center"
    )


def create_neighborhood_target(neighborhood: Dict[str, Any], country_code: str) -> AreaTarget:
    """Creates an AreaTarget for a neighborhood using discovered coordinates directly."""
    return AreaTarget(
        label=neighborhood["name"],
        latitude=neighborhood["latitude"],
        longitude=neighborhood["longitude"],
        country_code=country_code,
        source="osm_neighborhood"
    )


def create_fallback_target(area_label: str, country_code: str = "US") -> AreaTarget:
    """
    Creates an AreaTarget for an unlisted or manually typed area.
    Coordinates are unresolved (0.0) and will be geocoded via Nominatim with rate limiting.
    """
    return AreaTarget(
        label=area_label.strip(),
        latitude=0.0,
        longitude=0.0,
        country_code=country_code,
        source="fallback_nominatim"
    )


def validate_manual_place(place_input: str, has_selected_city: bool) -> Tuple[bool, str]:
    """
    Validates manual place input per specification:
    - If a city is selected from the dropdown: manual place can be empty or any string.
    - If NO city is selected: manual place requires at least two comma-separated non-empty parts
      (e.g. 'Downtown, Austin, Texas' or 'City, Country').
    Returns (is_valid, error_reason).
    """
    s = (place_input or "").strip()
    if has_selected_city:
        return True, ""
    if not s:
        return False, "Please select a city or enter a place."
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) < 2:
        return False, "Manual place requires at least two comma-separated parts (e.g. Downtown, Austin, Texas) when no city is selected."
    return True, ""


def build_manual_geocode_query(
    place_input: str,
    city: Optional[Dict[str, Any]] = None,
    region_name: str = "",
    country_name: str = ""
) -> Tuple[str, str]:
    """
    Builds the combined geocoding query and determines country code:
    - If city is selected: combines manual area + city + region + country,
      and returns (combined_query, city['country_code']).
    - If city is not selected: returns (place_input, '').
    """
    manual_clean = (place_input or "").strip()
    if city:
        city_name = city.get("name", "")
        reg = region_name if (region_name and region_name != "All regions") else ""
        c_name = country_name or ""
        parts = [p for p in [manual_clean, city_name, reg, c_name] if p]
        combined = ", ".join(parts)
        return combined, city.get("country_code", "US")
    else:
        return manual_clean, ""

