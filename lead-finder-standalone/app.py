"""
app.py — LocalLeads Kit Streamlit Web UI.

Instant B2B local business lead extraction & real-time email verification engine.
UI layer only — pure business logic is encapsulated in leadcore.py and places.py.
Styling and visual components are provided by ui.py.
"""

import os
import sys
import time
import html
from typing import Any, List, Dict, Optional
import pandas as pd
import streamlit as st

# Local engine modules
import config
import leadcore
import places
import ui

# ----------------- PAGE CONFIG & THEME INITIALIZATION -----------------

st.set_page_config(
    page_title="LocalLeads Kit — B2B Local Business Lead Engine",
    layout="wide",
    initial_sidebar_state="auto"
)

# Inject dark console stylesheet
ui.inject_theme_css()

# File paths
HISTORY_FILE = "lead_history.json"
CACHE_FILE = config.VERIFICATION_CACHE_FILE
SETTINGS_FILE = "settings.json"
DEFAULT_EXPORT_CSV = "localleads_export.csv"


# ----------------- SETTINGS & CACHE HELPERS -----------------

def get_settings() -> dict:
    return leadcore.load_json(SETTINGS_FILE, default={})


def update_settings(key: str, val: Any) -> None:
    settings = get_settings()
    settings[key] = val
    leadcore.save_json_atomic(SETTINGS_FILE, settings)


# Initialize Session State
if "leads_df" not in st.session_state:
    st.session_state.leads_df = None
if "scraping_in_progress" not in st.session_state:
    st.session_state.scraping_in_progress = False
if "loaded_neighborhoods" not in st.session_state:
    st.session_state.loaded_neighborhoods = []

settings = get_settings()
saved_contact_email = settings.get("contact_email", "")


# ----------------- SIDEBAR CONFIGURATION -----------------

st.sidebar.markdown('<div class="sidebar-section-label">Settings & Verification</div>', unsafe_allow_html=True)

# Verification Expander
with st.sidebar.expander("Verification", expanded=False):
    enable_verification = st.checkbox(
        "Enable ZeroBounce real-time verification",
        value=False,
        help="Validates mailbox deliverability via ZeroBounce API. Verified deliverable emails count as Ready for email."
    )
    zb_api_key = ""
    if enable_verification:
        zb_api_key = st.text_input(
            "ZeroBounce API key",
            value=settings.get("zerobounce_api_key", ""),
            type="password",
            help="Enter your ZeroBounce API key. Results are cached locally to preserve credits."
        )
        if zb_api_key and zb_api_key != settings.get("zerobounce_api_key"):
            update_settings("zerobounce_api_key", zb_api_key)

        if st.button("Check key / show credits"):
            if not zb_api_key:
                st.error("Please enter a ZeroBounce API key first.")
            else:
                with st.spinner("Checking credits balance..."):
                    res = leadcore.check_zerobounce_credits(zb_api_key)
                    if res.get("success"):
                        st.session_state.zb_credits = res.get("credits", 0)
                        st.success(f"Active key. Remaining credits: {res['credits']:,}")
                    else:
                        st.session_state.zb_credits = 0
                        st.error(f"Error: {res.get('error', 'Failed to check credits.')}")

        st.caption("100 free verifications/mo on ZeroBounce. Cached in verified_emails_cache.json.")

# Advanced Settings Expander
with st.sidebar.expander("Advanced settings", expanded=False):
    radius_input = st.slider(
        "Search sweep radius (meters)",
        min_value=500,
        max_value=5000,
        value=config.DEFAULT_RADIUS_METERS,
        step=100
    )
    max_leads_input = st.slider(
        "Max leads to analyze per area",
        min_value=1,
        max_value=100,
        value=config.DEFAULT_MAX_LEADS,
        step=5
    )
    web_fallback_toggle = st.checkbox(
        "Web search fallback (experimental)",
        value=False,
        help="Attempts to find missing business websites via web search. Slower, but uncovers more sites."
    )
    guessed_info_toggle = st.checkbox(
        "Include guessed info@ addresses (low quality)",
        value=False,
        help="Generates info@domain addresses when website is known but no email was found on page. Appears only in unverified export."
    )
    ignore_csv_toggle = st.checkbox(
        "Ignore existing CSV for this run",
        value=False,
        help="Do not merge previously saved leads from the local CSV into this session."
    )
    export_filename = st.text_input(
        "Local CSV save file",
        value=DEFAULT_EXPORT_CSV
    )
    if st.button("Clear search history cache"):
        cleared = False
        if os.path.exists(HISTORY_FILE):
            try:
                os.remove(HISTORY_FILE)
                cleared = True
            except Exception as e:
                st.error(f"Error clearing history: {e}")
        if os.path.exists(CACHE_FILE):
            try:
                os.remove(CACHE_FILE)
                cleared = True
            except Exception:
                pass
        st.session_state.leads_df = None
        if cleared:
            st.success("Lead history and verification cache cleared successfully.")
        else:
            st.info("Cache is already empty.")

