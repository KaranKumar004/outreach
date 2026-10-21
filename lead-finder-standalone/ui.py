"""
ui.py — Dark Console Presentation Engine for LocalLeads Kit.

Presentation logic and styling only; zero crawler, export, or validation logic.
Strict adherence to design specifications:
- Calm, confident B2B dark console palette (:root tokens)
- Robust WCAG AA contrast (>= 4.5:1 text, >= 3:1 non-text borders)
- Zero emoji across all labels, headers, buttons, tabs, alerts, and badges
- Local static font serving (Manrope + JetBrains Mono) with system fallbacks
- Full HTML escaping via html.escape for all user-supplied or dynamic strings (XSS defense)
"""

import html
from typing import Dict, List, Tuple, Optional, Any
import streamlit as st


# =====================================================================
# 1. CSS Design Tokens & Theme Stylesheet
# =====================================================================

# Canonical status colors (WCAG AA compliant >= 4.5:1 against surfaces)
STATUS_COLORS = {
    "valid": "#3DDC97",
    "unverified": "#F5B841",
    "risky": "#FF9F5A",
    "invalid": "#FF6B6B",
    "guessed": "#B79CFF",
    "no_email": "#8B96B4",
    "unknown": "#A9B4D0",
}

STATUS_DISPLAY_LABELS = {
    "valid": "Valid",
    "unverified": "Unverified",
    "risky": "Risky",
    "invalid": "Invalid",
    "guessed": "Guessed",
    "no_email": "No email",
    "unknown": "Unknown",
}

