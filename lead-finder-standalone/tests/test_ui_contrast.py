"""
test_ui_contrast.py — Automated WCAG 2.1 contrast ratio verification for design tokens.

Verifies:
- Text tokens vs surfaces achieve >= 4.5:1 AA contrast ratio
- Border-strong token (#56668F) achieves >= 3.0:1 non-text contrast ratio against surface, input fill, and bg
"""

def srgb_to_lin(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    hex_clean = hex_color.lstrip("#")
    r, g, b = [int(hex_clean[i:i+2], 16) for i in (0, 2, 4)]
    return 0.2126 * srgb_to_lin(r) + 0.7152 * srgb_to_lin(g) + 0.0722 * srgb_to_lin(b)


def contrast_ratio(color1: str, color2: str) -> float:
    l1 = relative_luminance(color1)
    l2 = relative_luminance(color2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_text_tokens_contrast():
    """Text tokens must meet or exceed WCAG AA 4.5:1 contrast against their backgrounds."""
    bg = "#0B1020"
    sidebar = "#0E1528"
    surface = "#121A2F"

    text = "#E8ECF7"
    text_2 = "#9AA6C4"
    text_3 = "#8B96B4"
    accent = "#6E8BFF"
    on_accent = "#0B1020"

    # Text vs background / surface
    assert contrast_ratio(text, bg) >= 4.5, "text vs bg must be >= 4.5:1"
    assert contrast_ratio(text, surface) >= 4.5, "text vs surface must be >= 4.5:1"

    # Secondary text vs surface
    assert contrast_ratio(text_2, surface) >= 4.5, "text-2 vs surface must be >= 4.5:1"

    # Captions / text-3 vs surface and sidebar
    assert contrast_ratio(text_3, surface) >= 4.5, "text-3 vs surface must be >= 4.5:1"
    assert contrast_ratio(text_3, sidebar) >= 4.5, "text-3 vs sidebar must be >= 4.5:1"

    # Primary button on-accent vs accent
    assert contrast_ratio(on_accent, accent) >= 4.5, "on-accent vs accent must be >= 4.5:1"


def test_status_tokens_contrast():
    """Status colors must meet WCAG AA contrast (>= 4.5:1) against card surface and table background."""
    import sys
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    import ui

    surface = "#121A2F"
    table_bg = "#0B1020"
    input_fill = "#0E1528"

    for name, hex_val in ui.STATUS_COLORS.items():
        ratio_surface = contrast_ratio(hex_val, surface)
        assert ratio_surface >= 4.5, f"Status {name} ({hex_val}) vs surface must be >= 4.5:1, got {ratio_surface:.2f}:1"

        ratio_table = contrast_ratio(hex_val, table_bg)
        assert ratio_table >= 4.5, f"Status {name} ({hex_val}) vs table_bg must be >= 4.5:1, got {ratio_table:.2f}:1"

        ratio_input = contrast_ratio(hex_val, input_fill)
        assert ratio_input >= 4.5, f"Status {name} ({hex_val}) vs input_fill must be >= 4.5:1, got {ratio_input:.2f}:1"


def test_border_strong_non_text_contrast():
    """
    --border-strong (#56668F) must achieve >= 3.0:1 non-text contrast
    against surface (#121A2F), input fill (#0E1528), and bg (#0B1020).
    """
    border_strong = "#56668F"
    surface = "#121A2F"
    input_fill = "#0E1528"
    bg = "#0B1020"

    ratio_surface = contrast_ratio(border_strong, surface)
    ratio_input = contrast_ratio(border_strong, input_fill)
    ratio_bg = contrast_ratio(border_strong, bg)

    assert ratio_surface >= 3.0, f"border-strong vs surface must be >= 3.0:1, got {ratio_surface:.2f}:1"
    assert ratio_input >= 3.0, f"border-strong vs input fill must be >= 3.0:1, got {ratio_input:.2f}:1"
    assert ratio_bg >= 3.0, f"border-strong vs bg must be >= 3.0:1, got {ratio_bg:.2f}:1"
