"""Pure conversation engine for BanaoBot (multi-tenant WhatsApp bot platform).

NO I/O HERE: no database, no network, no API calls. Given the customer's
phone number, their message text, their current session dict, and the
*business* bundle (one business's menu/FAQs/settings — see
storage.Store.get_business_bundle), return (replies, new_session).

The engine NEVER sees more than one business's data: no cross-business
leakage by construction. Pass business=None to use the built-in Bhoj House
demo business (keeps the original single-business behaviour / tests working).

Replies are dicts in WhatsApp Cloud API message format:
  {"type": "text", "text": {"body": "..."}}
  {"type": "interactive", "interactive": {"type": "button", ...}}
  {"type": "interactive", "interactive": {"type": "list", ...}}

Side effects the server must perform (saving a booking, raising an owner
alert) are returned inside new_session["_events"] as a list of dicts:
  {"type": "save_booking", "booking": {...}}
  {"type": "owner_alert", "reason": "..."}
The caller applies them and strips the key before persisting the session.

Interactive callbacks: when a customer taps a button or list row, WhatsApp
sends back the reply *id* (not the title). Our ids look like "cmd:menu",
"cmd:cat:3", "cmd:confirm_booking". The demo UI and server.py forward
those ids here as the message text, so natural text and taps share one path.

Multi-tenant rule: this module never touches storage. server.py loads ONE
business bundle (see storage.get_business_bundle) and hands it in; every
string the customer sees is either business data, a template default
(templates.py), or a tone-pack variant (phrasing.py). Restaurant wording
("menu", "guests", "book a table") lives in the *restaurant template*, not
in this file — other templates plug in their own nouns and flows.

Voice: every repeated line comes from phrasing.py in the business's tone
(friendly / professional / casual), with 2-4 rotating variants per line,
natural Hinglish in Hindi mode, and the customer's name once learned.
The bot never claims to be a bot/AI — it just talks like a person.
"""

import copy
import re
import uuid
from datetime import date, datetime, timedelta

import phrasing
import templates
from content import FAQS as _CONTENT_FAQS
from content import MENU as _CONTENT_MENU
from content import RESTAURANT as _CONTENT_RESTAURANT
from content import STR

CMD = "cmd:"

# ---------------------------------------------------------------------------
# Business bundle
# ---------------------------------------------------------------------------
# The normalized shape the engine works with. storage.get_business_bundle
# builds this from the DB; default_business() builds it from content.py.

_DEFAULT_BIZ = None


def _booking_on(biz):
    """Resolved booking-enabled flag: business-level setting, template default."""
    val = biz.get("booking_enabled")
    if val is None:
        return bool(biz["tpl"]["booking_enabled"])
    return bool(val)


def _default_tpl():
    """Template bundle for the built-in demo business (restaurant)."""
    tpl = templates.get("restaurant")
    return {
        "id": "restaurant",
        "name": tpl["name"],
        "emoji": tpl["emoji"],
        "booking_enabled": True,
        "catalog": tpl["catalog"],
        "item_plural": tpl["item_plural"],
        "btn_catalog": tpl["btn_catalog"],
        "btn_action": tpl["btn_action"],
        "unit": tpl["unit"],
        "unit_word": tpl["unit_word"],
        "catalog_heading": tpl["catalog_heading"],
        "show_veg": tpl["show_veg"],
        "booked_ok": tpl["booked_ok"],
        "hours_note": tpl["hours_note"],
        "cat_examples": tpl["cat_examples"],
        "item_example": tpl["item_example"],
    }


