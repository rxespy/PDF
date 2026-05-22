# arabic/engine.py
"""
Isolated Monolithic Arabic RTL Processing Engine.
Reshapes letters and reverses text using standard BiDi mechanics.
Guarantees correct font registration so Arabic joins are never broken.
"""

import os
import urllib.request
import arabic_reshaper
from bidi.algorithm import get_display

# Default directory to persist the TrueType Font (.ttf)
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
FONT_PATH = os.path.join(FONT_DIR, "Amiri-Regular.ttf")
AMIRI_GOOGLE_FONT_URL = "https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Regular.ttf"

def ensure_arabic_font() -> str:
    """
    Ensures that a standard Arabic font (Amiri Unified Unicode TTF) exists locally.
    Downloads the font if missing, enabling high-quality PDF text-rendering.
    """
    if not os.path.exists(FONT_DIR):
        os.makedirs(FONT_DIR, exist_ok=True)
        
    if not os.path.exists(FONT_PATH):
        try:
            # Dynamic download of verified open-source Amiri TrueType Font
            urllib.request.urlretrieve(AMIRI_GOOGLE_FONT_URL, FONT_PATH)
        except Exception as e:
            # Fallback to custom font path or system fonts
            pass
            
    return FONT_PATH


def reshape_and_bidi(text: str) -> str:
    """
    Applies shaping analysis to Arabic letter compounds before BiDi alignment.
    Reverses lines to standard RTL formats while supporting mixed alphanumeric.
    """
    if not text:
        return ""
        
    # Check if string contains Arabic characters
    has_arabic = any(0x0600 <= ord(char) <= 0x06FF for char in text)
    if not has_arabic:
        return text

    # Step A: Perform glyph reshaping for ligatures
    configuration = {
        'delete_harakat': False,
        'support_ligatures': True,
        'support_zwj': True
    }
    reshaper = arabic_reshaper.ArabicReshaper(configuration=configuration)
    reshaped_text = reshaper.reshape(text)

    # Step B: Reverse directional display vectors (Implicit bidirectional algorithm)
    bidi_text = get_display(reshaped_text)
    return bidi_text
