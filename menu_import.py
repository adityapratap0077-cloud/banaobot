"""Auto-catalogue builder for BanaoBot: turn a menu into catalogue items.

The owner pastes menu text, uploads a .txt/.csv file, or uploads a photo/PDF
of their menu (read with the free OCR.space API). :func:`parse_menu_text`
then heuristically extracts categories, item names and prices so the review
screen can show an editable draft before anything is saved.

No ML, no API keys, no extra dependencies — pure regex heuristics tuned for
Indian menus in English, Hindi (Devanagari) and Hinglish, e.g.::

    STARTERS
    Paneer Tikka ............ ₹250
    Chicken 65 - Rs. 220
    Masala Dosa | 120
    ## Main Course
    Butter Chicken (creamy tomato gravy) 320/-

Public API:
  parse_menu_text(text) -> list[dict]
      [{"category": str, "emoji": str,
        "items": [{"name": str, "price": int,
                   "description": str, "veg": int}]}]
  ocr_image(data: bytes, filename: str) -> str
      OCR a menu photo/PDF via the free OCR.space tier. Raises OCRError
      when OCR is unavailable so callers can fall back to "paste the text".
"""

import io
import json
import re
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# OCR (free tier, no key signup — uses OCR.space's public demo key)
# ---------------------------------------------------------------------------

_OCR_URL = "https://api.ocr.space/parse/image"
_OCR_KEY = "helloworld"  # OCR.space's public demo key; low rate limits
_OCR_TIMEOUT = 40


class OCRError(Exception):
    """Raised when menu OCR fails; caller should ask the user to paste text."""


def ocr_image(data: bytes, filename: str = "menu.jpg") -> str:
    """Extract text from a menu photo/PDF. Raises OCRError on any failure."""
    if not data:
        raise OCRError("Empty file.")
    boundary = "----banaobotocrboundary"
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        'Content-Disposition: form-data; name="apikey"\r\n\r\n'.encode()
        + _OCR_KEY.encode() + b"\r\n"
    )
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        'Content-Disposition: form-data; name="OCREngine";\r\n\r\n2\r\n'.encode()
    )
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    body.write(data)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        _OCR_URL,
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_OCR_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        raise OCRError(f"OCR service unreachable: {exc}") from exc
    if payload.get("IsErroredOnProcessing"):
        msg = payload.get("ErrorMessage") or ["OCR failed"]
        raise OCRError("; ".join(str(m) for m in msg))
    texts = [
        (r.get("ParsedText") or "")
        for r in (payload.get("ParsedResults") or [])
    ]
    text = "\n".join(texts).strip()
    if not text:
        raise OCRError("OCR read the image but found no text — "
                       "try a clearer photo, or paste the menu text.")
    return text


# ---------------------------------------------------------------------------
# Menu text -> structured catalogue
# ---------------------------------------------------------------------------

# Explicit currency spellings, e.g. "₹250", "Rs. 250", "250/-", "250 ₹".
_PRICE_PATTERNS = [
    re.compile(r"₹\s*([\d,]{1,7})"),
    re.compile(r"\bRs\.?\s*([\d,]{1,7})", re.IGNORECASE),
    re.compile(r"\bINR\s*([\d,]{1,7})", re.IGNORECASE),
    re.compile(r"([\d,]{1,7})\s*₹"),
    re.compile(r"([\d,]{1,7})\s*/-"),
]

# Fallback: a bare number at the very end of the line ("Butter Chicken 320").
_TRAILING_NUMBER = re.compile(r"[\s:>|\-–—]+([\d,]{1,6})\s*[.)]?\s*$")

# Lines that are never items, even without a price.
_JUNK = re.compile(
    r"^(menu|our menu|price list|rate list|page\s*\d+|www\.|http|"
    r"\+?91[\s-]?\d[\d\s-]{7,}|timings?|hours?|address).*$",
    re.IGNORECASE,
)

_NONVEG_WORDS = {
    "chicken", "mutton", "fish", "prawn", "shrimp", "crab", "lobster",
    "egg", "anda", "keema", "kheema", "bacon", "ham", "sausage", "salami",
    "turkey", "duck", "meat", "non-veg", "nonveg", "chilli chicken",
}

_CATEGORY_EMOJI = [
    ({"starter", "snack", "chaat", "tandoor", "kebab", "appetizer"}, "🥗"),
    ({"main", "curry", "sabzi", "dal", "paneer", "gravy"}, "🍛"),
    ({"biryani", "rice", "pulao", "fried rice"}, "🍚"),
    ({"bread", "roti", "naan", "paratha", "kulcha"}, "🫓"),
    ({"chinese", "noodle", "momos", "manchurian"}, "🍜"),
    ({"south", "dosa", "idli", "uttapam", "vada"}, "🥞"),
    ({"pizza"}, "🍕"),
    ({"burger", "sandwich", "wrap", "roll"}, "🍔"),
    ({"dessert", "sweet", "ice cream", "cake", "mithai"}, "🍨"),
    ({"beverage", "drink", "juice", "shake", "coffee", "chai", "tea",
      "lassi", "mocktail", "cold drink"}, "☕"),
    ({"combo", "thali", "platter", "meal"}, "🍱"),
    ({"breakfast"}, "🍳"),
]


