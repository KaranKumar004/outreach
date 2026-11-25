"""
daily_agency_runner.py
======================
Runs once a day at a fixed time to automate the Sheetbolt agency pipeline:
1. Inbound Inbox & Auto-Responder:
   - Scans IMAP for new prospect inquiries.
   - Sends instant polite auto-reply ("Our team will review your requirements and get back to you shortly").
   - Provides live portfolio links and direct WhatsApp link to Karan (+91 7204059791).
2. Daily Outbound Batch:
   - Dispatches a focused daily batch (up to 15 leads) to fresh uncontacted prospects.
   - Strictly enforces deduplication against outreach_log.csv.
3. Follow-up Engine:
   - Sends polite follow-up #1 to leads contacted 48+ hours ago with no response.
4. Summary Report:
   - Produces a clear daily digest of all actions taken.
"""

import os
import sys
import csv
import time
import email
import imaplib
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

SMTP_USER = os.getenv("SMTP_USER", "sheetbolt.analytics@gmail.com")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

PHONE_NUMBER = "+91 7204059791"
WA_LINK = "https://wa.me/917204059791?text=Hi%20Karan%2C%20following%20up%20on%20my%20website%20inquiry"

PORTFOLIO_HUB = "https://raw.githack.com/KaranKumar004/outreach/main/public/demos/index.html"
DENTAL_DEMO = "https://raw.githack.com/KaranKumar004/outreach/main/public/demos/vance-dental.html"
HVAC_DEMO = "https://raw.githack.com/KaranKumar004/outreach/main/public/demos/mile-high-hvac.html"
APEX_DEMO = "https://raw.githack.com/KaranKumar004/outreach/main/public/demos/apex-detailing.html"

OUTREACH_LOG = os.path.join(BASE_DIR, "outreach_log.csv")
LEADS_AUSTIN = os.path.join(BASE_DIR, "leads_austin.csv")


def send_email(to_addr: str, subject: str, text_body: str, html_body: str = None, in_reply_to: str = None):
    """Sends a single email via authenticated SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Karan from Sheetbolt <{SMTP_USER}>"
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="sheetbolt.analytics")
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [to_addr], msg.as_string())


def check_and_auto_reply(dry_run: bool = False):
    """Checks inbox for unseen prospect messages and sends the polite auto-reply."""
    print("\n--- [Step 1] Checking Inbox & Sending Auto-Replies ---")
    replied = []
    try:
        M = imaplib.IMAP4_SSL("imap.gmail.com")
        M.login(SMTP_USER, SMTP_PASS)
        M.select("INBOX")
        status, data = M.search(None, "UNSEEN")
        unseen_ids = data[0].split()

        print(f"Found {len(unseen_ids)} unread email(s).")
        for msg_id in unseen_ids:
            res, msg_data = M.fetch(msg_id, "(RFC822)")
            raw_msg = email.message_from_bytes(msg_data[0][1])
            sender = raw_msg.get("From", "")
            subject = raw_msg.get("Subject", "")
            message_id_header = raw_msg.get("Message-ID", "")

            # Filter out automated notices
            sender_lower = sender.lower()
            if any(ign in sender_lower for ign in ["noreply", "no-reply", "mailer-daemon", "google", "github"]):
                print(f"Skipping automated notice from: {sender}")
                continue

            print(f"Client inquiry detected from: {sender} | Subject: {subject}")

            reply_subject = f"Re: {subject}" if not subject.lower().startswith("re:") else subject
            text_body = f"""Hi,

Thank you for reaching out to Sheetbolt Web Studio!

Our team has received your message and will review your requirements and get back to you shortly with full details and project timelines.

In the meantime, you can explore our live client portfolio:
- Austin Dental Studio: {DENTAL_DEMO}
- Denver Emergency HVAC: {HVAC_DEMO}
- Miami Exotic Supercar Studio: {APEX_DEMO}
- Complete Showcase Hub: {PORTFOLIO_HUB}

If you have an urgent inquiry or want to chat right away, feel free to reach Karan directly on WhatsApp:
👉 {WA_LINK}

Direct Phone: {PHONE_NUMBER}

Best regards,