def default_business():
    """The built-in Bhoj House demo business, in normalized bundle shape."""
    global _DEFAULT_BIZ
    if _DEFAULT_BIZ is None:
        _DEFAULT_BIZ = {
            "id": 1,
            "name": _CONTENT_RESTAURANT["name"],
            "prefix": "BH",
            "tagline": {
                "en": _CONTENT_RESTAURANT["tagline_en"],
                "hi": _CONTENT_RESTAURANT["tagline_hi"],
            },
            "owner_phone": _CONTENT_RESTAURANT["phone_display"],
            "address": {
                "en": _CONTENT_RESTAURANT["address_en"],
                "hi": _CONTENT_RESTAURANT["address_hi"],
            },
            "maps_link": _CONTENT_RESTAURANT["maps_link"],
            "hours_open": _CONTENT_RESTAURANT["hours_open"],
            "hours_close": _CONTENT_RESTAURANT["hours_close"],
            "last_booking": _CONTENT_RESTAURANT["last_booking"],
            "language": "en",
            "welcome": {"en": STR["welcome"]["en"], "hi": STR["welcome"]["hi"]},
            "tone": "friendly",
            "tpl": _default_tpl(),
            "menu": [
                {
                    "id": c["id"],
                    "name": {"en": c["name_en"], "hi": c["name_hi"]},
                    "emoji": c["emoji"],
                    "items": [
                        {
                            "name": {"en": i["name_en"], "hi": i["name_hi"]},
                            "price": i["price"],
                            "veg": bool(i["veg"]),
                            "description": "",
                        }
                        for i in c["items"]
                    ],
                }
                for c in _CONTENT_MENU
            ],
            "faqs": [
                {
                    "id": f["id"],
                    "keywords": list(f["keywords"]),
                    "answer": {"en": f["answer_en"], "hi": f["answer_hi"]},
                }
                for f in _CONTENT_FAQS
            ],
        }
    return _DEFAULT_BIZ


# ---------------------------------------------------------------------------
# Reply builders (WhatsApp Cloud API shapes)
# ---------------------------------------------------------------------------

def t(body):
    """Plain text message."""
    return {"type": "text", "text": {"body": body}}


def buttons(body, btns, footer=None):
    """Interactive message with up to 3 quick-reply buttons.

    btns: list of (id, title). Titles must be <= 20 chars (WhatsApp limit).
    """
    items = [
        {"type": "reply", "reply": {"id": bid, "title": title}}
        for bid, title in btns[:3]
    ]
    interactive = {
        "type": "button",
        "body": {"text": body},
        "action": {"buttons": items},
    }
    if footer:
        interactive["footer"] = {"text": footer}
    return {"type": "interactive", "interactive": interactive}


def pick_list(body, button_text, sections, footer=None):
    """Interactive list message. sections: [(title, [(id, title, desc), ...])]."""
    secs = [
        {
            "title": sec_title,
            "rows": [
                {"id": rid, "title": rtitle, "description": desc or ""}
                for rid, rtitle, desc in rows
            ],
        }
        for sec_title, rows in sections
    ]
    interactive = {
        "type": "list",
        "body": {"text": body},
        "action": {"button": button_text, "sections": secs},
    }
    if footer:
        interactive["footer"] = {"text": footer}
    return {"type": "interactive", "interactive": interactive}


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_HINDI_ROMAN = {
    "namaste", "namaskar", "khana", "khaana", "bhojan", "shakahari",
    "samay", "pata", "patta", "kitne", "kya", "hai", "mein", "main",
    "aap", "aapka", "mujhe", "chahiye", "batao", "bataiye", "kripya",
    "dhanyavaad", "shukriya", "accha", "acha", "haan", "nahi", "kal",
    "aaj", "daam", "keemat", "theek", "kripaya",
}


def looks_hindi(text):
    """True if the message is Hindi: Devanagari script or romanized words."""
    if re.search(r"[\u0900-\u097F]", text):
        return True
    words = set(re.findall(r"[a-z]+", text.lower()))
    return bool(words & _HINDI_ROMAN)


def _words(text):
    return set(re.findall(r"[\w\u0900-\u097F]+", text.lower()))


# ---------------------------------------------------------------------------
# Intent keyword sets (matched against whole words, not substrings)
# ---------------------------------------------------------------------------

_GREET = {
    "hi", "hii", "hiii", "hello", "hey", "yo", "namaste", "namaskar",
    "ram", "good", "morning", "evening", "afternoon", "नमस्ते", "नमस्कार",
}
# catalog browsing — generic nouns across all templates, not just "menu"
_MENU = {"menu", "menue", "khana", "khaana", "bhojan", "food", "dishes",
         "items", "rates", "pricelist", "price", "catalog", "catalogue",
         "product", "products", "service", "services",
         "course", "courses", "treatment", "treatments",
         "offering", "offerings", "collection",
         "मेन्यू", "खाना", "भोजन", "सामान", "कोर्स"}
_BOOK = {"book", "booking", "booked", "reserve", "reservation", "table",
         "seat", "appointment", "demo", "consult", "consultation",
         "visit", "slot", "session",
         "टेबल", "बुक", "बुकिंग", "सीट", "डेमो", "अपॉइंटमेंट"}
# order / purchase words -> enquiry flow for booking-disabled businesses
_ENQUIRE = {"order", "orders", "ordering", "buy", "buying", "purchase",
            "enquire", "enquiry", "ऑर्डर", "खरीद"}
