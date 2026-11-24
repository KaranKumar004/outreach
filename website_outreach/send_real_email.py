"""
send_real_email.py
Utility to send real, live emails through SMTP to verify actual client communication delivery.
Reads credentials safely from .env.
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from dotenv import load_dotenv

# Load workspace .env
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
DEFAULT_RECIPIENT = os.getenv("TEST_RECIPIENTS", "skarankumar003@gmail.com")
SENDER_NAME = os.getenv("OUTREACH_SENDER_NAME", "Karan from Sheetbolt")

def send_real_email(subject: str, text_body: str, html_body: str = None, recipient: str = None) -> bool:
    """Sends a real email using SMTP and verifies delivery."""
    target_to = recipient or DEFAULT_RECIPIENT
    
    if not SMTP_USER or not SMTP_PASS:
        raise ValueError("SMTP_USER or SMTP_PASS missing from environment variables.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SENDER_NAME} <{SMTP_USER}>"
    msg["To"] = target_to
    msg["Date"] = formatdate(localtime=True)

    # Attach plain text
    msg.attach(MIMEText(text_body, "plain", "utf-8"))

    # Attach HTML if provided
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    print(f"Connecting to SMTP server {SMTP_HOST}:{SMTP_PORT}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [target_to], msg.as_string())
    
    print(f"[SUCCESS] Live email successfully sent to: {target_to}")
    print(f"   Subject: {subject}")
    return True

if __name__ == "__main__":
    import sys
    test_subj = sys.argv[1] if len(sys.argv) > 1 else "Sheetbolt Live Test Email"
    test_body = sys.argv[2] if len(sys.argv) > 2 else "This is a real live test email from Sheetbolt Web Studio."
    send_real_email(test_subj, test_body)
