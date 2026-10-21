# Changelog

All notable changes to **LocalLeads Kit** will be documented in this file.

## [1.0.2] - 2026-09-21

### Added
- **Verified-Valid Email Filtering:** Sourcing pipeline strictly restricts the primary ready-for-email export (`leads_ready_for_email.csv`) to deliverable, verified-valid email addresses only.
- **Quarantined Unverified & Guessed Emails:** Quarantined unverified emails and pattern-guessed `info@` addresses into dedicated review exports (`leads_unverified_emails.csv` and `leads_risky_review.csv`) to protect sender reputation.
- **Explicit `no_email` Status:** Assigned explicit `no_email` status classification to businesses with telephone or physical premises but no published email address.
- **Crawler Hardening & Honest User-Agent:** Hardened website contact crawler with per-domain `robots.txt` compliance, strict 30-second per-site deadline bounds, DNS/connect/SSL error retries, and an honest, transparent `User-Agent: Mozilla/5.0 (compatible; LocalLeadsKit/1.0.2)`.
- **Phone Parsing by Country:** Integrated Google's `phonenumbers` library to extract and format numbers in E.164 and international display formats based on geocoded country codes.
- **New Columns (Address, Maps URL, Sources):** Added `address` (assembled from OSM `addr:housenumber`, `addr:street`, `addr:suburb`, `addr:city`, `addr:postcode`), `maps_url` (direct zero-API Google Maps search links), `email_source`, `phone_source`, and `source_url` (exact crawled page where contact was discovered).
- **Expanded Category Tags:** Audited OSM presets against global taginfo usage; added `healthcare=dentist|doctor|clinic` for Clinic, `craft=hvac|roofer|painter` and `office=construction_company` for Contractor, `amenity=coworking_space` for Coworking, `shop=estate_agent` for Real Estate, and compound sports center selectors for Gyms.
- **Cascading Location Dropdowns:** Added instant offline cascading dropdowns (Country -> Region -> City) backed by bundled GeoNames database of 69,735 cities across 250+ countries with alias resolution (e.g. Bangalore -> Bengaluru) and zero external geocoding calls on keystrokes.
- **Required Contact Email:** Embedded required contact email input in Step 1 to satisfy OpenStreetMap API policy and ensure polite, identified crawling.
- **Legacy Schema Migration & Blank-Cell Fix:** Implemented robust migration layer that transparently parses and exports historical CSV and JSON records from v1.0.0/v1.0.1, handling missing columns and blank/NaN cells without DictWriter mismatches or crash errors.
- **Self-Contained Launcher:** Standalone zero-Python launcher scripts (`run.bat`, `run.sh`, `run.command`) with pinned `uv` v0.6.5, cryptographic SHA256 checksum verification, and automated Python 3.11 environment provisioning.
- **Dark Console UI:** Re-architected interface into a calm, focused dark data console with strict WCAG AA contrast (>= 4.5:1 text and status tokens, >= 3.0:1 strong borders), responsive card grids down to 390px, and zero emoji across all components.

### Changed
- **Default Sweep Radius:** Increased default radius to 2500 m in `config.py` for enhanced urban business recall.
- **Stepper Progression:** Relocated setup workflow stepper to top of setup with `aria-current="step"` attribute on active stage.
- **Header Tagline:** Dynamically toggles between "verified email addresses" (when ZeroBounce credits active) and "public contact emails".

### Removed
- **Dead OSM Tag:** Pruned unused `office=legal` tag.

## [1.0.1] - 2026-09-20