_HOURS = {"hour", "hours", "timing", "timings", "open", "close", "closed",
          "location", "address", "where", "reach", "directions", "map",
          "समय", "पता", "खुला", "बंद", "लोकेशन"}
_HUMAN = {"human", "owner", "manager", "staff", "agent", "person", "someone",
          "anyone", "call", "help", "support", "complaint", "insaan", "insan",
          "aadmi", "admi", "malik", "इंसान", "मालिक",
          "मैनेजर", "स्टाफ", "फोन", "सहायता", "मदद"}
_CANCEL = {"cancel", "stop", "quit", "exit", "रद्द", "बंदकरो"}


def _has_any(words, bag):
    return bool(words & bag)


# ---------------------------------------------------------------------------
# Human voice: rotating phrasing variants per tone (phrasing.py)
# ---------------------------------------------------------------------------

def _reset_data(session, extra=None):
    """Fresh scratch data, preserving the variant-rotation counters and the
    customer's name across flow restarts."""
    data = session.get("data") or {}
    keep = {}
    for k in ("_vc", "cust_name"):
        if k in data:
            keep[k] = data[k]
    keep.update(extra or {})
    session["data"] = keep
    return keep


def _rotate(session, key, variants):
    """Pick the next rotating variant for `key`, bumping a per-key counter
    stored in the session. First use of a key always yields variants[0],
    so behaviour stays deterministic for tests and new conversations."""
    data = session.setdefault("data", {})
    vcmap = data.setdefault("_vc", {})
    vc = vcmap.get(key, 0)
    vcmap[key] = vc + 1
    return variants[vc % len(variants)]


def _cust_name(session):
    """' Rahul' once the bot has learned the customer's name, else ''."""
    n = ((session.get("data") or {}).get("cust_name") or "").strip()
    return f" {n}" if n else ""


def _say(session, biz, lang, key, **kw):
    """One human-voiced line: tone pack -> rotating variant -> formatted."""
    tone = biz.get("tone") or "friendly"
    table = phrasing.pack(tone).get(lang) or phrasing.pack(tone)["en"]
    kw.setdefault("name", _cust_name(session))
    return _rotate(session, key, table[key]).format(**kw)


# ---------------------------------------------------------------------------
# Booking field parsers
# ---------------------------------------------------------------------------

def parse_date(text, today):
    """'today'/'tomorrow'/'aaj'/'kal' or DD-MM[-YYYY]. Returns date or None."""
    s = text.strip().lower()
    if s in ("today", "aaj", "आज"):
        return today
    if s in ("tomorrow", "kal", "कल"):
        return today + timedelta(days=1)
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?$", s)
    if not m:
        return None
    d, mo = int(m.group(1)), int(m.group(2))
    y = int(m.group(3)) if m.group(3) else today.year
    if y < 100:
        y += 2000
    try:
        dt = date(y, mo, d)
    except ValueError:
        return None
    if dt < today:  # maybe they meant next year
        try:
            dt = date(y + 1, mo, d)
        except ValueError:
            return None
        if dt < today:
            return None
    if (dt - today).days > 60:
        return None
    return dt


def parse_time(text):
    """'8pm', '8 pm', '8:30pm', '19:00', '20' -> (hour, minute) or None."""
    s = text.strip().lower().replace(" ", "")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)?$", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if mi > 59:
        return None
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    elif not ap:
        if 1 <= h <= 10:
            h += 12          # "8" at a restaurant means 8pm
        elif h == 24:
            h = 0
    if not (0 <= h <= 23):
        return None
    return h, mi


def fmt_time(h, mi):
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{mi:02d} {ap}"


def _fmt_hm(hm, lang):
    """'22:30' -> '10:30 PM' (en) / 'रात 10:30' (hi)."""
    h, mi = int(hm[:2]), int(hm[3:5])
    if lang == "hi":
        if 5 <= h < 12:
            dp = "सुबह"
        elif 12 <= h < 17:
            dp = "दोपहर"
        elif 17 <= h < 21:
            dp = "शाम"
        else:
            dp = "रात"
        return f"{dp} {h % 12 or 12}:{mi:02d}"
    return fmt_time(h, mi)


def _hm_tuple(hm):
    return int(hm[:2]), int(hm[3:5])


def parse_party_size(text):
    m = re.search(r"\d+", text)
    if not m:
        return None
    n = int(m.group())
    return n if 1 <= n <= 20 else None