THEME_CSS = """
<style>
/* Local Fonts via Streamlit Static Serving */
@font-face {
  font-family: 'Manrope';
  font-style: normal;
  font-weight: 400 800;
  font-display: swap;
  src: url('/app/static/fonts/manrope-latin.woff2') format('woff2');
}

@font-face {
  font-family: 'JetBrains Mono';
  font-style: normal;
  font-weight: 400 700;
  font-display: swap;
  src: url('/app/static/fonts/jetbrains-mono-latin.woff2') format('woff2');
}

:root {
  /* Surface and Background Hierarchy */
  --bg: #0B1020;
  --sidebar: #0E1528;
  --surface: #121A2F;
  --surface-2: #182240;
  --border: #24304F;
  --border-strong: #56668F;

  /* Typography */
  --text: #E8ECF7;
  --text-2: #9AA6C4;
  --text-3: #8B96B4;

  /* Brand / Action Accents */
  --accent: #6E8BFF;
  --accent-hover: #8AA2FF;
  --on-accent: #0B1020;

  /* Strict Status Taxonomy from Single Source */
  --status-valid: #3DDC97;
  --status-unverified: #F5B841;
  --status-risky: #FF9F5A;
  --status-invalid: #FF6B6B;
  --status-guessed: #B79CFF;
  --status-no-email: #8B96B4;
  --status-unknown: #A9B4D0;

  /* Font Stacks */
  --font-ui: 'Manrope', system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, "Cascadia Mono", Consolas, monospace;
}

/* Global Container & Typography */
html, body, [data-testid="stAppViewContainer"] {
  background-color: var(--bg) !important;
  color: var(--text) !important;
  font-family: var(--font-ui) !important;
  font-size: 15px;
  line-height: 1.5;
}

/* Main Content Constraints (Compact top padding for 768px/720px viewport visibility) */
.main .block-container {
  max-width: 1180px !important;
  padding: 12px 20px !important;
  padding-top: 12px !important;
}

.main [data-testid="stVerticalBlock"] {
  gap: 0.5rem !important;
}

.main [data-testid="stVerticalBlockBorderWrapper"] {
  margin-bottom: 0 !important;
}

/* Hide Streamlit Unwanted Chrome while Preserving Sidebar Toggle */
header[data-testid="stHeader"] {
  display: none !important;
  height: 0 !important;
  min-height: 0 !important;
}
#MainMenu, footer, [data-testid="stToolbar"] {
  display: none !important;
}

/* Sidebar Styling */
[data-testid="stSidebar"] {
  background-color: var(--sidebar) !important;
  border-right: 1px solid var(--border) !important;
  width: 280px !important;
}
[data-testid="stSidebar"] .block-container {
  padding: 20px 14px !important;
}
.sidebar-section-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-3);
  margin-top: 6px;
  margin-bottom: 3px;
}

/* Form Inputs, Selects, Multiselects */
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] div[data-baseweb="select"],
[data-testid="stMultiSelect"] div[data-baseweb="select"] {
  background-color: #0E1528 !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: 8px !important;
  color: var(--text) !important;
  font-family: var(--font-ui) !important;
  font-size: 13px !important;
  min-height: 38px !important;
  height: 38px !important;
  transition: border-color 150ms ease, box-shadow 150ms ease;
}

[data-testid="stTextInput"] input:focus,
[data-testid="stSelectbox"] div[data-baseweb="select"]:focus-within,
[data-testid="stMultiSelect"] div[data-baseweb="select"]:focus-within {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 2px rgba(110, 139, 255, 0.3) !important;
  outline: none !important;
}

/* Input Field Labels */
[data-testid="stWidgetLabel"] {
  min-height: 0 !important;
  margin-bottom: 2px !important;
}
[data-testid="stWidgetLabel"] label {
  font-size: 12px !important;
  font-weight: 600 !important;
  color: var(--text-2) !important;
}

/* Primary Action Button */
[data-testid="stButton"] button[kind="primary"],
.stButton button[kind="primary"],
[data-testid="stBaseButton-primary"] {
  background-color: var(--accent) !important;
  color: var(--on-accent) !important;
  font-family: var(--font-ui) !important;
  font-weight: 600 !important;
  font-size: 15px !important;
  height: 44px !important;
  border-radius: 10px !important;
  border: none !important;
  padding: 0 24px !important;
  transition: background-color 150ms ease, transform 150ms ease;
  box-shadow: none !important;
}

[data-testid="stButton"] button[kind="primary"]:hover:not(:disabled),
[data-testid="stBaseButton-primary"]:hover:not(:disabled) {
  background-color: var(--accent-hover) !important;
  color: var(--on-accent) !important;
}

[data-testid="stButton"] button[kind="primary"]:disabled,
[data-testid="stBaseButton-primary"]:disabled {
  opacity: 0.4 !important;
  cursor: not-allowed !important;
  background-color: var(--accent) !important;
  color: var(--on-accent) !important;
}

/* Secondary & Download Buttons */
[data-testid="stButton"] button[kind="secondary"],
[data-testid="stDownloadButton"] button {
  background-color: transparent !important;
  color: var(--text) !important;
  font-family: var(--font-ui) !important;
  font-weight: 600 !important;
  font-size: 14px !important;
  height: 40px !important;
  border-radius: 10px !important;
  border: 1px solid var(--border-strong) !important;
  transition: border-color 150ms ease, color 150ms ease, background-color 150ms ease;
}

[data-testid="stButton"] button[kind="secondary"]:hover,
[data-testid="stDownloadButton"] button:hover {
  border-color: var(--accent) !important;
  color: var(--accent) !important;
  background-color: rgba(110, 139, 255, 0.08) !important;
}

/* Header Component */
.header-card {
  background: linear-gradient(135deg, var(--surface) 0%, var(--surface-2) 100%);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 14px;
  margin-bottom: 6px;
  position: relative;
  overflow: hidden;
}

.header-card::after {
  content: "";
  position: absolute;
  top: 0;
  right: 0;
  width: 140px;
  height: 60px;
  background: radial-gradient(circle at top right, rgba(110, 139, 255, 0.12), transparent 70%);
  pointer-events: none;
}

.header-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.header-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.02em;
  margin: 0;
}

.version-pill {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  background-color: rgba(110, 139, 255, 0.12);
  border: 1px solid rgba(110, 139, 255, 0.28);
  border-radius: 14px;
  padding: 2px 8px;
}

.header-desc {
  font-size: 12px;
  color: var(--text-2);
  margin-top: 1px;
  margin-bottom: 0;
}

/* Stepper Component */
.stepper-container {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  background-color: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 6px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-3);
}

.step-item.active {
  color: var(--text);
}

.step-item.completed {
  color: var(--status-valid);
}

.step-circle {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 1px solid var(--border-strong);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  background-color: var(--sidebar);
  color: var(--text-3);
}

.step-item.active .step-circle {
  border-color: var(--accent);
  background-color: var(--accent);
  color: var(--on-accent);
}

.step-item.completed .step-circle {
  border-color: var(--status-valid);
  background-color: rgba(61, 220, 151, 0.15);
  color: var(--status-valid);
}

.step-divider {
  flex: 1;
  height: 1px;
  background-color: var(--border);
}

/* Metric Cards */
.metric-card {
  background-color: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--metric-border, var(--accent));
  border-radius: 14px;
  padding: 16px 18px;
  height: 100%;
}

.metric-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-2);
  margin-bottom: 4px;
  word-break: keep-all !important;
  hyphens: none !important;
  overflow-wrap: normal !important;
}

.metric-value {
  font-family: var(--font-mono);
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  margin-bottom: 4px;
}

.metric-caption {
  font-size: 12px;
  color: var(--text-3);
}

/* Tab Component Styling */
[data-testid="stTabs"] [role="tablist"] {
  overflow-x: auto !important;
  scrollbar-width: thin !important;
  display: flex !important;
  flex-wrap: nowrap !important;
  gap: 8px !important;
  -webkit-overflow-scrolling: touch !important;
  mask-image: linear-gradient(to right, black 88%, transparent 100%);
  -webkit-mask-image: linear-gradient(to right, black 88%, transparent 100%);
}

[data-testid="stTabs"] button[role="tab"] {
  color: var(--text-2) !important;
  font-family: var(--font-ui) !important;
  font-size: 13px !important;
  font-weight: 600 !important;
  border: none !important;
  padding: 8px 14px !important;
  background: transparent !important;
  white-space: nowrap !important;
}

[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
  color: var(--text) !important;
  border-bottom: 2px solid var(--accent) !important;
}

.tab-badge,
[data-testid="stTab"] code,
button[role="tab"] code {
  font-family: var(--font-mono) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  padding: 2px 7px !important;
  border-radius: 10px !important;
  background-color: var(--surface-2) !important;
  color: var(--accent) !important;
  border: 1px solid var(--border) !important;
  margin-left: 6px !important;
}

[aria-selected="true"] .tab-badge,
[data-testid="stTab"][aria-selected="true"] code,
button[role="tab"][aria-selected="true"] code {
  background-color: rgba(110, 139, 255, 0.2) !important;
  color: var(--accent) !important;
  border-color: rgba(110, 139, 255, 0.4) !important;
}

/* Status Dot with Text */
.status-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.status-dot.valid { background-color: var(--status-valid); }
.status-dot.unverified { background-color: var(--status-unverified); }
.status-dot.risky { background-color: var(--status-risky); }
.status-dot.invalid { background-color: var(--status-invalid); }
.status-dot.guessed { background-color: var(--status-guessed); }
.status-dot.no_email { background-color: var(--status-no-email); }
.status-dot.unknown { background-color: var(--status-unknown); }

/* Run Summary Card */
.run-summary-card {
  background-color: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 12px;
  padding: 20px 24px;
  margin: 20px 0;
}

.run-summary-card.has-failures {
  border-left-color: var(--status-invalid);
}

.summary-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 12px;
}

.yield-split-row {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.yield-split-item {
  font-size: 13px;
  color: var(--text-2);
}

.yield-split-item strong {
  color: var(--text);
  font-family: var(--font-mono);
}

/* Empty State Card */
.empty-state-card {
  background-color: var(--surface);
  border: 1px dashed var(--border-strong);
  border-radius: 14px;
  padding: 48px 32px;
  text-align: center;
  margin: 32px 0;
}

.empty-state-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 8px;
}

.empty-state-desc {
  font-size: 14px;
  color: var(--text-2);
  max-width: 520px;
  margin: 0 auto 24px auto;
  line-height: 1.6;
}

.chips-container {
  display: flex;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
}

.chip-item {
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 500;
  padding: 6px 14px;
  border-radius: 20px;
  background-color: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-2);
}

/* Dataframe Styling (Horizontal scroll contained) */
[data-testid="stDataFrame"] {
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
  overflow-x: auto !important;
}

/* Telemetry Monospace Progress Panel */
.telemetry-panel {
  background-color: #0E1528;
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: 8px;
  padding: 8px 12px;
  margin: 10px 0;
  font-family: var(--font-mono);
  font-size: 11px;
}

.telemetry-line {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-2);
  padding: 2px 0;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Responsive Overrides */
@media (max-width: 1100px) {
  [data-testid="stSidebar"] {
    width: 280px !important;
  }
}

@media (max-width: 1100px) and (min-width: 641px) {
  [data-testid="stHorizontalBlock"]:has(.metric-card) {
    display: grid !important;
    grid-template-columns: repeat(3, 1fr) !important;
    gap: 12px !important;
  }
  .metric-label {
    font-size: 11px !important;
    word-break: keep-all !important;
    hyphens: none !important;
    overflow-wrap: normal !important;
  }
}

@media (max-width: 640px) {
  .main .block-container {
    padding: 14px !important;
    padding-top: 14px !important;
  }
  .stepper-container {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
  .step-divider {
    display: none;
  }
  [data-testid="stHorizontalBlock"]:has(.metric-card) {
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    gap: 10px !important;
  }
  [data-testid="stHorizontalBlock"]:has(.metric-card) > div[data-testid="column"]:nth-child(5) {
    grid-column: span 2 !important;
  }
  .metric-label {
    font-size: 10px !important;
    word-break: keep-all !important;
    hyphens: none !important;
    overflow-wrap: normal !important;
  }
}

/* Reduced Motion Compliance */
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
"""