# Sidebar Footer with Support and GeoNames License Attribution
st.sidebar.markdown(f"""
<div class="sidebar-footer" style="padding-top: 24px; border-top: 1px solid var(--border); font-size: 12px; color: var(--text-3); margin-top: 24px;">
    <div><strong>LocalLeads Kit</strong> v{html.escape(config.VERSION)}</div>
    <div style="margin-top: 4px;">Support: <a href="mailto:{html.escape(config.SUPPORT_EMAIL)}" style="color: var(--accent); text-decoration: none;">{html.escape(config.SUPPORT_EMAIL)}</a></div>
    <div style="margin-top: 8px; font-size: 11px; line-height: 1.4; color: var(--text-3);">
        Contains data from <a href="https://www.geonames.org/" target="_blank" style="color: var(--text-2); text-decoration: underline;">GeoNames</a>, used under the Creative Commons Attribution license (CC BY). See <a href="https://www.geonames.org/export/" target="_blank" style="color: var(--text-2); text-decoration: underline;">export terms</a>.
    </div>
</div>
""", unsafe_allow_html=True)


# ----------------- MAIN SOURCING UI -----------------

# Header Card with honest, dynamic value proposition
verified_credits_active = False
if enable_verification and zb_api_key and st.session_state.get("zb_credits", 0) > 0:
    verified_credits_active = True

ui.render_header(config.VERSION, config.SUPPORT_EMAIL, verified_credits_active=verified_credits_active)

# Stepper Progression (positioned at top of setup, updated reactively)
stepper_placeholder = st.empty()

# ----------------- STEP 1: CONTACT INFORMATION -----------------
st.markdown('<div class="sidebar-section-label">1. Contact information</div>', unsafe_allow_html=True)
contact_email_input = st.text_input(
    "Your contact email *",
    value=saved_contact_email,
    help="Mandatory: OpenStreetMap requires a valid contact email in the User-Agent header per their usage policy."
)
is_contact_valid = leadcore.validate_email(contact_email_input)
if contact_email_input and is_contact_valid:
    if contact_email_input != saved_contact_email:
        update_settings("contact_email", contact_email_input)
elif contact_email_input and not is_contact_valid:
    st.error("Please enter a valid contact email.")

# ----------------- STEP 2: TARGET LOCATION & CRITERIA -----------------
st.markdown('<div class="sidebar-section-label">2. Target location & business criteria</div>', unsafe_allow_html=True)
col_country, col_region, col_city = st.columns(3)

countries = places.load_countries()
country_names = [c[1] for c in countries]
country_code_map = {c[1]: c[0] for c in countries}
country_name_map = {c[0]: c[1] for c in countries}

saved_country_name = country_name_map.get(settings.get("country_code", ""), None)
default_country_idx = country_names.index(saved_country_name) if saved_country_name in country_names else None

with col_country:
    selected_country_name = st.selectbox(
        "Country",
        options=country_names,
        index=default_country_idx,
        placeholder="Search or select a country"
    )

selected_country_code = country_code_map.get(selected_country_name, "") if selected_country_name else ""
if selected_country_code and selected_country_code != settings.get("country_code"):
    update_settings("country_code", selected_country_code)

# Region Selection
regions = places.load_regions(selected_country_code) if selected_country_code else []
region_names = [r[1] for r in regions]
region_code_map = {r[1]: r[0] for r in regions}
region_name_map = {r[0]: r[1] for r in regions}

is_city_state = (len(regions) == 1 and regions[0][0] == "00")
saved_region_name = region_name_map.get(settings.get("admin1_code", ""), None)
default_region_idx = region_names.index(saved_region_name) if saved_region_name in region_names else (0 if is_city_state else None)

