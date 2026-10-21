"""
Competitor Intelligence Diff Summarizer
---------------------------------------
Queries changedetection.io REST API and transforms technical web diffs
into executive plain-English summaries for gym/fitness clients (e.g., Akash @ Impact Fitness Studio).

Can output plain text (for WhatsApp / Email) or JSON (for Supabase / Next.js dashboard ingestion).
"""

import os
import sys

# Ensure UTF-8 output on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
import json
import re
import difflib
import argparse
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

DEFAULT_BASE_URL = os.getenv("CHANGEDETECTION_URL", "http://127.0.0.1:5000")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "changedetection-data")


def get_default_api_key() -> str:
    """Read API key from environment variable or local changedetection data file."""
    env_key = os.getenv("CHANGEDETECTION_API_KEY")
    if env_key:
        return env_key
    
    settings_file = os.path.join(DATA_DIR, "url-watches.json")
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                token = data.get("settings", {}).get("application", {}).get("api_access_token", "")
                if token:
                    return token
        except Exception:
            pass
        # Fallback regex search in json file
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                content = f.read()
                m = re.search(r'"api_access_token":\s*"([a-f0-9]+)"', content)
                if m:
                    return m.group(1)
        except Exception:
            pass
    return ""


class ChangeDetectionClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or get_default_api_key()
        if not self.api_key:
            raise ValueError("No API key provided and none found in changedetection-data/url-watches.json")

    def _request(self, endpoint: str, method: str = "GET", data: Optional[dict] = None) -> Any:
        url = f"{self.base_url}{endpoint}"
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "LeadPilot-CompetitorMonitor/1.0"
        }
        encoded_data = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code} from changedetection.io: {err_body}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to changedetection.io at {url}: {e}")

    def get_watches(self, tag: Optional[str] = None) -> Dict[str, Any]:
        """Fetch all watches or watches matching a specific tag."""
        endpoint = "/api/v1/watch"
        if tag:
            endpoint += f"?tag={tag}"
        return self._request(endpoint)

    def get_watch_info(self, uuid: str) -> Dict[str, Any]:
        """Fetch metadata for a single watch."""
        return self._request(f"/api/v1/watch/{uuid}")

    def get_watch_history(self, uuid: str) -> Dict[str, str]:
        """Fetch map of {timestamp: file_path} for available snapshots."""
        return self._request(f"/api/v1/watch/{uuid}/history")

    def get_snapshot(self, uuid: str, timestamp: str = "latest") -> str:
        """Fetch the text content of a specific snapshot."""
        return self._request(f"/api/v1/watch/{uuid}/history/{timestamp}")


def clean_snapshot_lines(text: str) -> List[str]:
    """Clean whitespace and empty lines from snapshot text."""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line and line != "?" and not line.startswith("&"):
            lines.append(line)
    return lines


