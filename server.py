"""Flask server for BanaoBot — self-serve multi-tenant WhatsApp bot platform.

Endpoints:
  GET  /webhook          Meta verification handshake
  POST /webhook          incoming WhatsApp messages -> route by phone_number_id
                         -> engine -> Cloud API (per-business credentials)
  POST /demo/message     {phone, text, business_id?} -> engine replies as JSON
                         (simulator; needs zero Meta setup)
  GET  /                 demo phone-style chat UI (Bhoj House demo business)
  GET  /admin            legacy admin links (default demo business)
  GET  /admin/bookings   HTML table of bookings (default demo business)
  GET  /admin/alerts     HTML table of owner handoff alerts (default business)
  /app/*                 self-serve dashboard (dashboard.py blueprint):
                         signup/login, onboarding wizard, menu builder,
                         FAQ editor, settings, live preview, WhatsApp connect

Env vars:
  DEMO_MODE=true         (default) log outgoing messages instead of calling Meta
  VERIFY_TOKEN           must match the token you enter in Meta's dashboard
  WHATSAPP_TOKEN         fallback access token (live mode, single-business)
  PHONE_NUMBER_ID        fallback sender phone number id (live mode)
  BANAOBOT_SECRET        Flask session secret (dashboard login)
  PORT                   default 5000

Run locally:
  DEMO_MODE=true python3 server.py
  -> owner demo chat:  http://localhost:5000/
  -> self-serve app:   http://localhost:5000/app/
"""

import json
import os
import urllib.request

from flask import Flask, Response, jsonify, request, send_from_directory

import engine
from storage import Store

app = Flask(__name__)
app.secret_key = os.environ.get("BANAOBOT_SECRET", "banaobot-dev-key-change-me")

# Behind Render/any reverse proxy: trust X-Forwarded-* so url_for(_external=True)
# builds https:// URLs (required for OAuth redirect URIs).
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
except ImportError:  # pragma: no cover - werkzeug ships with Flask
    pass

DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() in ("1", "true", "yes")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
GRAPH_VERSION = "v21.0"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
store = Store(os.environ.get("BANAOBOT_DB", os.path.join(BASE_DIR, "bot.db")))
app.config["store"] = store  # dashboard blueprint reads the store from here

# Self-serve dashboard (auth, onboarding wizard, menu builder, preview...).
# Import is optional so the bot core keeps running even if dashboard.py
# is absent or being edited.
try:
    import dashboard  # noqa: E402
    app.register_blueprint(dashboard.bp, url_prefix="/app")
    print("[banaobot] dashboard mounted at /app/")
except Exception as exc:  # pragma: no cover - surfaced loudly in logs
    print(f"[banaobot] WARNING: dashboard not loaded: {exc}")


# ---------------------------------------------------------------------------
# Outgoing messages
# ---------------------------------------------------------------------------

def send_to_whatsapp(phone, reply, business=None):
    """Send one reply dict via the Cloud API, or log it in demo mode.

    In live mode each connected business uses its OWN stored credentials;
    the WHATSAPP_TOKEN/PHONE_NUMBER_ID env vars are only a fallback for
    single-business setups.
    """
    payload = {"messaging_product": "whatsapp", "to": phone}
    payload.update(reply)
    if DEMO_MODE:
        biz_name = (business or {}).get("name", "?") if business else "?"
        print(f"[DEMO send -> {phone} via {biz_name}] "
              f"{json.dumps(payload, ensure_ascii=False)[:300]}")
        return {"demo": True}
    token, sender_pnid = "", ""
    if business:
        token = store.get_whatsapp_token(business["id"])
        sender_pnid = business.get("whatsapp_phone_number_id") or ""
    token = token or WHATSAPP_TOKEN
    sender_pnid = sender_pnid or PHONE_NUMBER_ID
    if not token or not sender_pnid:
        raise RuntimeError(
            "No WhatsApp credentials: connect the business in /app/ or set "
            "WHATSAPP_TOKEN and PHONE_NUMBER_ID")
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{sender_pnid}/messages"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Core pipeline: business -> session -> engine -> events -> session -> replies
# ---------------------------------------------------------------------------

def resolve_business_id(business_id=None, phone_number_id=None):
    """Map an incoming message to a business.

    Priority: explicit business_id (demo/simulator) -> Meta phone_number_id
    -> default demo business (DEMO_MODE only; live mode returns None so the
    webhook ignores unmapped numbers instead of misrouting them).
    """
    if business_id:
        return business_id if store.get_business(business_id) else None
    if phone_number_id:
        biz = store.get_business_by_phone_number_id(phone_number_id)
        if biz:
            return biz["id"]
    if DEMO_MODE:
        return store.get_default_business_id()
    return None


def process_message(phone, text, business_id=None, phone_number_id=None):
    """Run one incoming message through the whole pipeline.

    Returns (replies, business_id). Sessions, bookings and alerts are all
    scoped to the resolved business — a message for business A can never
    see business B's data.
    """
    business_id = resolve_business_id(business_id, phone_number_id)
    if not business_id:
        return [], None
    bundle = store.get_business_bundle(business_id)
    session = store.get_session(phone, business_id)
    replies, new_session = engine.handle_message(phone, text, session, bundle)
    events = new_session.pop("_events", [])
    for ev in events:
        if ev["type"] == "save_booking":
            store.save_booking(ev["booking"], business_id)
        elif ev["type"] == "owner_alert":
            store.add_alert(phone, ev["reason"], business_id)
    store.save_session(phone, new_session, business_id)
    store.log_message(business_id, phone, "in")
    return replies, business_id