def parse_phone(text):
    digits = re.sub(r"\D", "", text)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if re.fullmatch(r"[6-9]\d{9}", digits) else None


# ---------------------------------------------------------------------------
# Menu / info renderers (all read from the business bundle)
# ---------------------------------------------------------------------------

def _cat_by_id(cat_id, biz):
    for c in biz["menu"]:
        if str(c["id"]) == str(cat_id):
            return c
    return None


def _action_cmd(biz):
    """The main action command for this business: book or enquire."""
    return "book" if _booking_on(biz) else "enquire"


def _action_btn(biz, lang):
    return (f"{CMD}{_action_cmd(biz)}", biz["tpl"]["btn_action"][lang])


def render_categories(lang, biz):
    rows = [
        (f"{CMD}cat:{c['id']}",
         f"{c['emoji']} {c['name'][lang]}",
         f"{len(c['items'])} {biz['tpl']['item_plural'][lang]}")
        for c in biz["menu"]
    ]
    sec_title = biz["tpl"]["catalog"][lang]
    return pick_list(
        biz["tpl"]["catalog_heading"][lang],
        STR["list_button"][lang],
        [(sec_title, rows)],
        footer=STR["hint_human"][lang],
    )


def render_items(cat, lang, biz):
    lines = [f"*{cat['name'][lang]}* {cat['emoji']}", ""]
    for it in cat["items"]:
        if biz["tpl"]["show_veg"]:
            mark = "🟢" if it["veg"] else "🔴"
            lines.append(f"{mark} {it['name'][lang]} — ₹{it['price']}")
        else:
            lines.append(f"▪️ {it['name'][lang]} — ₹{it['price']}")
    if biz["tpl"]["show_veg"]:
        lines += ["", "_🟢 veg · 🔴 non-veg_"]
    return "\n".join(lines)


def render_hours(lang, biz):
    addr = biz["address"][lang] or biz["address"]["en"]
    return biz["tpl"]["hours_note"][lang].format(
        open=_fmt_hm(biz["hours_open"], lang),
        close=_fmt_hm(biz["hours_close"], lang),
        last=_fmt_hm(biz["last_booking"], lang),
        addr=addr,
        maps=biz["maps_link"],
    )


def main_menu(session, lang, biz):
    welcome = biz["welcome"][lang] or biz["welcome"]["en"]
    nudge = _say(session, biz, lang, "greet_nudge")
    return buttons(
        f"{welcome}\n\n{nudge}",
        [
            (f"{CMD}menu", biz["tpl"]["btn_catalog"][lang]),
            _action_btn(biz, lang),
            (f"{CMD}info", STR["btn_info"][lang]),
        ],
        footer=STR["hint_human"][lang],
    )


def _faq_title(faq, lang):
    """Row title for an FAQ: first line of its answer minus emoji/markup."""
    first = (faq["answer"][lang] or faq["answer"]["en"] or "").split("\n")[0]
    first = re.sub(r"^[^\w\u0900-\u097F*]+", "", first).strip()
    first = first.strip("*").strip()
    return first or faq["id"]


def _faq_desc(faq, lang):
    lines = (faq["answer"][lang] or faq["answer"]["en"] or "").split("\n")
    body = " ".join(l for l in lines[1:] if l.strip())
    return body[:72]


def info_list(lang, biz):
    # preferred FAQ shortcuts first, then whatever the business has
    preferred = ["delivery", "veg", "payment", "parking", "spicy", "banquet"]
    by_id = {f["id"]: f for f in biz["faqs"]}
    picks = [by_id[k] for k in preferred if k in by_id]
    picks += [f for f in biz["faqs"] if f not in picks]
    rows = [
        (f"{CMD}hours", STR["row_hours"][lang], STR["row_hours_desc"][lang]),
    ]
    for f in picks[:3]:
        rows.append((f"{CMD}faq:{f['id']}",
                     _faq_title(f, lang)[:24], _faq_desc(f, lang)))
    rows += [
        (f"{CMD}human", STR["row_human"][lang], STR["row_human_desc"][lang]),
        (f"{CMD}lang_toggle", STR["row_lang"][lang], STR["row_lang_desc"][lang]),
    ]
    return pick_list(
        STR["info_list_body"][lang],
        STR["list_button"][lang],
        [("Info" if lang == "en" else "जानकारी", rows)],
    )


