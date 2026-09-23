"""WhatsApp Cloud API connector for prompt-first BanaoBot.

Mounted by server.py as the ``whatsapp`` blueprint under /webhooks.

  GET  /webhooks/whatsapp   Meta subscription verification handshake
  POST /webhooks/whatsapp   incoming messages -> linked prompt-first bot
                            -> reply via the Graph API

How it works: each owner connects their own Meta WhatsApp app in
/app/whatsapp (phone_number_id + access token + optional app secret).
Meta sends incoming messages to POST /webhooks/whatsapp; we look up the
connection by metadata.phone_number_id, run the linked bot's prompt through
Gemini with the owner's brain key, and send the reply back through the
Graph API.

Hard rules:
  * Always 200 for Meta on processed or ignored payloads — never 500.
  * Raw access tokens are never printed or logged.
  * Per-sender conversation history is kept in-memory only (cap 10 turns),
    keyed by (phone_number_id, wa_id).
  * DEMO_MODE=true logs outgoing sends instead of calling Meta.
"""

import hashlib
import hmac
import json
import os
import urllib.request

from flask import Blueprint, Response, current_app, jsonify, request

import brain

bp = Blueprint("whatsapp", __name__)

GRAPH_VERSION = "v21.0"
MAX_HISTORY_TURNS = 10          # per-sender turns kept in memory
_MAX_HISTORY_SENDERS = 5000    # guard so the dict cannot grow unbounded

# In-memory per-sender conversation history:
#   {"<pnid>:<wa_id>": [("user", text), ("model", text), ...]}
_wa_history = {}

DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() in ("1", "true", "yes")


def store():
    return current_app.config["store"]


# ---------------------------------------------------------------------------
# outgoing Graph API calls
# ---------------------------------------------------------------------------

def _graph_post(phone_number_id, access_token, payload):
    """POST one payload to the WhatsApp Cloud API.

    In demo mode the send is only logged (no Meta call). The raw token is
    never included in any log line.
    """
    url = ("https://graph.facebook.com/%s/%s/messages"
           % (GRAPH_VERSION, phone_number_id))
    if DEMO_MODE:
        kind = payload.get("type") or payload.get("status") or "?"
        body = ""
        if payload.get("type") == "text":
            body = (payload.get("text") or {}).get("body", "")[:160]
        print(f"[whatsapp DEMO -> {phone_number_id} {kind}] {body}")
        return {"demo": True}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _mark_read(phone_number_id, access_token, message_id):
    try:
        _graph_post(phone_number_id, access_token, {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        })
    except Exception as exc:  # never break message handling over this
        print(f"[whatsapp] mark-read failed: {type(exc).__name__}")


def _send_text(phone_number_id, access_token, wa_id, text):
    _graph_post(phone_number_id, access_token, {
        "messaging_product": "whatsapp",
        "to": wa_id,
        "type": "text",
        "text": {"body": (text or "")[:4000]},
    })


# ---------------------------------------------------------------------------
# signature verification
# ---------------------------------------------------------------------------

def _signature_ok(raw_body, app_secret, header_value):
    """Verify Meta's X-Hub-Signature-256 header (hmac sha256)."""
    if not app_secret or not header_value:
        return False
    expected = "sha256=" + hmac.new(
        app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value)


# ---------------------------------------------------------------------------
# payload parsing
# ---------------------------------------------------------------------------

def _iter_incoming(data):
    """Yield (pnid, wa_id, message_id, text) for text messages only.

    Statuses, reactions, images, audio, etc. are ignored (Meta still gets
    its 200 OK from the route).
    """
    for entry in data.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            pnid = (value.get("metadata") or {}).get("phone_number_id")
            for msg in value.get("messages", []) or []:
                wa_id = msg.get("from")
                text = (msg.get("text") or {}).get("body")
                if pnid and wa_id and isinstance(text, str) and text.strip():
                    yield pnid, wa_id, msg.get("id"), text


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

@bp.get("/whatsapp")
def webhook_verify():
    """Meta subscription handshake: the verify_token must match one of our
    stored connections; the challenge is echoed back as plain text."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge", "")
    if mode == "subscribe" and token:
        conn = store().get_whatsapp_connection_by_verify_token(token)
        if conn is not None:
            return Response(challenge, status=200, mimetype="text/plain")
    return Response("verification failed", status=403)


@bp.post("/whatsapp")
def webhook_receive():
    raw_body = request.get_data() or b""
    data = request.get_json(force=True, silent=True) or {}
    try:
        for pnid, wa_id, message_id, text in _iter_incoming(data):
            _handle_message(raw_body, pnid, wa_id, message_id, text)
    except Exception as exc:  # Meta retries on anything but 200
        print(f"[whatsapp] webhook error: {type(exc).__name__}: {exc}")
    return jsonify({"ok": True})


def _handle_message(raw_body, pnid, wa_id, message_id, text):
    """Route one incoming text message to the owner's linked bot."""
    st = store()
    conn = st.get_whatsapp_connection_by_pnid(pnid)
    if conn is None:
        print(f"[whatsapp] unknown phone_number_id={pnid}; ignored")
        return
    if conn.get("app_secret"):
        sig = request.headers.get("X-Hub-Signature-256", "")
        if not _signature_ok(raw_body, conn["app_secret"], sig):
            print("[whatsapp] bad X-Hub-Signature-256; rejected")
            return  # signature failure: drop silently, keep the 200
    token = conn["access_token"]
    if message_id:
        _mark_read(pnid, token, message_id)

    # Resolve the linked prompt-first bot: must exist, belong to the
    # connection owner, and the connection must be enabled.
    bot = None
    if conn.get("enabled") and conn.get("bot_id"):
        maybe = st.get_bot(conn["bot_id"])
        if maybe and maybe["user_id"] == conn["user_id"]:
            bot = maybe

    key = st.get_user_brain_key(conn["user_id"])
    if bot is None or not (key or "").strip():
        # Honest "not awake" path — chat_with_prompt says it for us when
        # the key is missing; a missing/disabled bot needs it too.
        reply = brain.chat_with_prompt(
            "", bot["name"] if bot else "Bot",
            bot["prompt"] if bot else "", [], text)
    else:
        hkey = "%s:%s" % (pnid, wa_id)
        history = _wa_history.get(hkey, [])
        try:
            reply = brain.chat_with_prompt(
                key, bot["name"], bot["prompt"], history, text)
        except Exception as exc:
            print(f"[whatsapp] brain error: {type(exc).__name__}")
            reply = ("I couldn't reach my brain right now — "
                     "please try again in a moment.")
        history = (history + [("user", text[:1500]),
                              ("model", (reply or "")[:1500])])
        history = history[-(MAX_HISTORY_TURNS * 2):]
        _wa_history[hkey] = history
        if len(_wa_history) > _MAX_HISTORY_SENDERS:
            _wa_history.clear()

    try:
        _send_text(pnid, token, wa_id, reply)
    except Exception as exc:
        print(f"[whatsapp] send failed: {type(exc).__name__}: {exc}")
