"""
test_no_emoji.py — Verifies that no emoji characters exist in app.py, ui.py, places.py, or UI strings.

Allows standard typographic characters like em dashes (—), en dashes (–), middle dots (·),
bullets (•), and arrows (→).
"""

import os
import re

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

EMOJI_PATTERN = re.compile(
    r"["
    r"\U0001F1E0-\U0001F1FF"  # Flags
    r"\U0001F300-\U0001F5FF"  # Symbols & Pictographs
    r"\U0001F600-\U0001F64F"  # Emoticons
    r"\U0001F680-\U0001F6FF"  # Transport & Map
    r"\U0001F700-\U0001F77F"  # Alchemical
    r"\U0001F780-\U0001F7FF"  # Geometric
    r"\U0001F800-\U0001F8FF"  # Arrows Supplement
    r"\U0001F900-\U0001F9FF"  # Supplemental Symbols
    r"\U0001FA00-\U0001FA6F"  # Chess Symbols
    r"\U0001FA70-\U0001FAFF"  # Symbols Extended-A
    r"\u2600-\u26FF"          # Miscellaneous Symbols (⚠️, ⚙️, ☕, etc.)
    r"\u2700-\u27BF"          # Dingbats (✅, ✉️, etc.)
    r"]+",
    flags=re.UNICODE
)


def test_no_emoji_in_source_files():
    """Verify zero emoji characters in app.py, ui.py, and places.py."""
    files_to_check = ["app.py", "ui.py", "places.py"]
    violations = {}

    for fname in files_to_check:
        fpath = os.path.join(BASE_DIR, fname)
        assert os.path.exists(fpath), f"File {fpath} does not exist"
        with open(fpath, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                matches = EMOJI_PATTERN.findall(line)
                if matches:
                    violations.setdefault(fname, []).append((line_no, matches, line.strip()))

    assert not violations, f"Forbidden emoji characters found in source code: {violations}"


def test_typography_characters_allowed():
    """Confirms that typographic punctuation (em dash, en dash, middle dot, arrows) is not flagged."""
    sample_text = "LocalLeads Kit — B2B Engine · Search → Results • Filter – All"
    assert not EMOJI_PATTERN.search(sample_text), "Typographic characters must not be flagged as emoji!"