def quick_menu(session, lang, biz):
    """Small follow-up buttons after an answer."""
    return buttons(
        _say(session, biz, lang, "after_answer"),
        [
            (f"{CMD}menu", biz["tpl"]["btn_catalog"][lang]),
            _action_btn(biz, lang),
            (f"{CMD}human", STR["btn_human"][lang]),
        ],
    )


def match_faq(text, biz):
    low = text.lower()
    for faq in biz["faqs"]:
        for kw in faq["keywords"]:
            if kw.lower() in low:
                return faq
    return None


# ---------------------------------------------------------------------------
# Booking flow
# ---------------------------------------------------------------------------

def start_booking(session, lang, biz):
    _reset_data(session, {"booking": {}})
    session["state"] = "book_date"
    body = _say(session, biz, lang, "ask_date") + "\n\n" + STR["cancel_hint"][lang]
    return [t(body)]


def _confirm_summary(session, biz, lang, b):
    head = _say(session, biz, lang, "confirm_head")
    d = datetime.strptime(b["date"], "%Y-%m-%d").date()
    date_s = d.strftime("%a, %d %b %Y")
    h, mi = int(b["time"][:2]), int(b["time"][3:5])
    unit = biz["tpl"]["unit"][lang]
    if lang == "en":
        body = (f"{head}\n\n"
                f"📅 {date_s}\n"
                f"🕗 {fmt_time(h, mi)}\n"
                f"👥 {b['party_size']} {unit}\n"
                f"📝 {b['name']}\n"
                f"📱 +91 {b['phone']}")
    else:
        body = (f"{head}\n\n"
                f"📅 {date_s}\n"
                f"🕗 {fmt_time(h, mi)}\n"
                f"👥 {b['party_size']} {unit}\n"
                f"📝 {b['name']}\n"
                f"📱 +91 {b['phone']}")
    return body


def handle_booking(phone, raw, low, words, session, lang, events, today, biz):
    """Step-by-step booking state machine. Returns list of replies."""
    state = session["state"]
    data = session.setdefault("data", {})
    b = data.setdefault("booking", {})

    # universal escapes inside the booking flow
    if raw.startswith(CMD):
        cmd = raw[len(CMD):]
        if cmd == "cancel_booking":
            return cancel_booking(session, lang, biz)
        if cmd == "human":
            return do_handoff(phone, raw, session, lang, events, biz)
        # any other tap mid-booking: nudge back to the flow
        return [t(_say(session, biz, lang, "booking_interrupted"))]
    if _has_any(words, _CANCEL):
        return cancel_booking(session, lang, biz)

    if state == "book_date":
        dt = parse_date(raw, today)
        if not dt:
            return [t(_say(session, biz, lang, "bad_date"))]
        b["date"] = dt.isoformat()
        session["state"] = "book_time"
        ask = _say(session, biz, lang, "ask_time",
                   open=_fmt_hm(biz["hours_open"], lang),
                   close=_fmt_hm(biz["hours_close"], lang))
        return [t(ask + "\n\n" + STR["cancel_hint"][lang])]

    if state == "book_time":
        parsed = parse_time(raw)
        if not parsed:
            return [t(_say(session, biz, lang, "bad_time",
                            open=_fmt_hm(biz["hours_open"], lang),
                            last=_fmt_hm(biz["last_booking"], lang)))]
        h, mi = parsed
        open_t = _hm_tuple(biz["hours_open"])
        last_t = _hm_tuple(biz["last_booking"])
        if (h, mi) < open_t or (h, mi) > last_t:
            return [t(_say(session, biz, lang, "bad_time",
                            open=_fmt_hm(biz["hours_open"], lang),
                            last=_fmt_hm(biz["last_booking"], lang)))]
        b["time"] = f"{h:02d}:{mi:02d}"
        session["state"] = "book_size"
        ask = _say(session, biz, lang, "ask_unit", unit=biz["tpl"]["unit"][lang])
        return [t(ask + "\n\n" + STR["cancel_hint"][lang])]

    if state == "book_size":
        n = parse_party_size(raw)
        if n is None:
            return [t(_say(session, biz, lang, "bad_unit",
                            unit=biz["tpl"]["unit"][lang]))]
        b["party_size"] = n
        session["state"] = "book_name"
        return [t(_say(session, biz, lang, "ask_name") + "\n\n" + STR["cancel_hint"][lang])]

    if state == "book_name":
        name = raw.strip()
        if len(name) < 2:
            return [t(_say(session, biz, lang, "bad_name"))]
        b["name"] = name
        data["cust_name"] = name  # the bot now knows who it's talking to
        session["state"] = "book_phone"
        return [t(_say(session, biz, lang, "ask_phone") + "\n\n" + STR["cancel_hint"][lang])]

    if state == "book_phone":
        ph = parse_phone(raw)
        if not ph:
            return [t(_say(session, biz, lang, "bad_phone"))]
        b["phone"] = ph
        session["state"] = "book_confirm"
        return [buttons(
            _confirm_summary(session, biz, lang, b),
            [(f"{CMD}confirm_booking", STR["btn_confirm"][lang]),
             (f"{CMD}cancel_booking", STR["btn_cancel"][lang])],
        )]

    if state == "book_confirm":
        # user typed instead of tapping: accept yes/no-ish answers
        yes = {"yes", "yeah", "yep", "confirm", "haan", "ha", "पक्का", "हाँ", "हां"}
        no = {"no", "nahi", "नहीं", "cancel"}
        if words & yes:
            return confirm_booking(phone, session, lang, events, biz)
        if words & no:
            return cancel_booking(session, lang, biz)
        return [buttons(
            _confirm_summary(session, biz, lang, b),
            [(f"{CMD}confirm_booking", STR["btn_confirm"][lang]),
             (f"{CMD}cancel_booking", STR["btn_cancel"][lang])],
        )]

    # unknown booking sub-state: reset safely
    _reset_data(session)
    session["state"] = "idle"
    return [t(_say(session, biz, lang, "fallback")), quick_menu(session, lang, biz)]


