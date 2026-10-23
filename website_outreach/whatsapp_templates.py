"""
whatsapp_templates.py — Pitch scripts and Click-to-Chat WhatsApp generator
for businesses without websites.
"""

import os
import re
import csv
import urllib.parse
from typing import Dict, Any, List, Optional
try:
    import phonenumbers
    from phonenumbers import PhoneNumberType, number_type
    PHONENUMBERS_AVAILABLE = True
except ImportError:
    PHONENUMBERS_AVAILABLE = False


WHATSAPP_PITCHES: Dict[str, str] = {
    "agency": (
        "Hi! Came across {clean_name}{area_str} and noticed you guys don't have an active website "
        "for your portfolio yet. I put together a quick 1-page agency layout for you—open to checking out the preview link?"
    ),
    "clinic": (
        "Hi! Came across {clean_name} on Google Maps{area_str}. Noticed you don't have a website yet "
        "for patient timings & appointments. Put together a quick 1-page mobile layout for your clinic—can I share the link?"
    ),
    "dentist": (
        "Hi! Came across {clean_name} on Google Maps{area_str}. Noticed you don't have a website yet "
        "for patient bookings & consultation timings. Put together a quick 1-page mobile layout for your dental clinic—can I send the preview link?"
    ),
    "dentists": (
        "Hi! Came across {clean_name} on Google Maps{area_str}. Noticed you don't have a website yet "
        "for patient bookings & consultation timings. Put together a quick 1-page mobile layout for your dental clinic—can I send the preview link?"
    ),
    "gym": (
        "Hi! Came across {clean_name} on Google Maps{area_str}. Noticed you don't have a website yet "
        "for membership plans & schedules. Put together a quick mobile layout for your gym—can I send the link?"
    ),
    "salon": (
        "Hi! Came across {clean_name} on Google Maps{area_str}. Noticed you guys don't have a website yet "
        "for your service menu & bookings. Made a quick 1-page mobile layout for you—would you like to see the preview link?"
    ),
    "restaurant": (
        "Hi! Came across {clean_name} on Google Maps{area_str}. Noticed you don't have a website yet "
        "for your menu & inquiries. Put together a quick mobile layout for you—can I send the preview link?"
    ),
    "accounting": (
        "Hi! Came across {clean_name}{area_str} and noticed you don't have a dedicated website yet "
        "for your advisory & tax services. Put together a quick 1-page layout for your firm—can I send the preview link?"
    ),
    "retail": (
        "Hi! Came across {clean_name} on Google Maps{area_str}. Noticed you don't have a website yet "
        "for your catalog & customer inquiries. Put together a quick 1-page mobile layout for you—can I send the link?"
    ),
    "general": (
        "Hi! Came across {clean_name} on Google Maps{area_str}. Noticed you don't have an active website yet "
        "for customer inquiries. Put together a quick 1-page mobile layout for you—can I send over the link?"
    ),
}


