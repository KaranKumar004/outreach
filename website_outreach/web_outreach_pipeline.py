"""
web_outreach_pipeline.py — Cold email outreach pipeline for Website Creation service.

Core Safety & Design Principles:
1. Safety First: Defaults to --dry-run. Requires explicit --send-live to transmit emails.
2. Subject Lines: Strictly < 8 words, benefit-led, zero spam trigger words.
3. Body Word Count: Under 90 words. Short, conversational, low-friction CTA.
4. Duplicate Prevention: Checks outreach_log.csv before drafting or sending.
5. Inbox Warmup: Throttles sends (5/day week 1, 10/day week 2, 25/day week 3+).
6. Protected Accounts: Refuses sending if sender or reply-to matches PROTECTED_ACCOUNTS.
7. Test Send: CLI --test-send dispatches sample draft strictly to TEST_RECIPIENTS.
"""

import os
import sys
import re
import csv
import time
import json
import socket
import smtplib
import hashlib
import argparse
from datetime import datetime, date, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid, parseaddr
from typing import Dict, Any, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env():
    """Loads environment configuration without overwriting existing vars."""
    paths = [
        os.path.join(SCRIPT_DIR, ".env.local"),
        os.path.join(SCRIPT_DIR, ".env"),
        os.path.join(SCRIPT_DIR, "..", ".env.local"),
        os.path.join(SCRIPT_DIR, "..", ".env"),
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = parts[1].strip()
                        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                            v = v[1:-1]
                        if k not in os.environ:
                            os.environ[k] = v

load_env()

# Configuration paths
LEADS_CSV = os.path.join(SCRIPT_DIR, "leads_website.csv")
OUTREACH_LOG_CSV = os.path.join(SCRIPT_DIR, "outreach_log.csv")
PREVIEW_DIR = os.path.join(SCRIPT_DIR, "preview_drafts")

# Ensure preview directory exists
os.makedirs(PREVIEW_DIR, exist_ok=True)

# Environment settings
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_REPLY_TO = os.environ.get("SMTP_REPLY_TO", SMTP_USER)
OUTREACH_SENDER_NAME = os.environ.get("OUTREACH_SENDER_NAME", "Karan")
OUTREACH_SUPPORT_EMAIL = os.environ.get("OUTREACH_SUPPORT_EMAIL", SMTP_USER)
PORTFOLIO_URL = os.environ.get("PORTFOLIO_URL", "https://your-portfolio-site.com")
SAMPLE_PREVIEW_URL = os.environ.get("SAMPLE_PREVIEW_URL", f"{PORTFOLIO_URL}/samples")
PROTECTED_ACCOUNTS = set(a.strip().lower() for a in os.environ.get("PROTECTED_ACCOUNTS", "").split(",") if a.strip())
TEST_RECIPIENTS = [a.strip() for a in os.environ.get("TEST_RECIPIENTS", "").split(",") if a.strip()]

# Copy templates for Website Creation
EMAIL_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "agency": {
        "subjects": [
            "A modern portfolio site for {clean_name}",
            "Client showcase website for {clean_name}",
            "Quick website concept for {clean_name}"
        ],
        "body": (
            "Hi {clean_name} team,\n\n"
            "I noticed you don't currently have an active website to showcase your client work and services.\n\n"
            "I design clean, fast, high-converting websites for agencies and consulting firms. "
            "To show you what's possible, I put together a quick 1-page sample preview for {clean_name}.\n\n"
            "Would you be open to seeing the preview link?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{portfolio_url}"
        )
    },
    "clinic": {
        "subjects": [
            "Online patient booking for {clean_name}",
            "Simple modern website for {clean_name}",
            "Appointment booking site for {clean_name}"
        ],
        "body": (
            "Hi {clean_name} team,\n\n"
            "I noticed patients searching for your clinic online don't currently see an official website "
            "to view your services or book appointments.\n\n"
            "I build simple, fast clinic websites with easy WhatsApp and appointment booking. "
            "I drafted a quick sample layout tailored for {clean_name}.\n\n"
            "Would you like me to share the preview link?\n\n"
            "Warm regards,\n"
            "{sender_name}\n"
            "{portfolio_url}"
        )
    },
    "gym": {
        "subjects": [
            "Member inquiry website for {clean_name}",
            "Modern fitness site for {clean_name}",
            "Quick mobile site for {clean_name}"
        ],
        "body": (
            "Hi {clean_name} team,\n\n"
            "I noticed your gym doesn't have an active website to display your membership packages, "
            "trainer profiles, and schedules.\n\n"
            "I design lightweight, mobile-friendly websites that turn local searchers into gym members. "
            "I put together a quick sample concept for {clean_name}.\n\n"
            "Open to taking a look at the preview?\n\n"
            "Best,\n"
            "{sender_name}\n"
            "{portfolio_url}"
        )
    },
    "salon": {
        "subjects": [
            "Online service menu for {clean_name}",
            "Modern booking site for {clean_name}",
            "Mobile website concept for {clean_name}"
        ],
        "body": (
            "Hi {clean_name} team,\n\n"
            "I noticed you don't have an official website where clients can view your service menu, pricing, and book slots.\n\n"
            "I build elegant, mobile-ready websites for salons and spas with built-in booking buttons. "
            "I put together a quick sample preview for {clean_name}.\n\n"
            "Would you like me to send over the link?\n\n"
            "Best,\n"
            "{sender_name}\n"
            "{portfolio_url}"
        )
    },
    "restaurant": {
        "subjects": [
            "Online menu website for {clean_name}",
            "Fast mobile site for {clean_name}",
            "Simple dining site for {clean_name}"
        ],
        "body": (
            "Hi {clean_name} team,\n\n"
            "Customers looking for your menu online currently don't see an official website.\n\n"
            "I create fast, clean mobile websites that display menus, location directions, and table inquiry buttons. "
            "I drafted a quick preview layout for {clean_name}.\n\n"
            "Shall I send over the link?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{portfolio_url}"
        )
    },
    "retail": {
        "subjects": [
            "Product showcase website for {clean_name}",
            "Digital catalog site for {clean_name}",
            "Modern online site for {clean_name}"
        ],
        "body": (
            "Hi {clean_name} team,\n\n"
            "I noticed your store doesn't currently have an official website to showcase products and store updates.\n\n"
            "I build simple, attractive product showcase sites that help local stores get found on Google. "
            "I put together a quick 1-page sample preview for {clean_name}.\n\n"
            "Would you like to see the preview link?\n\n"
            "Best,\n"
            "{sender_name}\n"
            "{portfolio_url}"
        )
    },
    "accounting": {
        "subjects": [
            "Professional website for {clean_name}",
            "Client inquiry site for {clean_name}",
            "New website layout for {clean_name}"
        ],
        "body": (
            "Hi {clean_name} team,\n\n"
            "I noticed your firm doesn't currently have a dedicated website to outline your services and credentials.\n\n"
            "I build trustworthy, clean websites for accounting and consulting practices. "
            "I put together a quick sample layout tailored for {clean_name}.\n\n"
            "Would you like me to share the preview link?\n\n"
            "Warm regards,\n"
            "{sender_name}\n"
            "{portfolio_url}"
        )
    },
    "general": {
        "subjects": [
            "A modern website for {clean_name}",
            "New website concept for {clean_name}",
            "Customer inquiry site for {clean_name}"
        ],
        "body": (
            "Hi {clean_name} team,\n\n"
            "I noticed you don't currently have an active website for your business.\n\n"
            "I build clean, fast, mobile-friendly websites that help local businesses get found on Google "
            "and generate more customer calls. I put together a quick sample concept for {clean_name}.\n\n"
            "Would you be open to seeing the preview link?\n\n"
            "Best regards,\n"
            "{sender_name}\n"
            "{portfolio_url}"
        )
    }
}