def confirm_booking(phone, session, lang, events, biz):
    """Finalize the draft: emit save_booking event, reset to idle."""
    b = (session.get("data") or {}).get("booking", {})
    bid = biz["prefix"] + "-" + uuid.uuid4().hex[:6].upper()
    events.append({"type": "save_booking", "booking": {
        "id": bid,
        "phone": phone,            # customer's WhatsApp number
        "name": b.get("name", ""),
        "date": b.get("date", ""),
        "time": b.get("time", ""),
        "party_size": b.get("party_size", 0),
    }})
    name = (b.get("name") or "").strip()
    _reset_data(session)
    if name:
        session["data"]["cust_name"] = name
    session["state"] = "idle"
    body = _rotate(session, "booked_ok",
                   biz["tpl"]["booked_ok"][lang]).format(
        bid=bid, name=f" {name}" if name else "")
    return [t(body), quick_menu(session, lang, biz)]


def cancel_booking(session, lang, biz):
    data = session.get("data") or {}
    key = "enquiry_cancelled" if data.get("enquiry") else "cancelled"
    body = _say(session, biz, lang, key)
    _reset_data(session)
    session["state"] = "idle"
    return [t(body)]


def do_handoff(phone, raw, session, lang, events, biz):
    """Flag the conversation for the business team (owner alert)."""
    events.append({"type": "owner_alert",
                   "reason": f"handoff requested; last message: {raw[:200]}"})
    body = _say(session, biz, lang, "handoff", phone=biz["owner_phone"] or "us")
    _reset_data(session)
    session["state"] = "idle"
    return [t(body)]


# ---------------------------------------------------------------------------
# Enquiry flow (booking-disabled businesses: shops etc.)
# ---------------------------------------------------------------------------

def start_enquiry(session, lang, biz):
    _reset_data(session, {"enquiry": {}})
    session["state"] = "enq_items"
    return [t(_say(session, biz, lang, "enquire_ask_items"))]


def _enquiry_summary(session, biz, lang, enq):
    head = _say(session, biz, lang, "confirm_head")
    return (f"{head}\n\n"
            f"🛒 {enq.get('items', '')}\n"
            f"👤 {enq.get('name', '')}\n"
            f"📱 +91 {enq.get('phone', '')}")