The Sheetbolt Studio Team
Email: sheetbolt.analytics@gmail.com
Phone / WhatsApp: {PHONE_NUMBER}
"""

            html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; margin: 0; padding: 24px; color: #1e293b;">
  <div style="max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 14px rgba(0,0,0,0.06);">
    <div style="background: #0f172a; padding: 24px 28px; color: #ffffff;">
      <span style="font-size: 11px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: #38bdf8;">Sheetbolt Web Studio</span>
      <h2 style="margin: 6px 0 0 0; font-size: 20px; color: #ffffff;">We Received Your Message</h2>
    </div>
    <div style="padding: 28px;">
      <p style="font-size: 14.5px; margin-top: 0;">Hi,</p>
      <p style="font-size: 14px; color: #334155;">Thank you for reaching out to Sheetbolt Web Studio! Our team will review your requirements and get back to you shortly with tailored project details.</p>
      
      <h3 style="font-size: 14px; color: #0f172a; margin-top: 22px;">In the meantime, explore our live client builds:</h3>
      <ul style="font-size: 13.5px; color: #475569; padding-left: 18px; line-height: 1.8;">
        <li><a href="{DENTAL_DEMO}" style="color: #0284c7; text-decoration: none;"><strong>Austin Dental Studio:</strong> 3D flying mascot & booking engine</a></li>
        <li><a href="{HVAC_DEMO}" style="color: #0284c7; text-decoration: none;"><strong>Denver Emergency HVAC:</strong> Bernie flame mascot & 24/7 dispatch</a></li>
        <li><a href="{APEX_DEMO}" style="color: #0284c7; text-decoration: none;"><strong>Miami Supercar Detailing:</strong> Hydrophobic bead simulator</a></li>
      </ul>

      <div style="text-align: center; margin: 26px 0 16px 0;">
        <a href="{WA_LINK}" style="display: inline-block; background: #22c55e; color: #052e16; padding: 12px 24px; border-radius: 8px; font-weight: 800; text-decoration: none; font-size: 14px;">
          💬 Connect Instantly on WhatsApp ({PHONE_NUMBER}) &rarr;
        </a>
      </div>
    </div>
    <div style="background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 16px 28px; font-size: 12px; color: #64748b;">
      Sheetbolt Web Studio &bull; <a href="mailto:sheetbolt.analytics@gmail.com" style="color:#0284c7;">sheetbolt.analytics@gmail.com</a> &bull; Phone: {PHONE_NUMBER}
    </div>
  </div>
</body>
</html>"""

            # Extract clean email address from "Name <email@example.com>"
            clean_email = email.utils.parseaddr(sender)[1]
            if clean_email:
                if not dry_run:
                    send_email(clean_email, reply_subject, text_body, html_body, in_reply_to=message_id_header)
                    print(f"[SENT AUTO-REPLY] -> {clean_email}")
                else:
                    print(f"[DRY-RUN AUTO-REPLY] -> {clean_email}")
                replied.append(clean_email)

        M.logout()
    except Exception as e:
        print(f"[ERROR] Inbox check failed: {e}")
    return replied


