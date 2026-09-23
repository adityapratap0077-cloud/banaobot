"""BanaoBot "brain" — optional LLM layer (Google Gemini, free tier).

Architecture: the rule engine still owns bookings, the catalogue and FAQs —
deterministic flows that must never hallucinate a price or a booking. The
brain handles everything else: open questions, chit-chat, vague requests —
and keeps the conversation going naturally.

The owner pastes their own free Gemini API key (from Google AI Studio) in
Settings -> Bot brain. The key is encrypted at rest, exactly like the
WhatsApp tokens. No key, or any API failure -> the brain quietly steps
aside and the classic rule-based reply is used. The bot never breaks.

Public API:
  brain_on(biz) -> bool
      True when the business row has the brain enabled AND a stored key.
  chat(api_key, bundle, history, user_text, lang) -> str | None
      Ask Gemini. history = [(role, text), ...] with role in
      {"user", "model"}. Returns the reply text, or None on any failure.
  chat_with_error(api_key, bundle, history, user_text, lang)
      -> (str | None, str | None)
      Same as chat, but also returns a short key-free error description
      (HTTP status + Google's message) for the owner's diagnostics.
  build_system_prompt(bundle) -> str
      The business-aware system prompt: identity, catalogue, FAQs, hours,
      tone and guardrails.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

_GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
# Google retires model names over time (gemini-2.0-flash started returning
# 404 NOT_FOUND in Sep 2026), so try candidates in order and use the first
# model that answers. 404 -> try the next name; other errors stop the loop.
_GEMINI_MODELS = ("gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.0-flash")
_TIMEOUT = 25
_MAX_HISTORY = 8  # exchanges (user+bot pairs) sent as context


def brain_on(biz):
    """True when this business has the brain enabled with a stored key.

    Accepts the raw business row (brain_api_key_enc) and the normalized
    engine bundle (brain_key).
    """
    if not biz or not biz.get("brain_enabled"):
        return False
    enc = (biz.get("brain_api_key_enc") or "").strip()
    plain = (biz.get("brain_key") or "").strip()
    return bool(enc or plain)


def _menu_text(bundle):
    lines = []
    for c in bundle.get("menu") or []:
        name = (c.get("name") or {}).get("en", "")
        if not name:
            continue
        lines.append(f"[{name}]")
        for it in c.get("items") or []:
            iname = (it.get("name") or {}).get("en", "")
            if not iname:
                continue
            price = f" — ₹{it['price']}" if it.get("price") else ""
            desc = f" ({it['description']})" if it.get("description") else ""
            lines.append(f"  • {iname}{price}{desc}")
    return "\n".join(lines) or "(no catalogue yet)"


def _faq_text(bundle):
    lines = []
    for f in bundle.get("faqs") or []:
        q = ", ".join(f.get("keywords") or []) or f.get("id", "")
        a = (f.get("answer") or {}).get("en", "")
        if a:
            lines.append(f"Q ({q}): {a}")
    return "\n".join(lines) or "(no FAQs yet)"


def build_system_prompt(bundle):
    """Business-aware system prompt for the brain."""
    tpl = bundle.get("tpl") or {}
    name = bundle.get("name", "this business")
    tagline = (bundle.get("tagline") or {}).get("en", "")
    tone = bundle.get("tone") or "friendly"
    action_btn = (tpl.get("btn_action") or {}).get("en", "Book")
    hours = (f"{bundle.get('hours_open', '')}–{bundle.get('hours_close', '')}"
             .strip("–"))
    addr = (bundle.get("address") or {}).get("en", "")
    booking = "takes bookings via its booking button" \
        if bundle.get("booking_enabled") else "does not take bookings"

    return f"""You are the WhatsApp chat personality of "{name}".
{("Tagline: " + tagline) if tagline else ""}
You {booking}. Your tone is {tone}, warm and human — like texting a helpful friend, not a helpdesk.

WHAT YOU KNOW (never invent beyond this):
Catalogue:
{_menu_text(bundle)}