### Added
- **Dark Console UI Architecture (`ui.py`):** Calm, authoritative dark console UI with strict WCAG AA contrast (>= 4.5:1 text, >= 3.0:1 `--border-strong: #56668F`), responsive layout down to 390px, and zero emoji across all headers, metrics, tabs, buttons, and alerts.
- **Local Static Typography:** Bundled Manrope (UI) and JetBrains Mono (data/code) woff2 fonts served locally via Streamlit static serving (`enableStaticServing = true`) with SIL OFL licenses and zero external CDN requests.
- **Offline Geographic Places Engine (`places.py`):** Bundled offline GeoNames database (252 countries, 3,865 admin1 regions, 69,735 cities with population >= 5,000, and 62 verified aliases) with instant sub-millisecond cascading dropdowns (Country -> Region -> City) and zero Nominatim calls on keystrokes.
- **City-State & Blank Admin1 Resilience:** Automatic auto-selection of "All regions" for city-states (e.g. Singapore, Monaco, Hong Kong) and territories without regional subdivisions.
- **Neighborhood Discovery with Atomic Cache:** Population-scaled Overpass neighborhood queries (25km >5M, 15km >1M, 10km >250k, 6km else) with 30-day TTL, atomic file caching, and corrupt-cache tolerance.
- **XSS Defense Layer:** Strict `html.escape` sanitization applied to all dynamic and user-supplied strings before injection into HTML.
- **Core Engine Extraction (`leadcore.py`):** Pure-logic processing layer decoupled from Streamlit UI for direct testability and performance.
- **Industry-Standard Phone Parsing:** Integrated Google's `phonenumbers` library to extract and format numbers in E.164 and international display standards based on geocoded country codes.
- **Directory Domain Filter:** Added `DIRECTORY_DOMAINS` to block false leads from 20+ aggregators and social networks (Justdial, Yelp, Facebook, LinkedIn, Zomato, etc.).
- **Segmented Export Architecture:** Added 5 distinct CSV downloads: `leads_ready_for_email.csv` (strictly valid deliverable emails), `leads_unverified_emails.csv`, `leads_phone_outreach.csv`, `leads_risky_review.csv`, and `leads_all.csv`.
- **ZeroBounce Balance Checking:** Added "Check key / show credits" utility button and graceful run halt when credits expire or keys are invalid.
- **OpenStreetMap Policy Compliance:** Required buyer contact email in sidebar, dynamically included in the Nominatim and Overpass `User-Agent`.
- **Standalone Zero-Python Launchers (`run.bat`, `run.sh`, `run.command`):** Automated bootstrapping that downloads pinned `uv` v0.6.5, verifies cryptographic SHA256 integrity, provisions an isolated Python 3.11 environment in `.venv/`, and launches the app with no pre-installed Python needed.
- **Resilient Crawler Architecture:** Added 30-second per-site deadline bounds, separate connect (8s) / read (15s) timeouts, single retry, polite `robots.txt` compliance, and cross-registrable-domain redirect checking.
- **Obfuscation & Cloudflare Decoding:** Added automatic decoding for Cloudflare `data-cfemail` obfuscation and `[at]` / `(at)` text conventions.
- **Lead Provenance Tracking:** Granular source attribution distinguishing OSM tags from Website crawl extractions for both emails and phone numbers.
- **macOS Launcher (`run.command`):** Double-click execution support for macOS users.
- **Automated Packaging (`make_zip.py`):** Standalone distribution script creating clean zip archives with preserved executable bits.
- **Automated Test Suite:** Comprehensive `pytest` test suite covering contrast, XSS escaping, no emoji, places cascade, validation, normalization, deduplication, formula injection safety, crawler time bounds, launcher integrity, and headless Streamlit runs.

### Changed
- **Email Status Taxonomy:** Enforced strict status classification: `valid`, `risky`, `invalid`, `unknown`, `unverified`, `guessed`, and `no_email`.
- **Transparent User-Agent:** Replaced browser spoofing with honest User-Agent `Mozilla/5.0 (compatible; LocalLeadsKit/{VERSION})`.
- **Throughput & Concurrency:** Implemented `ThreadPoolExecutor(max_workers=5)` for concurrent website crawling with per-domain politeness delays.
- **Overpass Failover:** Configured automatic retry with exponential backoff across 4 verified global Overpass mirrors.
- **CSV Formula Injection Protection:** Sanitized text fields starting with `=`, `+`, `-`, `@`, `\t`, or `\r` to protect spreadsheet applications.
- **Honest Documentation:** Removed misleading marketing claims, documented zero-Python launcher architecture, and added transparent "Known Limitations".
- **Support Contact:** Dedicated support channel established at `supportlocalleadskit@gmail.com`.

### Removed
- Removed stale duplicate script `lead_finder.py`.
- Removed legacy placeholder User-Agents.