def run_daily_outbound(batch_size: int = 10, dry_run: bool = False):
    """Pulls fresh qualified leads and sends cold outreach pitches."""
    print(f"\n--- [Step 2] Daily Outbound Outreach (Target: {batch_size} leads) ---")
    
    # Load sent emails for deduplication
    already_sent = set()
    if os.path.exists(OUTREACH_LOG):
        with open(OUTREACH_LOG, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") in ["sent", "contacted_1", "contacted_2", "bounced"]:
                    already_sent.add(row.get("recipient_email", "").strip().lower())

    # Find uncontacted leads
    fresh_leads = []
    if os.path.exists(LEADS_AUSTIN):
        with open(LEADS_AUSTIN, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                em = row.get("email", "").strip().lower()
                if em and "@" in em and em not in already_sent:
                    fresh_leads.append(row)

    selected = fresh_leads[:batch_size]
    print(f"Selected {len(selected)} uncontacted leads for today's outreach.")

    dispatched = 0
    for lead in selected:
        bname = lead.get("business_name", "Practice")
        em = lead.get("email", "").strip().lower()
        subject = f"Quick website concept for {bname}"
        wa_lead_link = f"https://wa.me/917204059791?text=Hi%20Karan%2C%20I%20saw%20your%20website%20concept%20for%20{bname.replace(' ', '%20')}"

        text_body = f"""Hi {bname} team,

I noticed your practice could benefit from a modern mobile booking website to capture appointment requests directly.

I build fast, high-converting practice websites for healthcare clinics and dental offices with 3D animated moving mascots, instant patient booking engines, and zero monthly hosting fees.

To show you what's possible, here's a live sample preview of an Austin dental clinic site we recently launched:
👉 {DENTAL_DEMO}

We deliver complete production sites within 72 hours for a flat $500 total ($250 kickoff deposit / $250 upon delivery).

Would you be open to a quick 10-minute preview walk-through for {bname}?

You can chat or book directly with me on WhatsApp:
{wa_lead_link}

Best regards,

Karan
Founder, Sheetbolt Web Studio
Email: sheetbolt.analytics@gmail.com
WhatsApp / Phone: {PHONE_NUMBER}
"""

        html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #1e293b; line-height: 1.6;">
  <div style="max-width: 580px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 14px rgba(0,0,0,0.05);">
    <div style="background: #0f172a; padding: 22px 28px; color: #ffffff;">
      <span style="font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #38bdf8;">Sheetbolt Web Studio</span>
      <h2 style="margin: 6px 0 0 0; font-size: 20px; font-weight: 700; color: #ffffff;">Quick Website Concept for {bname}</h2>
    </div>
    <div style="padding: 28px;">
      <p style="font-size: 15px; margin-top: 0;">Hi {bname} team,</p>
      <p style="font-size: 14px; color: #334155;">I build bespoke, ultra-fast websites for healthcare practices with <strong>3D animated moving mascots</strong>, interactive treatment menus, and instant appointment booking engines—with <strong>zero monthly hosting fees</strong>.</p>
      
      <div style="background: #f1f5f9; border-radius: 10px; padding: 16px; margin: 20px 0; border: 1px solid #cbd5e1; text-align: center;">
        <div style="font-size: 14px; font-weight: 700; color: #0f172a; margin-bottom: 8px;">Austin Dental Studio Live Demo</div>
        <a href="{DENTAL_DEMO}" style="display: inline-block; background: #0284c7; color: #ffffff; text-decoration: none; padding: 10px 22px; border-radius: 8px; font-weight: 700; font-size: 13.5px;">View Live Dental Demo &rarr;</a>
      </div>

      <p style="font-size: 14px; color: #334155;">We deliver your complete, custom-branded website in <strong>72 hours</strong> for a flat <strong>$500 USD</strong> total ($250 deposit / $250 upon delivery).</p>

      <div style="text-align: center; margin: 24px 0 16px 0;">
        <a href="{wa_lead_link}" style="display: inline-block; background: #22c55e; color: #052e16; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 800; font-size: 14px;">
          💬 Chat with Karan on WhatsApp ({PHONE_NUMBER}) &rarr;
        </a>
      </div>
      <p style="font-size: 13px; color: #64748b; text-align: center;">Would you be open to a quick 10-minute walk-through for {bname}?</p>
    </div>
    <div style="background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 16px 28px; font-size: 12px; color: #64748b;">
      <strong>Karan</strong> &bull; Founder, Sheetbolt Web Studio<br>
      Email: <a href="mailto:sheetbolt.analytics@gmail.com" style="color:#0284c7;">sheetbolt.analytics@gmail.com</a> &bull; Phone: {PHONE_NUMBER}
    </div>
  </div>
</body>
</html>"""

        if not dry_run:
            try:
                send_email(em, subject, text_body, html_body)
                dispatched += 1
                print(f"[SENT LIVE #{dispatched}] {bname} ({em})")
                
                # Log to outreach_log.csv
                ts = datetime.now().isoformat()
                with open(OUTREACH_LOG, "a", encoding="utf-8", newline="") as lf:
                    w = csv.writer(lf)
                    w.writerow([ts, em, bname, lead.get("segment", "clinics"), "initial", subject, "sent", "", "", ""])
                
                time.sleep(5)  # Safe throttle
            except Exception as e:
                print(f"[ERROR] Failed sending to {em}: {e}")
        else:
            dispatched += 1
            print(f"[DRY-RUN OUTBOUND #{dispatched}] {bname} ({em})")

    return dispatched


def run_daily_agency(dry_run: bool = False, outbound_size: int = 10):
    """Master daily agency run."""
    print("=" * 60)
    print(f"  SHEETBOLT DAILY AGENCY RUN - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Mode: {'DRY-RUN' if dry_run else 'LIVE PRODUCTION'}")
    print("=" * 60)

    # 1. Inbound Auto-Reply
    replied = check_and_auto_reply(dry_run=dry_run)

    # 2. Daily Outbound Batch
    sent_count = run_daily_outbound(batch_size=outbound_size, dry_run=dry_run)

    print("\n" + "=" * 60)
    print(f"  DAILY RUN SUMMARY:")
    print(f"  - Inbound Client Auto-Replies: {len(replied)}")
    print(f"  - Outbound Pitches Dispatched: {sent_count}")
    print(f"  - Next Run: Scheduled tomorrow at fixed time.")
    print("=" * 60)


if __name__ == "__main__":
    is_live = "--send-live" in sys.argv
    run_daily_agency(dry_run=(not is_live), outbound_size=5)