FAQs:
{_faq_text(bundle)}

Hours: {hours or "not specified"}
Address: {addr or "not specified"}

RULES — follow them strictly:
1. Reply in the SAME language the user used: English, Hindi (Devanagari), or Hinglish (Roman script Hindi). Never ask them to pick a language.
2. Keep replies SHORT, like WhatsApp texts: 1–3 short messages, under ~60 words total. No essays, no bullet-point lectures.
3. NEVER invent catalogue items, prices, hours, or offers that aren't listed above. If asked about something not listed, say you don't have it and suggest the closest thing you do have.
4. Bookings/orders happen ONLY through the bot's buttons. If the user wants to book or order, warmly point them to the "{action_btn}" button instead of taking details yourself.
5. Keep the conversation alive: when natural, end with a light follow-up question. React to what the person actually said — don't be generic.
6. Stay in character. Never mention being an AI, a language model, or "as an AI". You are {name}'s voice on chat.
7. If someone is rude or asks for something impossible, stay kind, brief, and steer back to how you can help."""


def _google_error_msg(body):
    """Pull a short human-readable message out of a Google error body."""
    try:
        err = json.loads(body).get("error") or {}
        msg = err.get("message") or ""
        status = err.get("status") or ""
        bits = [b for b in (status, msg) if b]
        if bits:
            return " — ".join(bits)[:280]
    except (ValueError, AttributeError):
        pass
    return (body or "").strip()[:280]


def _block_reason(data):
    try:
        fb = data.get("promptFeedback") or {}
        return fb.get("blockReason") or "unknown"
    except AttributeError:
        return "unknown"


def chat_with_error(api_key, bundle, history, user_text, lang="en"):
    """Ask Gemini. Returns (reply_text_or_None, error_detail_or_None).

    error_detail is a short, key-free description of the failure
    (HTTP status + Google's error message), safe to show the bot owner
    for diagnostics. It never contains the API key.
    """
    if not (api_key or "").strip():
        return None, "no API key saved"
    if not (user_text or "").strip():
        return None, "empty prompt"
    system = build_system_prompt(bundle)
    contents = []
    for role, text in (history or [])[-_MAX_HISTORY:]:
        if role not in ("user", "model") or not text:
            continue
        contents.append({"role": role,
                         "parts": [{"text": text[:1500]}]})
    contents.append({"role": "user",
                     "parts": [{"text": user_text[:2000]}]})
    lang_hint = {"hi": "Hinglish (Roman-script Hindi)",
                 "en": "English"}.get(lang, "English")
    payload = {
        "system_instruction": {
            "parts": [{"text": system + f"\n\nThe user is writing in {lang_hint}. Match it."}]
        },
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": 320,
            "temperature": 0.7,
        },
    }
    body = json.dumps(payload).encode()
    last_err = "unknown error"
    for model in _GEMINI_MODELS:
        req = urllib.request.Request(
            "%s/models/%s:generateContent?key=%s"
            % (_GEMINI_API, model, urllib.parse.quote(api_key.strip())),
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", "replace")
            except Exception:
                err_body = ""
            last_err = "HTTP %s%s" % (
                e.code, ": " + _google_error_msg(err_body) if err_body else "")
            if e.code == 404:
                continue  # retired/unknown model name -> try next candidate
            return None, last_err
        except Exception as e:  # network/timeout/DNS -> rule-based fallback
            return None, "request failed: %s" % type(e).__name__
        try:
            data = json.loads(raw)
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, TypeError, ValueError):
            return None, "unparseable response from the API"
        if not text:
            return None, ("API returned no text (block reason: %s)"
                          % _block_reason(data))
        return text, None
    return None, last_err


def chat(api_key, bundle, history, user_text, lang="en"):
    """Ask Gemini for a reply. Returns text, or None on any failure."""
    text, _ = chat_with_error(api_key, bundle, history, user_text, lang)
    return text