def clean_business_name_for_msg(name: str) -> str:
    """Extracts a friendly business name without legal suffixes or noisy terms."""
    if not name:
        return "your team"
    clean = name.strip()
    clean = re.sub(r"\b(Pvt\.?|Ltd\.?|LLP|Inc\.?|Co\.?|LLC|Enterprises|Services)\b", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean or name.strip()


def normalize_phone_number(raw_phone: str, default_country: str = "IN") -> str:
    """
    Normalizes a phone number to standard international format (digits only, e.g. '919876543210' or '15125550123').
    Handles Indian numbers, US/international, and strips extraneous punctuation.
    If multiple numbers are provided separated by semicolons, slashes, or commas, takes the first valid phone.
    """
    if not raw_phone:
        return ""
    # Extract first number if multiple are chained together
    first_part = re.split(r"[;,/|]", str(raw_phone))[0].strip()
    digits = re.sub(r"\D", "", first_part)
    if not digits:
        return ""

    country = default_country.strip().upper()
    if country == "IN":
        # If 10 digits, prepend 91
        if len(digits) == 10:
            return "91" + digits
        # If 11 digits starting with 0, replace leading 0 with 91
        if len(digits) == 11 and digits.startswith("0"):
            return "91" + digits[1:]
        # If already starts with 91 and length is 12
        if len(digits) == 12 and digits.startswith("91"):
            return digits
        # If 13 digits starting with 091
        if len(digits) == 13 and digits.startswith("091"):
            return digits[1:]
        return digits

    elif country == "US":
        if len(digits) == 10:
            return "1" + digits
        if len(digits) == 11 and digits.startswith("1"):
            return digits
        return digits

    return digits


def get_whatsapp_message(business_name: str, segment: str = "general", area: str = "") -> str:
    """Returns a personalized WhatsApp outreach message tailored to the business and segment."""
    clean_name = clean_business_name_for_msg(business_name)
    area_clean = area.split(",")[0].strip() if area else ""
    area_str = f" in {area_clean}" if area_clean else ""
    template = WHATSAPP_PITCHES.get(segment.lower(), WHATSAPP_PITCHES["general"])
    return template.format(business_name=business_name, clean_name=clean_name, area_str=area_str)


def generate_wa_link(phone: str, message: str, default_country: str = "IN") -> str:
    """Generates a direct Click-to-Chat WhatsApp URL: https://wa.me/<number>?text=<url_encoded_message>"""
    normalized_digits = normalize_phone_number(phone, default_country=default_country)
    if not normalized_digits:
        return ""
    encoded_text = urllib.parse.quote(message)
    return f"https://wa.me/{normalized_digits}?text={encoded_text}"


def is_mobile_number(raw_phone: str, default_country: str = "IN") -> bool:
    """
    Checks if a phone number is a verified mobile number capable of receiving WhatsApp.
    Filters out landlines / fixed-line numbers (such as 080 STD in Bengaluru).
    """
    if not raw_phone:
        return False
    first_part = re.split(r"[;,/|]", str(raw_phone))[0].strip()
    
    country_clean = default_country.strip().upper()
    if PHONENUMBERS_AVAILABLE:
        try:
            parsed = phonenumbers.parse(first_part, country_clean)
            if not phonenumbers.is_valid_number(parsed):
                return False
            ntype = number_type(parsed)
            # In India, only MOBILE numbers can have WhatsApp.
            if country_clean == "IN":
                return ntype == PhoneNumberType.MOBILE
            return ntype in (PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE_OR_MOBILE)
        except Exception:
            pass

    # Regex fallback if phonenumbers fails or is not available
    digits = re.sub(r"\D", "", first_part)
    if country_clean == "IN":
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        elif digits.startswith("0") and len(digits) == 11:
            digits = digits[1:]
        # Indian mobile numbers are 10 digits starting with 6, 7, 8, 9
        # (Exclude landline prefixes like 80 for Bengaluru, 22 for Mumbai, etc.)
        if len(digits) == 10:
            if digits.startswith("80"):  # Bengaluru landline without 0 prefix
                return False
            return digits[0] in "6789"
        return False

    return len(digits) >= 10


def export_whatsapp_leads(leads: List[Dict[str, Any]], output_filepath: str, default_country: str = "IN") -> int:
    """
    Exports leads with mobile numbers to a dedicated CSV file for WhatsApp outreach.
    Filters out landlines so users don't encounter 'number not on WhatsApp' errors.
    Also saves landlines to leads_landline_calling.csv for optional phone calls.
    """
    fieldnames = [
        "business_name",
        "phone",
        "normalized_phone",
        "segment",
        "area",
        "whatsapp_link",
        "pitch_message",
        "status"
    ]
    landline_fieldnames = [
        "business_name",
        "phone",
        "normalized_phone",
        "segment",
        "area",
        "notes"
    ]
    
    count = 0
    landline_rows = []
    seen_phones = set()
    
    with open(output_filepath, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for lead in leads:
            raw_phone = lead.get("phone", "").strip()
            if not raw_phone:
                continue
            norm_phone = normalize_phone_number(raw_phone, default_country=default_country)
            if not norm_phone or norm_phone in seen_phones:
                continue
            seen_phones.add(norm_phone)
                
            seg = lead.get("segment", "general")
            biz_name = lead.get("business_name", "").strip()
            area = lead.get("area", "")
            
            # Check if this is a real mobile number
            if not is_mobile_number(raw_phone, default_country=default_country):
                landline_rows.append({
                    "business_name": biz_name,
                    "phone": raw_phone,
                    "normalized_phone": norm_phone,
                    "segment": seg,
                    "area": area,
                    "notes": "Landline / Fixed-line phone (Not on WhatsApp)"
                })
                continue
                
            msg = get_whatsapp_message(biz_name, seg, area=area)
            wa_link = generate_wa_link(norm_phone, msg, default_country=default_country)
            
            writer.writerow({
                "business_name": biz_name,
                "phone": raw_phone,
                "normalized_phone": norm_phone,
                "segment": seg,
                "area": area,
                "whatsapp_link": wa_link,
                "pitch_message": msg,
                "status": "new"
            })
            count += 1

    # If any landlines were found, export them separately
    if landline_rows:
        dir_name = os.path.dirname(output_filepath)
        landline_path = os.path.join(dir_name, "leads_landline_calling.csv")
        with open(landline_path, "w", encoding="utf-8", newline="") as lf:
            l_writer = csv.DictWriter(lf, fieldnames=landline_fieldnames)
            l_writer.writeheader()
            for row in landline_rows:
                l_writer.writerow(row)

    return count