def inject_theme_css() -> None:
    """Injects the core dark console stylesheet once into the Streamlit app."""
    st.markdown(THEME_CSS, unsafe_allow_html=True)


# =====================================================================
# 2. Reusable Visual Components with Strict html.escape Defense
# =====================================================================

SOURCE_DISPLAY_LABELS = {
    "osm_tag": "OSM Tag",
    "website_crawl": "Website Crawl",
    "search_snippet": "Search Snippet",
    "guessed_domain": "Domain Guess",
}


def render_header(version: str, support_email: str, verified_credits_active: bool = False) -> None:
    """Renders the top console header with version pill and honest, de-hyped value prop."""
    v_clean = html.escape(str(version))
    email_clean = html.escape(str(support_email))
    if verified_credits_active:
        desc_text = "Find local businesses, websites, phone numbers, and verified email addresses."
    else:
        desc_text = "Find local businesses, websites, phone numbers, and public contact emails."
    desc_clean = html.escape(desc_text)
    header_html = f"""
    <div class="header-card">
        <div class="header-title-row">
            <h1 class="header-title">LocalLeads Kit</h1>
            <span class="version-pill">v{v_clean}</span>
        </div>
        <p class="header-desc">
            {desc_clean}
        </p>
    </div>
    """
    st.markdown(header_html, unsafe_allow_html=True)