with col_region:
    if not selected_country_code:
        st.selectbox("Region (state/province)", options=[], placeholder="Select a country first", disabled=True)
        selected_admin1_code = ""
        selected_region_name = ""
    elif is_city_state or not regions:
        st.selectbox("Region (state/province)", options=["All regions"], index=0, disabled=True, help="City-state or no regional subdivisions.")
        selected_admin1_code = "00"
        selected_region_name = "All regions"
    else:
        selected_region_name = st.selectbox(
            "Region (state/province)",
            options=region_names,
            index=default_region_idx,
            placeholder="Search or select a region"
        )
        selected_admin1_code = region_code_map.get(selected_region_name, "") if selected_region_name else ""

if selected_admin1_code and selected_admin1_code != settings.get("admin1_code"):
    update_settings("admin1_code", selected_admin1_code)

# City Selection
cities = places.load_cities(selected_country_code, selected_admin1_code) if (selected_country_code and (is_city_state or selected_admin1_code)) else []
city_display_names = [c["display_name"] for c in cities]
city_by_display = {c["display_name"]: c for c in cities}

saved_city_geonameid = settings.get("city_geonameid", "")
saved_city_display = next((c["display_name"] for c in cities if c["geonameid"] == saved_city_geonameid), None)
default_city_idx = city_display_names.index(saved_city_display) if saved_city_display in city_display_names else None

with col_city:
    if not selected_country_code or (not is_city_state and not selected_admin1_code):
        st.selectbox("City", options=[], placeholder="Select a region first", disabled=True)
        selected_city = None
    else:
        selected_city_display = st.selectbox(
            "City",
            options=city_display_names,
            index=default_city_idx,
            placeholder="Search or select a city"
        )
        selected_city = city_by_display.get(selected_city_display) if selected_city_display else None

if selected_city and selected_city["geonameid"] != settings.get("city_geonameid"):
    update_settings("city_geonameid", selected_city["geonameid"])

# Category & Neighborhood Criteria Row
loaded_neighs = st.session_state.loaded_neighborhoods
neigh_names_map = {n["name"]: n for n in loaded_neighs}
neigh_options = ["City center"] + [n["name"] for n in loaded_neighs]

col_cat, col_neigh, col_btn = st.columns([1.5, 2, 0.9])
with col_cat:
    category_option = st.selectbox(
        "Business Category",
        options=list(config.BUSINESS_TAG_MAP.keys()) + ["Custom OSM Tag"]
    )
with col_neigh:
    selected_neighborhoods = st.multiselect(
        "Neighborhoods (optional)",
        options=neigh_options,
        default=["City center"] if selected_city else [],
        accept_new_options=True,
        help="Select City center or specific neighborhoods. Type custom entries if needed."
    )
with col_btn:
    can_load_neigh = bool(is_contact_valid and selected_city)
    load_neigh_btn = st.button(
        "Load neighborhoods",
        disabled=not can_load_neigh,
        help="Discovers suburbs and neighborhoods from OpenStreetMap for the selected city."
    )
    if load_neigh_btn and selected_city:
        with st.spinner("Discovering neighborhoods from OpenStreetMap..."):
            fetched_neighs = places.load_or_fetch_neighborhoods(selected_city, contact_email_input)
            st.session_state.loaded_neighborhoods = fetched_neighs
            st.rerun()

if len(selected_neighborhoods) > config.MAX_SELECTED_NEIGHBORHOODS:
    st.warning(f"Maximum {config.MAX_SELECTED_NEIGHBORHOODS} neighborhoods can be analyzed per run. The first {config.MAX_SELECTED_NEIGHBORHOODS} will be processed.")
    selected_neighborhoods = selected_neighborhoods[:config.MAX_SELECTED_NEIGHBORHOODS]

# Collapsible Manual Area Fallback (uses Nominatim with 1 req/s rate limit)
with st.expander("Place (area, city, region or country)", expanded=False):
    fallback_typed_input = st.text_input(
        "Manual area or place",
        placeholder="Downtown, Austin, Texas",
        help="Geocoded via OpenStreetMap Nominatim with a strict 1 request per second rate limit."
    )

has_selected_city = bool(selected_city)
is_manual_valid, manual_err_msg = places.validate_manual_place(fallback_typed_input, has_selected_city)
if fallback_typed_input and not has_selected_city and not is_manual_valid:
    st.error(manual_err_msg)

custom_tag = ""
if category_option == "Custom OSM Tag":
    custom_tag = st.text_input(
        "Custom OSM Tag Query",
        placeholder="e.g. amenity=dentist or craft=electrician"
    )
    if custom_tag:
        is_tag_valid, tag_err = leadcore.validate_custom_osm_tag(custom_tag)
        if not is_tag_valid:
            st.error(tag_err)