# ---------------------------------------------------------------------------
# Meta webhook
# ---------------------------------------------------------------------------

def extract_incoming(data):
    """Yield (phone_number_id, phone, text) from a Meta webhook payload.

    Handles plain text, button replies and list replies. Ignores
    delivery-status callbacks.
    """
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            pnid = (value.get("metadata") or {}).get("phone_number_id")
            for msg in value.get("messages", []):
                phone = msg.get("from")
                text = None
                if "text" in msg:
                    text = msg["text"].get("body", "")
                elif "interactive" in msg:
                    inter = msg["interactive"]
                    if inter.get("type") == "button_reply":
                        text = inter["button_reply"].get("id", "")
                    elif inter.get("type") == "list_reply":
                        text = inter["list_reply"].get("id", "")
                if phone and text is not None:
                    yield pnid, phone, text


@app.get("/webhook")
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge", "")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(challenge, status=200, mimetype="text/plain")
    return Response("verification failed", status=403)


@app.post("/webhook")
def webhook_receive():
    data = request.get_json(force=True, silent=True) or {}
    for pnid, phone, text in extract_incoming(data):
        try:
            replies, business_id = process_message(
                phone, text, phone_number_id=pnid)
            if business_id is None:
                print(f"[webhook] unmapped phone_number_id={pnid}; ignored")
                continue
            biz = store.get_business(business_id)
            for reply in replies:
                send_to_whatsapp(phone, reply, biz)
                store.log_message(business_id, phone, "out")
        except Exception as exc:  # never 500 on Meta's retry loop
            print(f"[error] {phone}: {exc}")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Demo simulator + UI (zero Meta setup needed)
# ---------------------------------------------------------------------------

@app.post("/demo/message")
def demo_message():
    data = request.get_json(force=True, silent=True) or {}
    phone = str(data.get("phone", "demo-user"))
    text = str(data.get("text", ""))
    business_id = data.get("business_id")
    try:
        business_id = int(business_id) if business_id is not None else None
    except (TypeError, ValueError):
        business_id = None
    if business_id and not store.get_business(business_id):
        return jsonify({"error": "unknown business"}), 404
    replies, resolved = process_message(phone, text, business_id=business_id)
    return jsonify({"replies": replies, "business_id": resolved})


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "demo.html")


# ---------------------------------------------------------------------------
# Legacy admin views (default demo business; superseded by /app/ dashboard)
# ---------------------------------------------------------------------------

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — BanaoBot</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f4f1ea;margin:0;padding:24px;color:#222}}
h1{{font-size:22px}} table{{border-collapse:collapse;width:100%;background:#fff;
box-shadow:0 1px 4px rgba(0,0,0,.08)}} th,td{{text-align:left;padding:10px 12px;
border-bottom:1px solid #eee;font-size:14px}} th{{background:#2b2118;color:#f5e9d0}}
a{{color:#8a5a00}} .nav{{margin-bottom:16px}} .empty{{color:#888;padding:20px}}
</style></head><body>
<div class="nav"><a href="/app/">dashboard</a> · <a href="/admin">admin</a> ·
<a href="/admin/bookings">bookings</a> · <a href="/admin/alerts">alerts</a> ·
<a href="/">demo chat</a></div>
<h1>{title}</h1>{body}</body></html>"""


@app.get("/admin")
def admin_home():
    body = (f"<p>Bookings: <b>{store.count_bookings()}</b> · "
            f"Alerts: <b>{len(store.list_alerts())}</b></p>"
            "<p>Demo chat: <a href='/'>/</a> · "
            "Dashboard: <a href='/app/'>/app/</a></p>")
    return PAGE.format(title="Admin", body=body)


@app.get("/admin/bookings")
def admin_bookings():
    rows = store.list_bookings()
    if not rows:
        body = "<p class='empty'>No bookings yet — try the demo chat.</p>"
    else:
        trs = "".join(
            f"<tr><td><b>{r['id']}</b></td><td>{r['name']}</td>"
            f"<td>{r['phone']}</td><td>{r['date']}</td><td>{r['time']}</td>"
            f"<td>{r['party_size']}</td><td>{r['status']}</td></tr>"
            for r in rows
        )
        body = ("<table><tr><th>ID</th><th>Name</th><th>Phone</th><th>Date</th>"
                "<th>Time</th><th>Guests</th><th>Status</th></tr>" + trs + "</table>")
    return PAGE.format(title="Bookings", body=body)


@app.get("/admin/alerts")
def admin_alerts():
    rows = store.list_alerts()
    if not rows:
        body = "<p class='empty'>No handoff alerts yet.</p>"
    else:
        trs = "".join(
            f"<tr><td>{r['id']}</td><td>{r['phone']}</td>"
            f"<td>{r['reason']}</td><td>{'yes' if r['handled'] else 'no'}</td></tr>"
            for r in rows
        )
        body = ("<table><tr><th>#</th><th>Phone</th><th>Reason</th>"
                "<th>Handled</th></tr>" + trs + "</table>")
    return PAGE.format(title="Owner alerts", body=body)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"BanaoBot — DEMO_MODE={DEMO_MODE} — http://localhost:{port}/ "
          f"(dashboard: http://localhost:{port}/app/)")
    app.run(host="0.0.0.0", port=port, debug=False)