def render_stepper(current_step: int = 1) -> None:
    """
    Renders the horizontal numbered workflow stepper (1 Contact, 2 Target, 3 Run).
    Includes aria-current="step" on the active step for accessibility.
    """
    s1 = (current_step == 1)
    s2 = (current_step == 2)
    s3 = (current_step == 3)

    step1_class = "step-item active" if s1 else ("step-item completed" if current_step > 1 else "step-item")
    step2_class = "step-item active" if s2 else ("step-item completed" if current_step > 2 else "step-item")
    step3_class = "step-item active" if s3 else "step-item"

    aria1 = ' aria-current="step"' if s1 else ""
    aria2 = ' aria-current="step"' if s2 else ""
    aria3 = ' aria-current="step"' if s3 else ""

    stepper_html = f"""
    <div class="stepper-container" role="navigation" aria-label="Progress">
        <div class="{step1_class}"{aria1}>
            <span class="step-circle">1</span>
            <span>Contact</span>
        </div>
        <div class="step-divider"></div>
        <div class="{step2_class}"{aria2}>
            <span class="step-circle">2</span>
            <span>Target</span>
        </div>
        <div class="step-divider"></div>
        <div class="{step3_class}"{aria3}>
            <span class="step-circle">3</span>
            <span>Run</span>
        </div>
    </div>
    """
    st.markdown(stepper_html, unsafe_allow_html=True)