# Stepper Progression & Validation
has_valid_target = has_selected_city or (bool(fallback_typed_input) and is_manual_valid)
stepper_step = 1
if is_contact_valid:
    stepper_step = 2
if is_contact_valid and has_valid_target:
    stepper_step = 3

with stepper_placeholder:
    ui.render_stepper(stepper_step)

# Primary Run Button & Guidance Helper
submit_disabled = st.session_state.scraping_in_progress or not is_contact_valid or not has_valid_target

if not is_contact_valid:
    st.caption("Enter a valid contact email in Step 1 to start.")
elif not has_valid_target:
    if fallback_typed_input and not is_manual_valid:
        st.caption(manual_err_msg)
    else:
        st.caption("Select a city or enter a manual place with at least two comma-separated parts (e.g. Downtown, Austin, Texas) to start.")

submit_button = st.button(
    "Start Sourcing Leads",
    type="primary",
    icon=":material/play_arrow:",
    disabled=submit_disabled,
    use_container_width=True
)


# ----------------- SOURCING PIPELINE -----------------

if submit_button:
    if category_option == "Custom OSM Tag":
        if not custom_tag:
            st.error("Please provide a custom OSM tag.")
            st.stop()
        is_tag_valid, tag_err = leadcore.validate_custom_osm_tag(custom_tag)
        if not is_tag_valid:
            st.error(tag_err)
            st.stop()
        tags_to_use = [custom_tag.strip()]
    else:
        tags_to_use = config.BUSINESS_TAG_MAP[category_option]

    # Build target AreaTarget objects with direct coordinates
    targets: List[places.AreaTarget] = []
    if selected_neighborhoods and selected_city:
        for item in selected_neighborhoods:
            if item == "City center" or "city center" in item.lower():
                targets.append(places.create_city_center_target(selected_city))
            elif item in neigh_names_map:
                targets.append(places.create_neighborhood_target(neigh_names_map[item], selected_city["country_code"]))
            else:
                # Custom typed neighborhood added via accept_new_options
                targets.append(places.create_fallback_target(item, selected_city["country_code"]))
    elif selected_city and not fallback_typed_input:
        targets.append(places.create_city_center_target(selected_city))

    if fallback_typed_input:
        if selected_city:
            reg_name = selected_region_name if 'selected_region_name' in locals() and selected_region_name else ""
            c_name = selected_country_name if 'selected_country_name' in locals() and selected_country_name else ""
            comb_query, c_code = places.build_manual_geocode_query(
                fallback_typed_input,
                city=selected_city,
                region_name=reg_name,
                country_name=c_name
            )
            targets.append(places.create_fallback_target(comb_query, c_code))
        else:
            comb_query, c_code = places.build_manual_geocode_query(fallback_typed_input)
            targets.append(places.create_fallback_target(comb_query, selected_country_code or "US"))

    user_agent_str = f"LocalLeadsKit/{config.VERSION} (contact: {contact_email_input.strip()})"
    history_data = leadcore.load_json(HISTORY_FILE, default={})
    verification_cache = leadcore.load_json(CACHE_FILE, default={})

    # Load existing leads from CSV if not ignored
    existing_csv_rows = []
    if not ignore_csv_toggle and os.path.exists(export_filename):
        try:
            raw_df = pd.read_csv(export_filename, keep_default_na=False).fillna("")
            existing_csv_rows = raw_df.to_dict(orient="records")
            # Normalize legacy statuses
            for r in existing_csv_rows:
                r["verification_status"] = leadcore.migrate_lead_status(
                    r.get("verification_status", ""),
                    r.get("context_notes", ""),
                    r.get("email", "")
                )
        except Exception:
            existing_csv_rows = []

    seen_element_keys = set(history_data.keys())
    for r in existing_csv_rows:
        if r.get("osm_type") and r.get("osm_id"):
            seen_element_keys.add(leadcore.get_lead_key(r["osm_type"], r["osm_id"]))

    # Track existing emails to detect shared email addresses across different businesses
    seen_emails = set()
    for entry in history_data.values():
        em = leadcore.safe_clean_str(entry.get("email")).lower()
        if em:
            seen_emails.add(em)
    for r in existing_csv_rows:
        em = leadcore.safe_clean_str(r.get("email")).lower()
        if em:
            seen_emails.add(em)

    run_start_time = time.time()
    st.session_state.scraping_in_progress = True
    status_box = st.status("Initializing lead discovery sweep...", expanded=True)
    telemetry_placeholder = st.empty()
    progress_bar = st.progress(0.0)

    total_areas = len(targets)
    new_leads_this_run: list = []
    failed_areas: list = []
    zb_active = enable_verification and bool(zb_api_key)
    zb_halted = False

    try:
        for area_idx, target in enumerate(targets):
            status_box.write(f"Processing target [{area_idx + 1}/{total_areas}]: {target.label}...")

            try:
                # Resolve coordinates: direct for bundled/Overpass places, Nominatim only for manual fallback
                if target.source in ("city_center", "osm_neighborhood"):
                    lat = target.latitude
                    lon = target.longitude
                    country_code = target.country_code
                    status_box.write(f"  Coordinates: ({lat:.4f}, {lon:.4f}) [Direct preset]")
                else:
                    city_name_geo = selected_city["name"] if selected_city else ""
                    status_box.write(f"  Geocoding '{target.label}' via Nominatim...")
                    lat, lon, country_code = leadcore.geocode_location(target.label, city_name_geo, user_agent_str)
                    if lat is None or lon is None:
                        status_box.write(f"  Could not resolve coordinates for '{target.label}'. Skipping.")
                        failed_areas.append((target.label, "Geocoding returned no coordinates"))
                        progress_bar.progress((area_idx + 1) / total_areas)
                        continue
                    status_box.write(f"  Coordinates resolved: ({lat:.4f}, {lon:.4f})")

                # Query Overpass
                status_box.write(f"  Querying OpenStreetMap listings within {radius_input}m radius...")
                businesses = leadcore.query_overpass(
                    tags_to_use, lat, lon, radius_input, user_agent_str, default_region=country_code
                )
                status_box.write(f"  Found {len(businesses)} listings in OpenStreetMap.")

                # Deduplicate on OSM element key
                unseen_biz = []
                for biz in businesses:
                    elem_key = leadcore.get_lead_key(biz["osm_type"], biz["osm_id"])
                    if elem_key not in seen_element_keys:
                        seen_element_keys.add(elem_key)
                        unseen_biz.append(biz)

                if not unseen_biz:
                    status_box.write(f"  All listings in '{target.label}' have already been gathered.")
                    progress_bar.progress((area_idx + 1) / total_areas)
                    continue

                # Capping to slider input
                if len(unseen_biz) > max_leads_input:
                    status_box.write(f"  Analyzing first {max_leads_input} new listings...")
                    unseen_biz = unseen_biz[:max_leads_input]

                status_box.write("  Crawling websites and enriching contacts concurrently...")

                def on_lead_enriched(current_idx, total_count, enriched_lead):
                    b_name = enriched_lead["business_name"]
                    em = enriched_lead.get("email") or "No email"
                    ph = enriched_lead.get("phone") or "No phone"
                    now_elapsed = time.time() - run_start_time
                    v_stat = enriched_lead.get("verification_status") or ("valid" if em != "No email" else "no_email")
                    if enriched_lead.get("email_source") == "guessed_domain":
                        v_stat = "guessed"
                    status_disp = ui.STATUS_DISPLAY_LABELS.get(v_stat, v_stat.capitalize())
                    line_html = ui.render_live_telemetry_line(
                        business_name=b_name,
                        area=target.label,
                        step=f"{current_idx}/{total_count}",
                        status=status_disp,
                        elapsed_sec=now_elapsed
                    )
                    telemetry_placeholder.markdown(line_html, unsafe_allow_html=True)
                    status_box.write(f"    [{current_idx}/{total_count}] {b_name} — {em} | {ph}")

                city_label = selected_city["name"] if selected_city else target.label
                enriched_batch = leadcore.enrich_leads_concurrently(
                    unseen_biz,
                    city_name=city_label,
                    default_region=country_code,
                    web_fallback=web_fallback_toggle,
                    include_guessed=guessed_info_toggle,
                    max_workers=5,
                    progress_callback=on_lead_enriched
                )

                # Sequential processing on main thread for verification & atomic writes
                for enriched in enriched_batch:
                    email = enriched.get("email", "")
                    phone = enriched.get("phone", "")
                    phone_e164 = enriched.get("phone_e164", "")
                    biz_name = enriched["business_name"]
                    website = enriched.get("website", "")
                    osm_type = enriched.get("osm_type", "node")
                    osm_id = enriched.get("osm_id", 0)
                    verification_status = enriched.get("verification_status", "no_email" if not email else "unverified")

                    # Shared email detection
                    shared_email = False
                    clean_em = leadcore.safe_clean_str(email).lower()
                    if clean_em:
                        if clean_em in seen_emails:
                            shared_email = True
                        else:
                            seen_emails.add(clean_em)

                    # ZeroBounce verification
                    if email and zb_active and not zb_halted and verification_status != "guessed":
                        try:
                            status_box.write(f"      Verifying deliverability for {email} via ZeroBounce...")
                            zb_status, _ = leadcore.verify_email_zerobounce(email, zb_api_key, verification_cache)
                            verification_status = zb_status
                            status_box.write(f"      ZeroBounce Result: {zb_status}")
                        except leadcore.ZeroBounceHaltException as zb_err:
                            status_box.warning(f"ZeroBounce stopped: {zb_err} Remaining emails marked unverified.")
                            zb_halted = True
                            verification_status = "unverified"

                    # Build context notes
                    notes_parts = []
                    if website:
                        notes_parts.append(f"Website: {website}")
                    else:
                        notes_parts.append("No website")
                    if enriched.get("crawl_diagnostic") and not email and enriched.get("crawl_diagnostic") != "directory domain skipped":
                        notes_parts.append(f"[{enriched['crawl_diagnostic']}]")
                    if enriched.get("email_source"):
                        notes_parts.append(f"[{enriched['email_source']}]")
                    if enriched.get("phone_source") == "Website crawl":
                        notes_parts.append("[Phone: Website crawl]")
                    notes_parts.append(f"[Status: {verification_status}]")
                    if shared_email:
                        notes_parts.append("[Shared Email]")

                    category_label = category_option if category_option != "Custom OSM Tag" else custom_tag

                    row = {
                        "business_name": biz_name,
                        "address": enriched.get("address", ""),
                        "phone": phone,
                        "phone_e164": phone_e164,
                        "email": email,
                        "verification_status": verification_status,
                        "website": website,
                        "maps_url": enriched.get("maps_url", ""),
                        "email_source": enriched.get("email_source", ""),
                        "phone_source": enriched.get("phone_source", ""),
                        "source_url": enriched.get("source_url", ""),
                        "business_type": category_label,
                        "contact_name": "",
                        "contact_method": enriched.get("contact_method", "none"),
                        "context_notes": " ".join(notes_parts),
                        "osm_type": osm_type,
                        "osm_id": osm_id,
                        "latitude": enriched.get("latitude", 0.0),
                        "longitude": enriched.get("longitude", 0.0),
                        "shared_email": shared_email,
                    }

                    # Atomic save of each lead immediately
                    new_leads_this_run.append(row)
                    elem_key = leadcore.get_lead_key(osm_type, osm_id)
                    history_data[elem_key] = {
                        "identifier": elem_key,
                        "business_name": biz_name,
                        "email": email,
                        "date_sourcing": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "verification": verification_status,
                    }
                    leadcore.save_json_atomic(HISTORY_FILE, history_data)
                    if verification_cache:
                        leadcore.save_json_atomic(CACHE_FILE, verification_cache)

                    # Write row atomically to target CSV
                    current_combined = existing_csv_rows + new_leads_this_run
                    leadcore.save_csv_atomic(export_filename, leadcore.CSV_FIELDS, current_combined)

                progress_bar.progress((area_idx + 1) / total_areas)

            except Exception as area_err:
                status_box.error(f"Target '{target.label}' failed: {area_err}")
                failed_areas.append((target.label, str(area_err)))
                progress_bar.progress((area_idx + 1) / total_areas)
                continue

        # End of Run Summary
        status_box.update(label="Lead Discovery Run Finished", state="complete", expanded=False)
        status_box.empty()
        progress_bar.empty()
        telemetry_placeholder.empty()

        all_final_leads = existing_csv_rows + new_leads_this_run
        st.session_state.leads_df = pd.DataFrame(all_final_leads).fillna("")

        total_run_elapsed = time.time() - run_start_time

        # Summary metrics
        osm_emails_count = sum(1 for l in new_leads_this_run if leadcore.safe_clean_str(l.get("email")) and l.get("email_source") == "osm_tag")
        crawl_emails_count = sum(1 for l in new_leads_this_run if leadcore.safe_clean_str(l.get("email")) and l.get("email_source") == "website_crawl")
        osm_phones_count = sum(1 for l in new_leads_this_run if leadcore.safe_clean_str(l.get("phone")) and l.get("phone_source") == "osm_tag")
        crawl_phones_count = sum(1 for l in new_leads_this_run if leadcore.safe_clean_str(l.get("phone")) and l.get("phone_source") == "website_crawl")

        ui.render_run_summary(
            leads_added=len(new_leads_this_run),
            export_filename=export_filename,
            osm_emails=osm_emails_count,
            crawl_emails=crawl_emails_count,
            osm_phones=osm_phones_count,
            crawl_phones=crawl_phones_count,
            elapsed_sec=total_run_elapsed,
            failed_areas=failed_areas
        )

    except Exception as e:
        status_box.error(f"Error during search run: {e}")
    finally:
        st.session_state.scraping_in_progress = False