def _category_emoji(name: str) -> str:
    low = name.lower()
    for words, emoji in _CATEGORY_EMOJI:
        if any(w in low for w in words):
            return emoji
    return "🍽️"


def _clean_name(text: str) -> str:
    """Strip bullets, numbering, filler dots and stray punctuation."""
    text = re.sub(r"^[\s•●▪▫\-\*#>~_]+", "", text)          # leading bullets
    text = re.sub(r"^\d{1,3}[.)\]\-:]+\s*", "", text)        # "12. ", "3)"
    text = re.sub(r"[.·•\-–—_]{2,}", " ", text)              # dot leaders
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" :-–—|•").strip()


def _split_name_description(name: str):
    """Pull a trailing '(...)' aside as the item description."""
    m = re.search(r"\(([^()]{2,80})\)\s*$", name)
    if m:
        desc = m.group(1).strip()
        name = name[:m.start()].strip()
        return name, desc
    return name, ""


def _extract_price(line: str):
    """Return (name_part, price) or (None, None) when no price found."""
    for pat in _PRICE_PATTERNS:
        m = pat.search(line)
        if m:
            try:
                price = int(m.group(1).replace(",", ""))
            except ValueError:
                continue
            name = (line[:m.start()] + " " + line[m.end():]).strip()
            return _clean_name(name), price
    m = _TRAILING_NUMBER.search(line.rstrip(". "))
    if m:
        try:
            price = int(m.group(1).replace(",", ""))
        except ValueError:
            return None, None
        return _clean_name(line[:m.start()]), price
    return None, None


def _looks_like_category(line: str) -> bool:
    """A priceless line is a category header when it *announces* one."""
    stripped = line.strip()
    if re.match(r"^#{1,3}\s+\S", stripped):
        return True  # ## Main Course
    s = stripped.strip("#*~_ ").strip()
    if not s or len(s) > 42:
        return False
    if "menu" in s.lower() and len(s.split()) <= 4:
        return False  # "Sharma Dhaba MENU" — the shop name, not a category
    if s.endswith(":"):
        return True
    if s.isupper() and len(s) > 2:
        return True
    if re.match(r"^[-=~]{2,}\s*.+\s*[-=~]{2,}$", stripped):
        return True  # --- Starters ---
    return False


def _looks_veg(name: str) -> int:
    low = name.lower()
    return 0 if any(w in low for w in _NONVEG_WORDS) else 1


def parse_menu_text(text: str):
    """Parse free-form menu text into categories + items.

    Returns a list of {"category", "emoji", "items": [...]} dicts, in the
    order they appeared. Lines that are neither a header nor a priced item
    are skipped silently.
    """
    groups = []
    current = None

    def _ensure_group(name):
        nonlocal current
        for g in groups:
            if g["category"].lower() == name.lower():
                current = g
                return
        current = {"category": name, "emoji": _category_emoji(name),
                   "items": []}
        groups.append(current)

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or _JUNK.match(line):
            continue
        name, price = _extract_price(line)
        if price is not None and name:
            if len(name) < 2 or len(name) > 80:
                continue
            if current is None:
                _ensure_group("Menu")
            name, desc = _split_name_description(name)
            if not name:
                continue
            current["items"].append({
                "name": name,
                "price": price,
                "description": desc,
                "veg": _looks_veg(name),
            })
        elif _looks_like_category(line):
            header = line.strip().strip("#*~_ ").rstrip(":").strip()
            header = re.sub(r"^[-=~]{2,}\s*", "", header)
            header = re.sub(r"\s*[-=~]{2,}$", "", header).strip()
            if header:
                _ensure_group(header.title() if header.isupper() else header)
        # anything else (addresses, notes, timings) is ignored

    return [g for g in groups if g["items"]]


def parse_upload(filename: str, data: bytes):
    """Read an uploaded menu file into text.

    .txt/.csv are read directly; images/PDFs go through OCR. Returns
    (text, via_ocr). Raises OCRError when OCR is needed but fails.
    """
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()
    if ext in ("txt", "csv", "text"):
        return data.decode("utf-8", "replace"), False
    if ext in ("png", "jpg", "jpeg", "webp", "bmp", "pdf", "tiff"):
        return ocr_image(data, filename), True
    # unknown extension: try as text first, it's the friendliest guess
    try:
        return data.decode("utf-8"), False
    except UnicodeDecodeError:
        raise OCRError(f"Can't read .{ext} files — upload a photo, PDF or "
                       ".txt of your menu instead.")