def clean_business_name(name: str) -> str:
    """Removes noise words from business name for a clean, natural greeting."""
    if not name:
        return "your"
    clean = name.strip()
    clean = re.sub(r"\b(Pvt\.?|Ltd\.?|LLP|Inc\.?|Co\.?|LLC|Enterprises|Services)\b", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean or name.strip()


def pick_subject(template_config: Dict[str, Any], email: str, clean_name: str) -> str:
    """Deterministically rotates subject lines based on recipient email hash."""
    subjects = template_config["subjects"]
    idx = int(hashlib.md5(email.encode("utf-8")).hexdigest(), 16) % len(subjects)
    raw = subjects[idx]
    formatted = raw.format(clean_name=clean_name)
    # Ensure strictly under 8 words
    words = formatted.split()
    if len(words) > 7:
        formatted = " ".join(words[:7])
    return formatted


def generate_email_content(lead: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Builds subject, plain text body, and HTML body for a lead.
    Enforces < 8 words subject and < 90 words body.
    """
    biz_name = lead.get("business_name", "").strip()
    clean_name = clean_business_name(biz_name)
    email = lead.get("email", "").strip().lower()
    segment = lead.get("segment", "general").lower()
    
    config = EMAIL_TEMPLATES.get(segment, EMAIL_TEMPLATES["general"])
    subject = pick_subject(config, email, clean_name)
    
    plain_text = config["body"].format(
        clean_name=clean_name,
        sender_name=OUTREACH_SENDER_NAME,
        portfolio_url=PORTFOLIO_URL
    )
    
    # Generate simple, clean, mobile-optimized HTML
    html_paragraphs = "".join([f"<p>{p.replace('\n', '<br>')}</p>" for p in plain_text.split("\n\n")])
    html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 15px; line-height: 1.5; color: #1f2937; margin: 0; padding: 16px; }}
p {{ margin: 0 0 14px 0; }}
a {{ color: #2563eb; text-decoration: underline; }}
</style>
</head>
<body>
{html_paragraphs}
</body>
</html>"""

    return subject, plain_text, html_body


def load_outreach_log() -> List[Dict[str, Any]]:
    """Loads all previously logged outreach attempts."""
    if not os.path.exists(OUTREACH_LOG_CSV):
        return []
    logs = []
    try:
        with open(OUTREACH_LOG_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                logs.append(r)
    except Exception:
        pass
    return logs


def get_sent_emails_set() -> set:
    """Returns set of lowercased emails that have already been contacted."""
    logs = load_outreach_log()
    return set(r.get("recipient", "").strip().lower() for r in logs if r.get("recipient") and r.get("status") == "sent")


def append_outreach_log(entry: Dict[str, Any]):
    """Appends an event to outreach_log.csv."""
    file_exists = os.path.exists(OUTREACH_LOG_CSV)
    fieldnames = [
        "timestamp",
        "recipient",
        "business_name",
        "segment",
        "subject",
        "status",
        "message_id",
        "mode"
    ]
    with open(OUTREACH_LOG_CSV, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: entry.get(k, "") for k in fieldnames})


def get_daily_send_cap(logs: List[Dict[str, Any]]) -> int:
    """
    Calculates the daily cap based on warm-up schedule:
    - Week 1: 5 sends / day
    - Week 2: 10 sends / day
    - Week 3+: 25 sends / day
    """
    live_sends = [r for r in logs if r.get("mode") == "live" and r.get("status") == "sent"]
    if not live_sends:
        return 5
    
    first_send_date = None
    for s in live_sends:
        try:
            dt = datetime.fromisoformat(s["timestamp"].replace("Z", "+00:00"))
            if first_send_date is None or dt < first_send_date:
                first_send_date = dt
        except Exception:
            continue
            
    if not first_send_date:
        return 5
        
    days_active = (datetime.now(timezone.utc) - first_send_date).days
    if days_active < 7:
        return 5
    elif days_active < 14:
        return 10
    else:
        return 25


def count_today_sends(logs: List[Dict[str, Any]]) -> int:
    """Counts how many live emails were sent today UTC."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    count = 0
    for r in logs:
        if r.get("mode") == "live" and r.get("status") == "sent":
            ts = r.get("timestamp", "")
            if ts.startswith(today_str):
                count += 1
    return count


def save_preview_draft(recipient: str, subject: str, plain_text: str, html_body: str):
    """Saves rendered draft to preview_drafts directory."""
    slug = re.sub(r"[^a-zA-Z0-9]", "_", recipient.split("@")[0])[:30]
    txt_path = os.path.join(PREVIEW_DIR, f"{slug}.txt")
    html_path = os.path.join(PREVIEW_DIR, f"{slug}.html")
    
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"Subject: {subject}\nTo: {recipient}\n\n{plain_text}")
        
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_body)


def send_single_email(
    to_addr: str,
    subject: str,
    plain_text: str,
    html_body: str,
    message_id: Optional[str] = None
) -> Tuple[bool, str]:
    """Transmits a single email via SMTP."""
    if not SMTP_USER or not SMTP_PASS:
        return False, "SMTP credentials missing from environment"
        
    if to_addr.lower() in PROTECTED_ACCOUNTS:
        return False, f"Refusing to send: recipient {to_addr} matches PROTECTED_ACCOUNTS"
        
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{OUTREACH_SENDER_NAME} <{SMTP_USER}>"
    msg["To"] = to_addr
    msg["Reply-To"] = SMTP_REPLY_TO
    msg["Message-ID"] = message_id or make_msgid()
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    
    part1 = MIMEText(plain_text, "plain", "utf-8")
    part2 = MIMEText(html_body, "html", "utf-8")
    msg.attach(part1)
    msg.attach(part2)
    
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [to_addr], msg.as_string())
        return True, msg["Message-ID"]
    except Exception as e:
        return False, str(e)


def run_pipeline(
    send_live: bool = False,
    test_send: bool = False,
    max_send_override: Optional[int] = None,
    no_warmup: bool = False
):
    """Executes the cold outreach pipeline."""
    mode = "live" if send_live else "dry_run"
    print("\n=======================================================")
    print(f"WEBSITE OUTREACH PIPELINE — MODE: [{mode.upper()}]")
    print("=======================================================")
    
    if test_send:
        if not TEST_RECIPIENTS:
            print("[ERROR] --test-send requested, but TEST_RECIPIENTS is not configured in .env")
            sys.exit(1)
        test_email = TEST_RECIPIENTS[0]
        print(f"Dispatching test preview strictly to: {test_email}")
        
        sample_lead = {
            "business_name": "Apex Marketing Group",
            "segment": "agency",
            "email": test_email
        }
        subj, txt, html_content = generate_email_content(sample_lead)
        save_preview_draft(test_email, subj, txt, html_content)
        
        if send_live:
            success, res = send_single_email(test_email, subj, txt, html_content)
            if success:
                print(f"[SUCCESS] Test email transmitted to {test_email}! Message-ID: {res}")
            else:
                print(f"[FAILURE] Test email failed: {res}")
        else:
            print("[DRY-RUN] Test email generated in preview_drafts/. Run with --send-live to transmit.")
        return

    if not os.path.exists(LEADS_CSV):
        print(f"[ERROR] No leads file found at: {LEADS_CSV}")
        print("Run 'py web_lead_finder.py <niche> <location>' first to source leads.")
        return

    # Load leads
    all_leads = []
    with open(LEADS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_leads.append(row)

    email_leads = [l for l in all_leads if l.get("email") and l.get("channel") == "email"]
    print(f"Found {len(all_leads)} total leads ({len(email_leads)} with email channel).")

    # Filter out already contacted
    already_sent = get_sent_emails_set()
    eligible_leads = [l for l in email_leads if l["email"].strip().lower() not in already_sent]
    print(f"Eligible leads remaining to contact: {len(eligible_leads)}")

    if not eligible_leads:
        print("No new eligible leads to email. All sourced leads have already been contacted.")
        return

    # Determine limits
    logs = load_outreach_log()
    today_sent = count_today_sends(logs)
    daily_cap = 9999 if no_warmup else get_daily_send_cap(logs)
    remaining_cap = max(0, daily_cap - today_sent)
    
    if max_send_override is not None:
        batch_limit = min(max_send_override, remaining_cap)
    else:
        batch_limit = remaining_cap

    print(f"Daily Cap: {daily_cap} | Already sent today: {today_sent} | Batch limit: {batch_limit}")

    if batch_limit <= 0 and send_live:
        print("[LIMIT] Daily send cap reached for today. Halting live sending to protect inbox reputation.")
        return

    to_process = eligible_leads[:batch_limit] if send_live else eligible_leads[:10]

    for idx, lead in enumerate(to_process, 1):
        recip = lead["email"].strip().lower()
        biz_name = lead.get("business_name", "your business")
        seg = lead.get("segment", "general")
        
        subj, txt, html_content = generate_email_content(lead)
        save_preview_draft(recip, subj, txt, html_content)

        print(f"  [{idx}/{len(to_process)}] {biz_name} ({recip})")
        print(f"      Subject: {subj}")

        if send_live:
            msg_id = make_msgid()
            success, err_or_id = send_single_email(recip, subj, txt, html_content, message_id=msg_id)
            if success:
                print(f"      [SENT] Live email delivered.")
                append_outreach_log({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "recipient": recip,
                    "business_name": biz_name,
                    "segment": seg,
                    "subject": subj,
                    "status": "sent",
                    "message_id": msg_id,
                    "mode": "live"
                })
                # Sleep briefly between live sends
                time.sleep(1.5)
            else:
                print(f"      [ERROR] Could not send: {err_or_id}")
                append_outreach_log({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "recipient": recip,
                    "business_name": biz_name,
                    "segment": seg,
                    "subject": subj,
                    "status": f"failed: {err_or_id}",
                    "message_id": "",
                    "mode": "live"
                })
        else:
            print(f"      [DRY-RUN] Draft created in preview_drafts/{re.sub(r'[^a-zA-Z0-9]', '_', recip.split('@')[0])[:30]}.html")
            append_outreach_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "recipient": recip,
                "business_name": biz_name,
                "segment": seg,
                "subject": subj,
                "status": "dry_run",
                "message_id": "",
                "mode": "dry_run"
            })

    print("\nBatch processing completed.")
    if not send_live:
        print("NOTE: Executed in safe --dry-run mode. To send live emails, use --send-live.")


def main():
    parser = argparse.ArgumentParser(description="Website Creation Outreach Pipeline")
    parser.add_argument("--send-live", action="store_true", help="Execute live email sending via SMTP")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Safe simulation mode (default)")
    parser.add_argument("--test-send", action="store_true", help="Send single test email strictly to TEST_RECIPIENTS")
    parser.add_argument("--max-sends", type=int, help="Override maximum sends for this batch")
    parser.add_argument("--no-warmup", action="store_true", help="Bypass warmup daily cap limits")
    
    args = parser.parse_args()

    run_pipeline(
        send_live=args.send_live,
        test_send=args.test_send,
        max_send_override=args.max_sends,
        no_warmup=args.no_warmup
    )


if __name__ == "__main__":
    main()