# ----------------- DISPLAY RESULTS & SEGMENTED TABS -----------------

if st.session_state.leads_df is None and os.path.exists(export_filename):
    try:
        loaded_df = pd.read_csv(export_filename, keep_default_na=False).fillna("")
        records_raw = loaded_df.to_dict(orient="records")
        migrated_records = [leadcore.migrate_lead_record(r) for r in records_raw]
        st.session_state.leads_df = pd.DataFrame(migrated_records).fillna("")
    except Exception:
        pass

# Shared Column Configuration for Dark Console Presentation
DISPLAY_COLUMNS = [
    "business_name", "address", "phone", "email", "verification_status", "website", "maps_url", "source"
]

lead_column_config = {
    "business_name": st.column_config.TextColumn("Business", pinned=True, width="medium"),
    "address": st.column_config.TextColumn("Address", width="medium", help="Physical address from OpenStreetMap"),
    "phone": st.column_config.TextColumn("Phone", width="small", help="Formatted display phone number"),
    "email": st.column_config.TextColumn("Email", width="medium", help="Discovered contact email"),
    "verification_status": st.column_config.TextColumn("Status", width="small", help="Email deliverability status"),
    "website": st.column_config.LinkColumn(
        "Website",
        width="small",
        help="Official business website",
        max_chars=40,
        display_text=r"https?://(?:www\.)?([^/]+)"
    ),
    "maps_url": st.column_config.LinkColumn(
        "Map",
        width="small",
        help="View business location on Google Maps",
        display_text="Open"
    ),
    "source": st.column_config.TextColumn(
        "Source",
        width="small",
        help="Provenance of discovered contact (email source, or phone source if no email)"
    ),
}


