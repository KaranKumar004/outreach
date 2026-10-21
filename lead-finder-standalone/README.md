<div align="center">

# LocalLeads Kit v1.0.2
### The B2B Local Business Lead Sourcing Engine

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B.svg)](https://streamlit.io/)
[![Zero Subscription](https://img.shields.io/badge/Subscription-None%20($0%2Fmo)-green.svg)](#)
[![ZeroBounce Compatible](https://img.shields.io/badge/Email%20Verification-ZeroBounce%20Ready-6366f1.svg)](#)
[![License](https://img.shields.io/badge/License-Commercial%20Friendly-emerald.svg)](#)

<br>

<img src="marketing/localleads_cover.jpg" alt="LocalLeads Kit Banner" width="100%" style="border-radius: 12px; margin: 15px 0;" />

<br>

**Source targeted local business leads, emails, standardized phone numbers, and websites across cities worldwide.**  
*Built for freelancers, agencies, cold outreach specialists, and B2B service providers.*

[Features](#features) • [Quickstart](#quickstart) • [Quick Test](#quick-test-run) • [Export Filters](#smart-export-filters) • [Known Limitations](#known-limitations) • [Support](#support)

</div>

---

## Why LocalLeads Kit?

Most B2B lead platforms (Apollo, ZoomInfo) charge recurring subscriptions of **$50 to $300/month** and cater primarily to enterprise software companies, frequently missing brick-and-mortar local businesses (dentists, salons, clinics, contractors, gyms, restaurants). 

**LocalLeads Kit** provides a self-hosted workflow: it queries community OpenStreetMap databases, crawls official business websites for published contacts, normalizes phone numbers via libphonenumber, and optionally validates email deliverability via ZeroBounce.

### Comparison Table

| Feature | LocalLeads Kit | Subscription Databases | Manual Web Scraping |
| :--- | :---: | :---: | :---: |
| **Pricing** | **One-Time Purchase ($0/mo)** | $49 – $299 / month | Free (Costs 20+ hours) |
| **Local Business Coverage** | Direct OpenStreetMap geographic data | Enterprise / tech bias | High but slow |
| **Email Deliverability** | Optional ZeroBounce API verification | Cached records | None |
| **Phone Detection & Parsing** | E.164 and international format parsing | Gated behind tier plans | Manual copying |
| **Data Ownership** | Local CSV on your hard drive | Monthly credit caps | Spreadsheets |
| **Launcher** | Automated launcher scripts | Web login | High manual scripting |

---

## Features

- **Geographic Sweep & Cascading Lookup:** Bundled offline search for 69,735 global cities across 250+ countries with instant sub-millisecond cascading dropdowns, population-scaled search radii, and alias matching (e.g. "Bangalore" -> Bengaluru).
- **OpenStreetMap Tag Matching:** Targeted presets (*Real Estate, Salons, Clinics/Dentists, Contractors, Hospitality, Gyms, Legal*) plus support for custom OSM tags (e.g. `amenity=dentist`).
- **Resilient Website Contact Crawler:**
  - Enforces a 30-second worst-case per-site deadline.
  - Transparent, honest `User-Agent: Mozilla/5.0 (compatible; LocalLeadsKit/1.0.2)`.
  - Polite `robots.txt` compliance checked per domain before fetching contact subpages.
  - Retries `www` / non-`www` variants strictly on DNS, connect, or SSL errors (not on read timeouts or HTTP errors).
  - Cross-domain redirect detection (recognizes subdomains on the same registrable domain vs. external redirects).
  - Decodes Cloudflare email obfuscation (`data-cfemail`) and `[at]` / `(at)` de-obfuscation.
- **Standardized Phone Parsing:** Extracts telephone contacts using the industry-standard `phonenumbers` library, deriving regions from geocoded country codes and saving both E.164 and readable display formats.
- **Anti-Garbage Email Validator:** Filters out junk domains (`example.com`, `sentry`, `wixpress.com`), image/font TLDs (`.png`, `.woff`, `.jpg`), and noreply robot addresses.
- **Real-Time ZeroBounce Integration:** Optional deliverability verification against the ZeroBounce API to separate deliverable emails from catch-all and invalid mailboxes.
- **Crash-Safe & Deduplicated Storage:** Automatically keys leads on OpenStreetMap element IDs and atomically writes each lead to local disk immediately upon discovery.
- **5 Segmented CSV Exports:**
  - `leads_all.csv`: Complete raw sourced leads report.
  - `leads_ready_for_email.csv`: Verified deliverable emails only, deduplicated by email address.
  - `leads_unverified_emails.csv`: Scraped emails pending deliverability verification.
  - `leads_phone_outreach.csv`: Clean, formatted phone numbers.
  - `leads_risky_review.csv`: Catch-all or unconfirmed server domains.

---

## Quickstart

The included 1-click launchers automatically download the verified, high-performance `uv` runtime manager (pinned to official release v0.6.5 with SHA256 integrity verification), provision an isolated Python 3.11 environment, and launch the dashboard.

### First-Run Automated Download Measurements
On first execution, the launcher performs a one-time automated dependency download:
* **Runtime Manager (`uv` v0.6.5):** ~15 MB
* **Portable Python 3.11 Toolchain:** ~25 MB compressed (~65 MB on disk)
* **Python Dependencies & Wheels (`requirements.txt`):** ~60–70 MB
* **Total Download Volume:** ~100–110 MB
* **Typical First-Run Setup Time:** ~20–45 seconds on high-speed internet (subsequent runs launch in < 2 seconds)

### What Is Written Where
To keep your kit folder clean and portable:
* **Application Runtime & Virtual Environment:**
  * Windows: `%LOCALAPPDATA%\LocalLeadsKit\venv\`
  * macOS / Linux: `~/.localleadskit/venv/`
* **UV Binary & Managed Python Toolchain:**
  * Windows: `%LOCALAPPDATA%\LocalLeadsKit\bin\` and `%LOCALAPPDATA%\LocalLeadsKit\python\`
  * macOS / Linux: `~/.localleadskit/bin/` and `~/.localleadskit/python/`
* **UV Download Cache:**
  * Windows: `%LOCALAPPDATA%\LocalLeadsKit\uv-cache\`
  * macOS / Linux: `~/.localleadskit/uv-cache/`
* **Streamlit Configuration:** `~/.streamlit/credentials.toml` (automatically created to suppress interactive email onboarding prompt)
* **User Data & Generated Files (Kept Strictly in Kit Directory):**
  * Sourced leads export (`localleads_export.csv`)
  * Search history (`lead_history.json`)
  * Application preferences (`settings.json`)
  * Local place lookup cache (`places_cache/`)
  * ZeroBounce validation cache (`verified_emails_cache.json`)

### Option A: 1-Click Launchers (Recommended)

What the launcher scripts do automatically:
1. Detect architecture (including 64-bit and ARM64) and check for `uv`.
2. Download verified official `uv` v0.6.5 and cryptographically verify its SHA256 integrity checksum.
3. Configure `~/.streamlit/credentials.toml` if absent.
4. Provision an isolated Python 3.11 virtual environment in the runtime directory.
5. Install and sync dependencies from `requirements.txt`.
6. Launch LocalLeads Kit in your default browser at `http://localhost:8501`.

* **Windows:** Double-click **`run.bat`**.
* **macOS:** Double-click **`run.command`** (or run `chmod +x run.sh && ./run.sh`).
* **Linux:** Run `chmod +x run.sh && ./run.sh`.

---

### Option B: Manual Setup (If you prefer using an existing Python 3.10+ environment)

1. **Open your terminal in the extracted kit directory:**
   ```bash
   cd LocalLeads-Kit
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # Windows
   python -m venv .venv
   call .venv\Scripts\activate.bat

   # macOS / Linux
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   python -m pip install -r requirements.txt
   ```

4. **Start the application:**
   ```bash
   streamlit run app.py
   ```

---

## Quick Test Run

To test the application quickly with reliable community data:

1. In the sidebar under **Contact and OpenStreetMap**, enter your **contact email** (required by OpenStreetMap's User-Agent policy).
2. Under **Target location**, select your geography via the cascading dropdowns:
   - **United States:** Select **Country** `United States` -> **Region** `Texas` -> **City** `Austin (Travis County, 790,390)`.
   - **India (Search & Alias Test):** Select **Country** `India` -> **Region** `Karnataka` -> **City** `Bengaluru (Bangalore)` (matched instantly via bundled alias index).
3. Select **Neighborhoods**: Keep default `City center` or click **Load neighborhoods** to query OpenStreetMap for local suburbs and quarters.
4. Set **Business Category** to `Clinic / Doctor / Dental` (or `Real Estate / Estate Agents`).
5. Click **Start Sourcing Leads**.
6. Observe the dark console as listings are geocoded, enriched, verified, and segmented into the 5 export tabs.

---

## Smart Export Filters

| Export File | Purpose | Recommended Outreach Channel |
| :--- | :--- | :--- |
| **`leads_ready_for_email.csv`** | Verified deliverable (`valid`) emails, deduplicated by email address. | Cold Email Campaigns (Instantly, Smartlead, Gmail) |
| **`leads_unverified_emails.csv`** | Format-valid emails scraped from websites, awaiting verification. | Manual verification or secondary verification tools |
| **`leads_phone_outreach.csv`** | Extracted phone numbers standardized to E.164 and readable format. | Direct Calling, SMS, or WhatsApp Outreach |
| **`leads_risky_review.csv`** | Catch-all domains or servers with risky deliverability. | Manual outreach or LinkedIn messaging |
| **`leads_all.csv`** | Master export containing all discovered leads with notes and OSM IDs. | CRM Import (HubSpot, Notion, Airtable) |

### CSV Export Schema

All exported CSV files conform to a standardized 20-column schema:

| Column | Description | Example |
| :--- | :--- | :--- |
| `business_name` | Official business name from OpenStreetMap tags | `Austin Family Dental` |
| `address` | Formatted street address assembled from OSM tags | `1010 W 6th St, Austin, TX 78703` |
| `phone` | Standardized national/local telephone format | `(512) 555-0144` |
| `phone_e164` | International telecom standard E.164 phone number | `+15125550144` |
| `email` | Cleaned business email address | `contact[at]austinfamilydental.com` |
| `verification_status` | Classification (`valid`, `risky`, `invalid`, `unknown`, `unverified`, `guessed`, `no_email`) | `valid` |
| `website` | Cleaned official homepage URL | `https://austinfamilydental.com` |
| `maps_url` | Direct Google Maps search link (zero API keys/calls needed) | `https://www.google.com/maps/search/?api=1&query=...` |
| `email_source` | Attribution machine taxonomy (`osm_tag`, `website_crawl`, `search_snippet`, `guessed_domain`) | `website_crawl` |
| `phone_source` | Attribution machine taxonomy (`osm_tag`, `website_crawl`, `search_snippet`, `guessed_domain`) | `osm_tag` |
| `source_url` | Exact page URL where the crawled contact was discovered | `https://austinfamilydental.com/contact-us` |
| `business_type` | Business category preset or custom OSM tag | `Clinic / Doctor / Dental` |
| `contact_name` | Identified contact or manager name (when published) | `Dr. Sarah Jenkins` |
| `contact_method` | Recommended outreach channel based on available contacts | `email` |
| `context_notes` | Crawler diagnostics and status details | `HTTP 200 via website crawl` |
| `osm_type` | OpenStreetMap primitive (`node` or `way`) | `node` |
| `osm_id` | Unique numeric identifier in OpenStreetMap for deduplication | `482910384` |
| `latitude` | Geographic latitude coordinate | `30.2672` |
| `longitude` | Geographic longitude coordinate | `-97.7431` |
| `shared_email` | Boolean flag (`True`/`False`) indicating multi-listing email | `False` |

---

## Sweep Radius & Empirical Recall Benchmarks

The sweep radius determines the circular search boundary around geographic coordinates. LocalLeads Kit defaults to **2500m** (configurable in `config.py` or directly in the UI):

* **Search Area Scaling:** Expanding radius from 1500m to 2500m increases the geographic circular search area from ~7.1 km² to ~19.6 km² (+176%).
* **Empirical Validation (Banaswadi, Bengaluru):**  
  Measured on **2026-09-21** via official Overpass mirror `https://overpass-api.de/api/interpreter` querying category *Gym / Fitness / Yoga*:

| Search Radius | Circular Area | Baseline Tag (`leisure=fitness_centre`) | Multi-Tag Preset (LocalLeads Kit v1.0.2) | Net Recall Gain |
| :---: | :---: | :---: | :---: | :---: |
| **1500m** | 7.07 km² | 5 listings | 6 listings | **+20.0%** (+1 lead) |
| **2500m** (Default) | 19.63 km² | 7 listings | 14 listings | **+100.0%** (+7 leads) |
| **3000m** | 28.27 km² | 7 listings | 16 listings | **+128.6%** (+9 leads) |

* **Tuning Guidance:** For dense urban centers with high walkability, 1500m–2000m provides hyper-local targeting. For sprawling suburban markets, 2500m–5000m ensures high recall across commercial strips.

---

## Known Limitations

1. **Bundled Geographic Coverage (Cities >= 5,000):** The offline places index includes 69,735 global cities and towns with population >= 5,000 (1.75 MB total data loaded in ~500 ms) to avoid bloated downloads. If your target locality has a population under 5,000, expand *"Cannot find your area? Type it manually"* to query OpenStreetMap Nominatim directly with strict 1 req/s rate limits.
2. **OpenStreetMap Data Density & Accuracy:** OSM website and phone tags can be missing, stale, or wrong, so expect email addresses on only a minority of leads (roughly 15% in our Austin dentist benchmark). Community tagging completeness varies by municipality: dense across North America and Western Europe, but noticeably thinner in certain regions such as India.
3. **Neighborhood Completeness:** Discovered neighborhoods depend on community `place=suburb`, `place=neighbourhood`, and `place=quarter` OpenStreetMap tags within a population-scaled radius around the city center.
4. **Website & Phone Availability:** Contact availability depends on whether businesses publish phone numbers and email addresses on their websites in crawlable HTML. Some businesses rely exclusively on third-party social profiles or contact forms.
5. **Email Deliverability Verification:** Emails are unverified until a ZeroBounce key is used. Without an API key, all format-valid scraped emails are cataloged as `unverified` and exported separately. Emails are only marked as deliverable (`valid`) when an active ZeroBounce API key is provided.
6. **Phone Numbers:** Extracted phone numbers are checked for geographic formatting validity via Google's `phonenumbers` library; this confirms standard telecom numbering plans, but does not guarantee the line is currently active.

---

## Data & License Attributions

- **GeoNames:** Contains data from [GeoNames](https://www.geonames.org), used under the Creative Commons Attribution license (CC BY). See https://www.geonames.org/export/ for terms.  
  <!-- NOTE: Generic CC BY deed text was previously misattributed as a quote from geonames.org. Upstream export terms and dump/readme.txt terms are documented verbatim in THIRD_PARTY_NOTICES.md. -->
  *Upstream Terms (geonames.org/export & dump/readme.txt):*  
  > "The Data is provided 'as is' without warranty or any representation of accuracy, timeliness or completeness."
- **OpenStreetMap:** Map data, point-of-interest tags, and neighborhood boundaries are provided by [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) under the Open Database License (ODbL).
- **Fonts:** Manrope and JetBrains Mono are distributed under the SIL Open Font License 1.1 (bundled locally in `static/fonts/` with full upstream license texts and copyright notices).
- **Automated Toolchain:** The launchers download `uv` (MIT / Apache-2.0, Astral Software) and portable standalone Python 3.11 (`python-build-standalone`, Python Software Foundation License 2.0).

---

## Configuration (`config.py`)

You can customize default behavior in `config.py`:
* `DEFAULT_CITY`: Default search region (default: `"Austin, Texas"`).
* `DEFAULT_RADIUS_METERS`: Sweep radius around coordinates (default: `2500m`).
* `BUSINESS_TAG_MAP`: Add your own business categories and OpenStreetMap tags.
* `OVERPASS_URLS`: List of verified primary and mirror Overpass endpoints.
* `DIRECTORY_DOMAINS`: Domains excluded from website crawling.

---

## Uninstall & Clean Removal

To remove LocalLeads Kit completely from your system:

1. **Delete the Kit Directory:** Delete the extracted `LocalLeads-Kit/` folder to remove all application code, CSV exports, search history, and settings.
2. **Remove Isolated Runtime & UV Cache:**
   * **Windows:** Delete the `%LOCALAPPDATA%\LocalLeadsKit` folder and `%USERPROFILE%\.streamlit\credentials.toml`.
   * **macOS / Linux:** Run `rm -rf ~/.localleadskit ~/.streamlit/credentials.toml`.

---

## Support

Need help getting started or encountered an issue?
* **Support Email:** [supportlocalleadskit@gmail.com](mailto:supportlocalleadskit@gmail.com)

---

<div align="center">
<b>LocalLeads Kit v1.0.2</b> • <i>Clean, transparent local lead sourcing.</i>
</div>