def render_metric_card(label: str, value: int, subcaption: str, status_key: str = "valid") -> None:
    """
    Renders a styled telemetry metric card with a 3px left status border
    and tabular numeral typography.
    """
    lbl_clean = html.escape(str(label))
    val_clean = html.escape(str(value))
    sub_clean = html.escape(str(subcaption))

    color_map = {
        "total": "var(--text-3)",
        "valid": STATUS_COLORS["valid"],
        "unverified": STATUS_COLORS["unverified"],
        "phone": "var(--accent)",
        "risky": STATUS_COLORS["risky"],
    }
    border_color = color_map.get(status_key, "var(--accent)")

    card_html = f"""
    <div class="metric-card" style="--metric-border: {border_color};">
        <div class="metric-label">{lbl_clean}</div>
        <div class="metric-value">{val_clean}</div>
        <div class="metric-caption">{sub_clean}</div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)


def render_empty_state() -> None:
    """Renders the centered dashed card before first lead discovery run."""
    chips = ["Dentists in Austin, Texas", "Accountants in London", "Plumbers in Sydney"]
    chips_html = "".join([f'<span class="chip-item">{html.escape(c)}</span>' for c in chips])

    empty_html = f"""
    <div class="empty-state-card">
        <div class="empty-state-title">No leads yet</div>
        <div class="empty-state-desc">
            Provide your contact email above, select a country, region, and city,
            choose your business category, and select Start Sourcing Leads.
        </div>
        <div class="chips-container">
            {chips_html}
        </div>
    </div>
    """
    st.markdown(empty_html, unsafe_allow_html=True)


def render_run_summary(
    leads_added: int,
    export_filename: str,
    osm_emails: int,
    crawl_emails: int,
    osm_phones: int,
    crawl_phones: int,
    elapsed_sec: float = 0.0,
    failed_areas: Optional[List[Tuple[str, str]]] = None
) -> None:
    """Renders the end-of-run summary card with yield source attribution and elapsed time."""
    has_failures = bool(failed_areas)
    card_class = "run-summary-card has-failures" if has_failures else "run-summary-card"

    fname_clean = html.escape(str(export_filename))
    added_clean = html.escape(str(leads_added))
    elapsed_text = f" in {elapsed_sec:.1f}s" if elapsed_sec > 0 else ""

    summary_html = f"""
    <div class="{card_class}">
        <div class="summary-title">Run finished{elapsed_text}: {added_clean} new leads saved to {fname_clean}</div>
        <div class="yield-split-row">
            <div class="yield-split-item">
                Emails: <strong>{osm_emails + crawl_emails}</strong>
                (OSM tags: {osm_emails}, Website crawl: {crawl_emails})
            </div>
            <div class="yield-split-item">
                Phones: <strong>{osm_phones + crawl_phones}</strong>
                (OSM tags: {osm_phones}, Website crawl: {crawl_phones})
            </div>
        </div>
    </div>
    """
    st.markdown(summary_html, unsafe_allow_html=True)

    if failed_areas:
        for area_name, reason in failed_areas:
            a_clean = html.escape(str(area_name))
            r_clean = html.escape(str(reason))
            st.warning(f"Area {a_clean} could not be processed: {r_clean}")


def render_status_badge(status: str) -> str:
    """Returns HTML for a colored status dot + text label."""
    s_clean = html.escape(str(status))
    dot_class = s_clean.lower().replace(" ", "_")
    return f'<span class="status-indicator"><span class="status-dot {dot_class}"></span>{s_clean}</span>'


def get_status_dot_label(status_raw: str) -> str:
    """
    Returns friendly label with a unicode dot:
    ● Valid, ● Unverified, ● Risky, ● Invalid, ● Guessed, ● No email.
    """
    s = str(status_raw or "").strip().lower()
    label = STATUS_DISPLAY_LABELS.get(s, STATUS_DISPLAY_LABELS.get("no_email", "No email"))
    return f"● {label}"


def render_telemetry_panel(lines: List[str]) -> str:
    """
    Renders up to 8 live telemetry lines in a monospace dark console panel.
    All lines are escaped via html.escape for safety.
    """
    inner = "".join([f'<div class="telemetry-line">{html.escape(l)}</div>' for l in lines])
    return f'<div class="telemetry-panel" role="log" aria-live="polite">{inner}</div>'


def render_live_telemetry_line(
    business_name: str,
    area: str,
    step: str,
    status: str,
    elapsed_sec: float = 0.0
) -> str:
    """
    Renders a single-line live telemetry indicator with strict html.escape on all dynamic values.
    Shows current business, area, step, and status.
    """
    b_clean = html.escape(str(business_name or "—"))
    a_clean = html.escape(str(area or "—"))
    s_clean = html.escape(str(step or "—"))
    stat_clean = html.escape(str(status or "—"))
    elapsed_text = f" ({elapsed_sec:.1f}s)" if elapsed_sec > 0 else ""
    return (
        f'<div class="telemetry-panel" role="log" aria-live="polite">'
        f'<div class="telemetry-line">'
        f'<span style="color: var(--accent); font-weight: 600;">[{a_clean}]</span> '
        f'<strong>{b_clean}</strong> '
        f'<span style="color: var(--text-3);">— Step: {s_clean} | Status: {stat_clean}{elapsed_text}</span>'
        f'</div>'
        f'</div>'
    )