def format_df_for_display(source_records: List[Dict[str, Any]]) -> pd.DataFrame:
    """Creates a display-friendly DataFrame with human-readable provenance labels and status dots."""
    df_disp = pd.DataFrame(source_records).fillna("")
    if "email_source" in df_disp.columns:
        df_disp["email_source"] = df_disp["email_source"].map(
            lambda s: ui.SOURCE_DISPLAY_LABELS.get(str(s).lower(), str(s)) if s else ""
        )
    if "phone_source" in df_disp.columns:
        df_disp["phone_source"] = df_disp["phone_source"].map(
            lambda s: ui.SOURCE_DISPLAY_LABELS.get(str(s).lower(), str(s)) if s else ""
        )
    if "verification_status" in df_disp.columns:
        df_disp["verification_status"] = df_disp["verification_status"].map(
            lambda s: ui.get_status_dot_label(str(s)) if s else ""
        )

    # UI "Source" column displays email source, falling back to phone source if no email
    def resolve_source(row):
        em_src = str(row.get("email_source", "")).strip()
        ph_src = str(row.get("phone_source", "")).strip()
        em = str(row.get("email", "")).strip()
        if em and em_src:
            return em_src
        elif ph_src:
            return ph_src
        return em_src or ph_src

    df_disp["source"] = df_disp.apply(resolve_source, axis=1)
    return df_disp