def handle_enquiry(phone, raw, low, words, session, lang, events, biz):
    """Collect items -> name -> phone, then raise an owner alert."""
    data = session.setdefault("data", {})
    enq = data.setdefault("enquiry", {})
    sub = session.get("state")

    if raw.startswith(CMD):
        cmd = raw[len(CMD):]
        if cmd == "cancel_booking":
            return cancel_booking(session, lang, biz)
        if cmd == "human":
            return do_handoff(phone, raw, session, lang, events, biz)
        return [t(_say(session, biz, lang, "booking_interrupted"))]
    if _has_any(words, _CANCEL):
        return cancel_booking(session, lang, biz)

    if sub == "enq_items":
        enq["items"] = raw.strip()
        session["state"] = "enq_name"
        return [t(_say(session, biz, lang, "ask_name"))]
    if sub == "enq_name":
        name = raw.strip()
        if len(name) < 2:
            return [t(_say(session, biz, lang, "bad_name"))]
        enq["name"] = name
        data["cust_name"] = name  # the bot now knows who it's talking to
        session["state"] = "enq_phone"
        return [t(_say(session, biz, lang, "ask_phone"))]
    if sub == "enq_phone":
        ph = parse_phone(raw)
        if not ph:
            return [t(_say(session, biz, lang, "bad_phone"))]
        enq["phone"] = ph
        session["state"] = "enq_confirm"
        return [buttons(
            _enquiry_summary(session, biz, lang, enq),
            [(f"{CMD}confirm_enquiry", STR["btn_confirm"][lang]),
             (f"{CMD}cancel_booking", STR["btn_cancel"][lang])],
        )]
    if sub == "enq_confirm":
        # user typed instead of tapping: accept yes/no-ish answers
        yes = {"yes", "yeah", "yep", "confirm", "haan", "ha", "पक्का", "हाँ", "हां"}
        no = {"no", "nahi", "नहीं", "cancel"}
        if words & yes:
            return confirm_enquiry(phone, session, lang, events, biz)
        if words & no:
            return cancel_booking(session, lang, biz)
        return [buttons(
            _enquiry_summary(session, biz, lang, enq),
            [(f"{CMD}confirm_enquiry", STR["btn_confirm"][lang]),
             (f"{CMD}cancel_booking", STR["btn_cancel"][lang])],
        )]

    # unknown enquiry sub-state: reset safely
    _reset_data(session)
    session["state"] = "idle"
    return [quick_menu(session, lang, biz)]


def confirm_enquiry(phone, session, lang, events, biz):
    """Turn the enquiry into an owner alert (no date/time booking)."""
    data = session.get("data") or {}
    enq = data.get("enquiry", {})
    name = (enq.get("name") or "").strip()
    reason = (f"🛒 New order enquiry from {name} "
              f"(+91 {enq.get('phone', '')}): {enq.get('items', '')}")
    events.append({"type": "owner_alert", "reason": reason})
    _reset_data(session)
    if name:
        session["data"]["cust_name"] = name
    session["state"] = "idle"
    return [t(_say(session, biz, lang, "enquire_ok")),
            quick_menu(session, lang, biz)]


# ---------------------------------------------------------------------------
# Idle intent routing
# ---------------------------------------------------------------------------

def handle_idle(phone, raw, low, words, session, lang, events, today, biz):
    if _has_any(words, _GREET):
        return [main_menu(session, lang, biz)]

    faq = match_faq(raw, biz)
    if faq:
        ans = faq["answer"][lang] or faq["answer"]["en"]
        return [t(ans), quick_menu(session, lang, biz)]

    if _has_any(words, _MENU):
        session["state"] = "menu_cat"
        return [render_categories(lang, biz)]

    if _has_any(words, _ENQUIRE) and not _booking_on(biz):
        return start_enquiry(session, lang, biz)

    if _has_any(words, _BOOK):
        if _booking_on(biz):
            return start_booking(session, lang, biz)
        return start_enquiry(session, lang, biz)

    if _has_any(words, _HOURS - {"time"}) or "timing" in low:
        return [t(render_hours(lang, biz)), quick_menu(session, lang, biz)]

    if _has_any(words, _HUMAN):
        return do_handoff(phone, raw, session, lang, events, biz)

    fallback = (_say(session, biz, lang, "fallback") + "\n\n"
                + STR["hint_human"][lang])
    return [t(fallback), quick_menu(session, lang, biz)]


def handle_menu_cat(raw, low, words, session, lang, biz):
    """Let the customer pick a category by typing its name."""
    for c in biz["menu"]:
        names = {c["name"]["en"].lower(), c["name"]["hi"], str(c["id"])}
        if low in names or c["name"]["en"].lower() in low:
            session["state"] = "menu_items"
            _reset_data(session, {"cat": str(c["id"])})
            return [t(render_items(c, lang, biz)),
                    buttons(_say(session, biz, lang, "after_answer"),
                            [(f"{CMD}menu", STR["btn_back"][lang]),
                             _action_btn(biz, lang)])]
    if _has_any(words, _CANCEL) or low in ("back", "वापस"):
        session["state"] = "idle"
        return [main_menu(session, lang, biz)]
    return [render_categories(lang, biz)]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _emit(session, events):
    session["_events"] = events
    return session