def classify_line_type(text: str) -> str:
    """Classify the content type of a change line (price, schedule, or general)."""
    text_lower = text.lower()
    
    # Check for pricing cues
    price_patterns = [r"₹", r"rs\.?", r"inr", r"/\s*month", r"/\s*year", r"quarterly", r"annual", r"fee", r"price", r"cost"]
    if any(re.search(p, text_lower) for p in price_patterns):
        return "pricing"
    
    # Check for schedule & timing cues
    time_patterns = [r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", r"batch", r"morning", r"evening", r"monday", r"tuesday", r"wednesday", r"thursday", r"friday", r"saturday", r"sunday", r"session", r"slot"]
    if any(re.search(p, text_lower) for p in time_patterns):
        return "schedule"
    
    return "service"


def summarize_diff(before_text: str, after_text: str, competitor_name: str, url: str) -> Dict[str, Any]:
    """
    Compare before and after text blocks, categorizing changes into
    plain English bullet points for prices, schedules, and services.
    """
    before_lines = clean_snapshot_lines(before_text)
    after_lines = clean_snapshot_lines(after_text)

    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
    
    pricing_updates = []
    schedule_updates = []
    general_updates = []

    for tag, alo, ahi, blo, bhi in matcher.get_opcodes():
        if tag == "equal":
            continue
        
        removed = before_lines[alo:ahi]
        added = after_lines[blo:bhi]

        # Case 1: Replacement (changed from X to Y)
        if tag == "replace":
            for r_item, a_item in zip(removed, added):
                c_type = classify_line_type(r_item) or classify_line_type(a_item)
                if c_type == "pricing":
                    pricing_updates.append(f"Price updated from '{r_item}' to '{a_item}'")
                elif c_type == "schedule":
                    schedule_updates.append(f"Timing adjusted from '{r_item}' to '{a_item}'")
                else:
                    general_updates.append(f"Changed '{r_item}' to '{a_item}'")
            
            # Remaining leftovers in replacement
            if len(removed) > len(added):
                for r_item in removed[len(added):]:
                    c_type = classify_line_type(r_item)
                    if c_type == "pricing":
                        pricing_updates.append(f"Discontinued pricing option: '{r_item}'")
                    elif c_type == "schedule":
                        schedule_updates.append(f"Removed batch slot: '{r_item}'")
                    else:
                        general_updates.append(f"Removed: '{r_item}'")
            elif len(added) > len(removed):
                for a_item in added[len(removed):]:
                    c_type = classify_line_type(a_item)
                    if c_type == "pricing":
                        pricing_updates.append(f"Introduced new pricing: '{a_item}'")
                    elif c_type == "schedule":
                        schedule_updates.append(f"Added new batch slot: '{a_item}'")
                    else:
                        general_updates.append(f"New addition: '{a_item}'")

        # Case 2: Pure insertion (new content added)
        elif tag == "insert":
            for a_item in added:
                c_type = classify_line_type(a_item)
                if c_type == "pricing":
                    pricing_updates.append(f"New rate/plan added: '{a_item}'")
                elif c_type == "schedule":
                    schedule_updates.append(f"New session added: '{a_item}'")
                else:
                    general_updates.append(f"Added: '{a_item}'")

        # Case 3: Pure deletion (content removed)
        elif tag == "delete":
            for r_item in removed:
                c_type = classify_line_type(r_item)
                if c_type == "pricing":
                    pricing_updates.append(f"Removed rate: '{r_item}'")
                elif c_type == "schedule":
                    schedule_updates.append(f"Discontinued session: '{r_item}'")
                else:
                    general_updates.append(f"Removed: '{r_item}'")

    total_changes = len(pricing_updates) + len(schedule_updates) + len(general_updates)

    return {
        "competitor": competitor_name,
        "url": url,
        "total_changes": total_changes,
        "pricing_updates": pricing_updates,
        "schedule_updates": schedule_updates,
        "general_updates": general_updates
    }


def format_executive_report(summaries: List[Dict[str, Any]], client_name: str = "Akash", business_name: str = "Impact Fitness Studio") -> str:
    """Format summaries into an executive plain English briefing."""
    timestamp = datetime.now().strftime("%d %b %Y, %I:%M %p IST")
    report = []
    report.append("=" * 64)
    report.append(f"📊 COMPETITOR INTELLIGENCE BRIEF — {business_name.upper()}")
    report.append(f"Prepared for: {client_name} | Generated: {timestamp}")
    report.append("=" * 64)
    report.append("")

    active_changes = [s for s in summaries if s["total_changes"] > 0]

    if not active_changes:
        report.append("✅ No competitor price or schedule adjustments detected in the latest cycle.")
        report.append("   All monitored competitors are maintaining their previous offerings.")
        report.append("")
        for s in summaries:
            report.append(f"   • {s['competitor']}: Monitored (0 changes) [{s['url']}]")
        report.append("=" * 64)
        return "\n".join(report)

    report.append(f"⚠️  {len(active_changes)} competitor(s) have updated their offerings or schedules:\n")

    for s in active_changes:
        report.append(f"🏋️  {s['competitor']}")
        report.append(f"    Source: {s['url']}")
        report.append(f"    Changes Detected: {s['total_changes']}")
        report.append("    Key Highlights:")

        if s["pricing_updates"]:
            report.append("    💰 Pricing Changes:")
            for p in s["pricing_updates"]:
                report.append(f"       • {p}")

        if s["schedule_updates"]:
            report.append("    ⏰ Batch & Schedule Changes:")
            for sc in s["schedule_updates"]:
                report.append(f"       • {sc}")

        if s["general_updates"]:
            report.append("    📌 Program & Service Updates:")
            for g in s["general_updates"]:
                report.append(f"       • {g}")

        report.append("-" * 64)

    report.append("\n💡 Actionable Insight for Impact Fitness Studio:")
    report.append("   Review the updated slots and pricing above to calibrate your own monthly promotions,")
    report.append("   trainer availability, and member retention incentives accordingly.")
    report.append("=" * 64)

    return "\n".join(report)


def run_simulation() -> str:
    """
    Run a simulation demonstrating how a real competitor shift is parsed into plain English.
    Useful for immediate proof demo with Akash without waiting for live website updates.
    """
    sim_before = """
BATCH DETAILS
IN CENTER DETAILS
Morning sessions:
Monday to Saturday
7:00-8:00AM, 8:30-9:30AM
Evening sessions:
Monday to Friday
5-6PM, 7-8PM
Standard Quarterly Pass: Rs. 14,000 / 3 months
Annual Unlimited: Rs. 38,000 / year
"""

    sim_after = """
BATCH DETAILS
IN CENTER DETAILS
Morning sessions:
Monday to Saturday
6:00-7:00AM, 7:00-8:00AM, 8:30-9:30AM
Evening sessions:
Monday to Friday
5-6PM, 7-8PM
Weekend CrossFit Special: Saturday & Sunday 9:00AM
Standard Quarterly Pass: Rs. 12,500 / 3 months (Limited Festival Offer)
Annual Unlimited: Rs. 38,000 / year
Personal Training Add-on: Rs. 5,000 / month
"""

    diff_summary = summarize_diff(
        before_text=sim_before,
        after_text=sim_after,
        competitor_name="Academy of Strength (Indiranagar)",
        url="https://www.academyofstrength.in/"
    )

    baseline_chisel = {
        "competitor": "Chisel Fitness (Bengaluru)",
        "url": "https://chisel.co.in/",
        "total_changes": 0,
        "pricing_updates": [],
        "schedule_updates": [],
        "general_updates": []
    }

    return format_executive_report([diff_summary, baseline_chisel])


def main():
    parser = argparse.ArgumentParser(description="Competitor Diff Summarizer for Changedetection.io")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="Base URL of changedetection.io")
    parser.add_argument("--api-key", default=None, help="Changedetection API Key")
    parser.add_argument("--tag", default="competitor-gyms", help="Filter watches by tag (default: competitor-gyms)")
    parser.add_argument("--watch-uuid", default=None, help="Inspect a specific watch by UUID")
    parser.add_argument("--simulate", action="store_true", help="Run with simulated competitor change for client demo")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format (for Next.js / Supabase dashboard)")
    args = parser.parse_args()

    if args.simulate:
        if args.json:
            sim_report = run_simulation()
            print(json.dumps({"mode": "simulation", "content": sim_report}, indent=2))
        else:
            print(run_simulation())
        return

    try:
        client = ChangeDetectionClient(base_url=args.url, api_key=args.api_key)
    except Exception as e:
        print(f"Error initializing client: {e}", file=sys.stderr)
        print("Tip: If running without Changedetection, run with --simulate to see the formatted demo.", file=sys.stderr)
        sys.exit(1)

    try:
        watches = client.get_watches(tag=args.tag)
    except Exception as e:
        print(f"Error connecting to changedetection API: {e}", file=sys.stderr)
        sys.exit(1)

    target_uuids = [args.watch_uuid] if args.watch_uuid else list(watches.keys())
    summaries = []

    for uuid in target_uuids:
        watch_data = watches.get(uuid)
        if not watch_data:
            continue
        
        watch_title = watch_data.get("title") or watch_data.get("url") or uuid
        watch_url = watch_data.get("url", "")
        
        # Skip default hackernews / changelog if filtering by tag
        if args.tag and "news.ycombinator" in watch_url:
            continue

        try:
            history = client.get_watch_history(uuid)
        except Exception:
            history = {}

        history_keys = sorted(list(history.keys()), key=lambda x: int(x) if x.isdigit() else 0)

        if len(history_keys) < 2:
            # Baseline snapshot only (no diff yet)
            summaries.append({
                "competitor": watch_title,
                "url": watch_url,
                "total_changes": 0,
                "pricing_updates": [],
                "schedule_updates": [],
                "general_updates": []
            })
            continue

        # Get previous snapshot and latest snapshot
        prev_ts = history_keys[-2]
        curr_ts = history_keys[-1]

        try:
            prev_content = client.get_snapshot(uuid, prev_ts)
            curr_content = client.get_snapshot(uuid, curr_ts)
            summary = summarize_diff(prev_content, curr_content, competitor_name=watch_title, url=watch_url)
            summaries.append(summary)
        except Exception as e:
            print(f"Warning: Failed to diff snapshots for {watch_title}: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps(summaries, indent=2))
    else:
        print(format_executive_report(summaries))


if __name__ == "__main__":
    main()