if st.session_state.leads_df is not None and not st.session_state.leads_df.empty:
    df = st.session_state.leads_df.fillna("")
    records = df.to_dict(orient="records")

    # Segmented datasets using leadcore logic
    ready_leads = leadcore.export_leads_ready_for_email(records)
    unverified_leads = leadcore.export_leads_unverified(records)
    phone_leads = leadcore.export_leads_phones(records)
    risky_leads = leadcore.export_leads_risky(records)

    total_count = len(df)
    ready_count = len(ready_leads)
    unverified_count = len(unverified_leads)
    phone_count = len(phone_leads)
    risky_count = len(risky_leads)

    st.markdown("---")
    st.markdown('<div class="sidebar-section-label">Sourced leads</div>', unsafe_allow_html=True)

    # 5 Styled Metrics Cards with status left border and tabular numerals
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        ui.render_metric_card("Total leads", total_count, "all records", "total")
    with c2:
        sub_ready = f"{ready_count / total_count * 100:.1f}% valid" if total_count else "0% valid"
        ui.render_metric_card("Ready for email", ready_count, sub_ready, "valid")
    with c3:
        sub_unver = f"{unverified_count / total_count * 100:.1f}% unverified" if total_count else "0% unverified"
        ui.render_metric_card("Unverified emails", unverified_count, sub_unver, "unverified")
    with c4:
        sub_phone = f"{phone_count / total_count * 100:.1f}% with phone" if total_count else "0% with phone"
        ui.render_metric_card("Phone outreach", phone_count, sub_phone, "phone")
    with c5:
        sub_risky = f"{risky_count / total_count * 100:.1f}% catch-all" if total_count else "0% catch-all"
        ui.render_metric_card("Risky / catch-all", risky_count, sub_risky, "risky")

    is_demo = bool(os.environ.get("LOCALLEADS_DEMO")) or any(".example.com" in str(r.get("website", "")) for r in records)
    if is_demo:
        st.caption("Sample data (fictional)")

    # 5 Segmented Export Tabs (Plain text with count badges)
    t_all, t_valid, t_unverified, t_phones, t_risky = st.tabs([
        f"All leads `{total_count}`",
        f"Ready for email `{ready_count}`",
        f"Unverified emails `{unverified_count}`",
        f"Phone outreach `{phone_count}`",
        f"Risky `{risky_count}`"
    ])

    with t_all:
        st.dataframe(format_df_for_display(records), column_order=DISPLAY_COLUMNS, column_config=lead_column_config, hide_index=True, use_container_width=True)
        csv_all = df.to_csv(index=False).encode("utf-8")
        st.download_button("Download all leads (CSV)", csv_all, "leads_all.csv", "text/csv")

    with t_valid:
        if ready_leads:
            st.dataframe(format_df_for_display(ready_leads), column_order=DISPLAY_COLUMNS, column_config=lead_column_config, hide_index=True, use_container_width=True)
            df_ready = pd.DataFrame(ready_leads)
            csv_ready = df_ready.to_csv(index=False).encode("utf-8")
            st.download_button("Download ready-for-email leads (CSV)", csv_ready, "leads_ready_for_email.csv", "text/csv")
        else:
            st.info("No verified emails yet. Add a ZeroBounce key in the sidebar or check the Unverified tab.")

    with t_unverified:
        if unverified_leads:
            st.dataframe(format_df_for_display(unverified_leads), column_order=DISPLAY_COLUMNS, column_config=lead_column_config, hide_index=True, use_container_width=True)
            df_unverified = pd.DataFrame(unverified_leads)
            csv_unverified = df_unverified.to_csv(index=False).encode("utf-8")
            st.download_button("Download unverified emails (CSV)", csv_unverified, "leads_unverified_emails.csv", "text/csv")
        else:
            st.info("No unverified emails found for these listings.")

    with t_phones:
        if phone_leads:
            st.dataframe(format_df_for_display(phone_leads), column_order=DISPLAY_COLUMNS, column_config=lead_column_config, hide_index=True, use_container_width=True)
            df_phone = pd.DataFrame(phone_leads)
            csv_phone = df_phone.to_csv(index=False).encode("utf-8")
            st.download_button("Download phone outreach leads (CSV)", csv_phone, "leads_phone_outreach.csv", "text/csv")
        else:
            st.info("No phone numbers found for these listings.")

    with t_risky:
        if risky_leads:
            st.dataframe(format_df_for_display(risky_leads), column_order=DISPLAY_COLUMNS, column_config=lead_column_config, hide_index=True, use_container_width=True)
            df_risky = pd.DataFrame(risky_leads)
            csv_risky = df_risky.to_csv(index=False).encode("utf-8")
            st.download_button("Download risky leads (CSV)", csv_risky, "leads_risky_review.csv", "text/csv")
        else:
            st.info("No catch-all or risky email addresses detected.")
else:
    ui.render_empty_state()