def handle_message(phone, text, session, business=None, today=None):
    """See module docstring. business=None -> Bhoj House demo business.
    today defaults to date.today() (injectable for tests)."""
    biz = business if business is not None else default_business()
    today = today or date.today()
    if session:
        session = copy.deepcopy(session)
    else:
        session = {"lang": None, "state": "idle", "data": {}}
    session.setdefault("lang", None)
    session.setdefault("state", "idle")
    session.setdefault("data", {})
    events = []

    raw = (text or "").strip()
    low = raw.lower()
    words = _words(raw)

    # explicit language switch (works in any state)
    if low in ("/english", "english"):
        session["lang"] = "en"
        return [t(STR["lang_set_en"]["en"])], _emit(session, events)
    if low in ("/hindi", "hindi", "हिंदी"):
        session["lang"] = "hi"
        return [t(STR["lang_set_hi"]["hi"])], _emit(session, events)

    # auto-detect language on first contact (default to business language)
    if not session.get("lang"):
        session["lang"] = "hi" if looks_hindi(raw) else biz.get("language", "en")
    lang = session["lang"]

    # interactive button/list taps arrive as "cmd:..." ids
    if raw.startswith(CMD):
        cmd = raw[len(CMD):]
        if cmd == "menu":
            session["state"] = "menu_cat"
            return [render_categories(lang, biz)], _emit(session, events)
        if cmd == "book":
            if _booking_on(biz):
                replies = start_booking(session, lang, biz)
            else:
                replies = start_enquiry(session, lang, biz)
            return replies, _emit(session, events)
        if cmd == "enquire":
            replies = start_enquiry(session, lang, biz)
            return replies, _emit(session, events)
        if cmd == "info":
            return [info_list(lang, biz)], _emit(session, events)
        if cmd == "hours":
            return [t(render_hours(lang, biz)),
                    quick_menu(session, lang, biz)], _emit(session, events)
        if cmd == "human":
            return do_handoff(phone, raw, session, lang, events, biz), _emit(session, events)
        if cmd == "confirm_booking":
            return confirm_booking(phone, session, lang, events, biz), _emit(session, events)
        if cmd == "confirm_enquiry":
            return confirm_enquiry(phone, session, lang, events, biz), _emit(session, events)
        if cmd == "cancel_booking":
            return cancel_booking(session, lang, biz), _emit(session, events)
        if cmd == "lang_toggle":
            session["lang"] = "hi" if lang == "en" else "en"
            key = "lang_set_hi" if session["lang"] == "hi" else "lang_set_en"
            new_lang = session["lang"]
            return [t(STR[key][new_lang]),
                    main_menu(session, new_lang, biz)], _emit(session, events)
        if cmd.startswith("cat:"):
            cat = _cat_by_id(cmd[4:], biz)
            if cat:
                session["state"] = "menu_items"
                _reset_data(session, {"cat": str(cat["id"])})
                return [t(render_items(cat, lang, biz)),
                        buttons(_say(session, biz, lang, "after_answer"),
                                [(f"{CMD}menu", STR["btn_back"][lang]),
                                 _action_btn(biz, lang)])], _emit(session, events)
        if cmd.startswith("faq:"):
            faq = next((f for f in biz["faqs"] if f["id"] == cmd[4:]), None)
            if faq:
                ans = faq["answer"][lang] or faq["answer"]["en"]
                return [t(ans),
                        quick_menu(session, lang, biz)], _emit(session, events)
        # unknown cmd: fall through to normal handling

    state = session["state"]
    if state == "idle":
        replies = handle_idle(phone, raw, low, words, session, lang, events, today, biz)
    elif state == "menu_cat":
        # natural-text category pick, or back
        replies = handle_menu_cat(raw, low, words, session, lang, biz)
    elif state == "menu_items":
        # any text here: back to categories (items are display-only)
        session["state"] = "menu_cat"
        replies = [render_categories(lang, biz)]
    elif state.startswith("book_"):
        replies = handle_booking(phone, raw, low, words, session, lang, events, today, biz)
    elif state.startswith("enq_"):
        replies = handle_enquiry(phone, raw, low, words, session, lang, events, biz)
    else:
        session["state"] = "idle"
        replies = [t(_say(session, biz, lang, "fallback")),
                   quick_menu(session, lang, biz)]

    return replies, _emit(session, events)
