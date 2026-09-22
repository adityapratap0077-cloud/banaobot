"""BanaoBot self-serve dashboard (owner-facing web UI).

Flask Blueprint named ``bp``. The parent app mounts it as::

    import dashboard
    app.register_blueprint(dashboard.bp, url_prefix="/app")

Hard rules this module follows:
  * NEVER imports server.py or storage.py directly (circular-import risk).
    The Store instance is pulled from ``current_app.config["store"]`` in
    every route.
  * Every business-scoped route verifies the business belongs to the
    logged-in user via ``own_business_or_404`` — a 404 (never a 403, never
    a leak) when it does not.
  * Passwords are hashed with werkzeug; login state lives in Flask's
    signed ``session`` (secret key is set by the parent app).
"""

import os
import re
import secrets
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, abort, current_app, flash, jsonify,
    redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import templates

bp = Blueprint("dashboard", __name__, template_folder="templates")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def store():
    """The Store instance the parent app stashed in app config."""
    return current_app.config["store"]


def _tpl(biz):
    """(template_id, template dict, resolved tone) for dashboard rendering."""
    tid = (biz or {}).get("template_id") or "restaurant"
    tpl = templates.get(tid)
    tone = ((biz or {}).get("tone") or "").strip() or tpl["default_tone"]
    return tid, tpl, tone


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("dashboard.login"))
        return view(*args, **kwargs)
    return wrapped


def own_business_or_404(bid):
    """Return the business dict, or 404 unless it belongs to the user."""
    biz = store().get_business(bid)
    if not biz or biz.get("user_id") != session.get("user_id"):
        abort(404)
    return biz


def _owner_row(sql, args):
    """Read-only SELECT on the store's connection for ownership lookups.

    Store has no public category/item/faq -> business getters, so we do a
    single read-only SELECT here (never a write) purely to enforce
    multi-tenant ownership before touching nested resources.
    """
    row = store()._conn.execute(sql, args).fetchone()
    return dict(row) if row else None


def _category_biz(cid):
    r = _owner_row("SELECT business_id FROM menu_categories WHERE id=?", (cid,))
    return r["business_id"] if r else None


def _item_biz(iid):
    r = _owner_row(
        "SELECT mc.business_id AS business_id FROM menu_items mi "
        "JOIN menu_categories mc ON mi.category_id = mc.id WHERE mi.id=?",
        (iid,),
    )
    return r["business_id"] if r else None


def _faq_biz(fid):
    r = _owner_row("SELECT business_id FROM faqs WHERE id=?", (fid,))
    return r["business_id"] if r else None


def _demo_mode():
    return os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")


def _json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Google sign-in (optional; enabled via GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET)
# ---------------------------------------------------------------------------

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _google_session(redirect_uri=None):
    """Build an OAuth2 session for Google, or None when sign-in is disabled.

    Disabled when GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are absent (the
    Google button is then hidden and the /oauth/google routes bounce back
    to login) or when authlib isn't installed.
    """
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    csec = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not cid or not csec:
        return None
    try:
        from authlib.integrations.requests_client import OAuth2Session
    except ImportError:
        return None
    return OAuth2Session(client_id=cid, client_secret=csec,
                         redirect_uri=redirect_uri,
                         scope="openid email profile")


def _google_enabled():
    return _google_session() is not None


def _unusable_password():
    """Password hash that can never validate (for Google-only accounts)."""
    return "!unusable-" + secrets.token_hex(16)


@bp.route("/oauth/google")
def google_login():
    redirect_uri = url_for("dashboard.google_callback", _external=True)
    gs = _google_session(redirect_uri)
    if gs is None:
        flash("Google sign-in isn't set up on this site yet.")
        return redirect(url_for("dashboard.login"))
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    auth_url, _ = gs.create_authorization_url(_GOOGLE_AUTH_URL, state=state)
    return redirect(auth_url)


@bp.route("/oauth/google/callback")
def google_callback():
    redirect_uri = url_for("dashboard.google_callback", _external=True)
    gs = _google_session(redirect_uri)
    if gs is None:
        return redirect(url_for("dashboard.login"))
    state = session.pop("oauth_state", None)
    if (not state or request.args.get("state") != state
            or "code" not in request.args):
        flash("Google sign-in didn't work — please try again.")
        return redirect(url_for("dashboard.login"))
    try:
        gs.fetch_token(_GOOGLE_TOKEN_URL, authorization_response=request.url)
        me = gs.get(_GOOGLE_USERINFO_URL).json()
    except Exception:
        flash("Google sign-in didn't work — please try again.")
        return redirect(url_for("dashboard.login"))
    sub = (me.get("sub") or "").strip()
    email = (me.get("email") or "").strip().lower()
    if not sub or not email or not me.get("email_verified"):
        flash("Google didn't share a verified email — try another way in.")
        return redirect(url_for("dashboard.login"))

    st = store()
    user = st.get_user_by_google_sub(sub)
    is_new = False
    if user is None:
        user = st.get_user_by_email(email)
        if user is None:
            uid = st.create_user(email, _unusable_password(), google_sub=sub)
            if uid is None:  # lost a race — fall back to the email row
                user = st.get_user_by_email(email)
            else:
                user = st.get_user(uid)
                is_new = True
        if user and not user.get("google_sub"):
            st.set_google_sub(user["id"], sub)
    if user is None:  # pragma: no cover - defensive
        flash("Couldn't create your account — please try again.")
        return redirect(url_for("dashboard.login"))

    session.clear()
    session["user_id"] = user["id"]
    session["email"] = user["email"]
    if is_new:
        flash("Welcome to BanaoBot! Let's set up your first business. 🎉")
        return redirect(url_for("dashboard.onboarding"))
    return redirect(url_for("dashboard.index"))


@bp.app_template_filter("ts")
def _fmt_ts(value):
    """Epoch seconds -> '23 Sep 2026, 02:10 PM'."""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError, OSError):
        return ""


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if "user_id" in session:
        return redirect(url_for("dashboard.index"))
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        pw2 = request.form.get("confirm", "")
        if not EMAIL_RE.match(email):
            error = "Please enter a valid email address."
        elif len(pw) < 6:
            error = "Password must be at least 6 characters."
        elif pw != pw2:
            error = "Passwords do not match."
        else:
            uid = store().create_user(email, generate_password_hash(pw))
            if uid is None:
                error = "That email is already registered. Try logging in."
            else:
                session.clear()
                session["user_id"] = uid
                session["email"] = email
                flash("Welcome to BanaoBot! Let's set up your first business. 🎉")
                return redirect(url_for("dashboard.onboarding"))
    return render_template(
        "dash_signup.html", error=error,
        google_enabled=_google_enabled())


@bp.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard.index"))
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        user = store().get_user_by_email(email)
        if not user or not check_password_hash(user["password_hash"], pw):
            error = "Invalid email or password."
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["email"] = user["email"]
            return redirect(url_for("dashboard.index"))
    return render_template(
        "dash_login.html", error=error,
        google_enabled=_google_enabled())


@bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out. See you soon! 👋")
    return redirect(url_for("dashboard.login"))


# ---------------------------------------------------------------------------
# dashboard home
# ---------------------------------------------------------------------------

@bp.route("/")
@login_required
def index():
    st = store()
    businesses = st.list_businesses(session["user_id"])
    cards = []
    for b in businesses:
        alerts = st.list_alerts(b["id"], limit=100)
        cards.append({
            "biz": b,
            "bookings": st.count_bookings(b["id"]),
            "alerts": sum(1 for a in alerts if not a.get("handled")),
            "messages": st.count_messages(b["id"]),
        })
    return render_template("dash_index.html", cards=cards)


# ---------------------------------------------------------------------------
# onboarding wizard (6 steps: 0 type -> 1 basics -> 2 catalog -> 3 details
# -> 4 faqs -> 5 welcome)
# ---------------------------------------------------------------------------

@bp.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    """Step 0 — "what best describes you?": the template picker.

    The legacy POST (name/language/owner_phone/taglines, no template) still
    creates a restaurant business and continues the wizard — kept working for
    API/back-compat; the picker form posts to /onboarding/basics instead.
    """
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        language = request.form.get("language", "en")
        owner_phone = request.form.get("owner_phone", "").strip()
        tagline_en = request.form.get("tagline_en", "").strip()
        tagline_hi = request.form.get("tagline_hi", "").strip()
        if language not in ("en", "hi"):
            language = "en"
        if not name:
            error = "Business name is required."
        elif not owner_phone:
            error = "Owner phone is required — handoff alerts go here."
        else:
            bid = store().create_business(
                session["user_id"], name,
                language=language, owner_phone=owner_phone,
                tagline_en=tagline_en, tagline_hi=tagline_hi,
                status="draft",
            )
            flash(f"“{name}” created! Now let's build the menu. 🍽️")
            return redirect(url_for("dashboard.onboarding_menu", bid=bid))
    return render_template("dash_onboarding_template.html",
                           templates=store().get_templates(), error=error)


@bp.route("/onboarding/basics", methods=["GET", "POST"])
@login_required
def onboarding_basics():
    """Step 1 — the basics: name, language, owner phone, tagline."""
    tid = request.values.get("template", "restaurant")
    if tid not in templates.ids():
        tid = "restaurant"
    tpl = templates.get(tid)
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        language = request.form.get("language", "en")
        owner_phone = request.form.get("owner_phone", "").strip()
        tagline_en = request.form.get("tagline_en", "").strip()
        tagline_hi = request.form.get("tagline_hi", "").strip()
        if language not in ("en", "hi"):
            language = "en"
        if not name:
            error = "Business name is required."
        elif not owner_phone:
            error = "Owner phone is required — handoff alerts go here."
        else:
            bid = store().create_business(
                session["user_id"], name, template_id=tid,
                language=language, owner_phone=owner_phone,
                tagline_en=tagline_en, tagline_hi=tagline_hi,
                status="draft",
            )
            flash(f"“{name}” created! Now add your {tpl['catalog']['en'].lower()}. {tpl['emoji']}")
            return redirect(url_for("dashboard.onboarding_menu", bid=bid))
    return render_template("dash_onboarding_basics.html", error=error,
                           tpl=tpl, tid=tid)


@bp.route("/onboarding/<int:bid>/menu")
@login_required
def onboarding_menu(bid):
    """Step 2 — catalog builder, then continue to details."""
    biz = own_business_or_404(bid)
    tid, tpl, tone = _tpl(biz)
    return render_template(
        "dash_onboarding_menu.html", biz=biz, bid=bid, tpl=tpl,
        continue_url=url_for("dashboard.onboarding_details", bid=bid),
    )


@bp.route("/onboarding/<int:bid>/details", methods=["GET", "POST"])
@login_required
def onboarding_details(bid):
    """Step 3 — hours, address, map link."""
    biz = own_business_or_404(bid)
    tid, tpl, tone = _tpl(biz)
    error = None
    if request.method == "POST":
        fields = {
            k: request.form.get(k, "").strip()
            for k in ("hours_open", "hours_close", "address_en",
                      "address_hi", "maps_link")
        }
        if not fields["hours_open"] or not fields["hours_close"]:
            error = "Opening and closing hours are required."
        else:
            store().update_business(bid, **fields)
            flash("Details saved! Now a few FAQs for the bot. 💬")
            return redirect(url_for("dashboard.onboarding_faqs", bid=bid))
    biz = store().get_business(bid)  # fresh values for the form
    return render_template("dash_onboarding_details.html",
                           biz=biz, bid=bid, tpl=tpl, error=error)


def _suggest_faq_key(keywords):
    """Derive a snake_case faq_key from the first keyword(s)."""
    slug = re.sub(r"[^a-z0-9]+", "_", (keywords or "").split(",")[0].lower())
    return slug.strip("_")[:40] or "faq"


@bp.route("/onboarding/<int:bid>/faqs", methods=["GET", "POST"])
@login_required
def onboarding_faqs(bid):
    """Step 4 — show existing FAQs + add form, then continue to welcome."""
    biz = own_business_or_404(bid)
    st = store()
    error = None
    if request.method == "POST":
        faq_key = request.form.get("faq_key", "").strip()
        keywords = request.form.get("keywords", "").strip()
        answer_en = request.form.get("answer_en", "").strip()
        answer_hi = request.form.get("answer_hi", "").strip()
        if not faq_key:
            faq_key = _suggest_faq_key(keywords)
        if not answer_en:
            error = "The English answer is required."
        else:
            st.add_faq(bid, faq_key, keywords, answer_en, answer_hi)
            flash("FAQ added! ✅")
            return redirect(url_for("dashboard.onboarding_faqs", bid=bid))
    faqs = st.list_faqs(bid)
    tid, tpl, tone = _tpl(biz)
    return render_template("dash_onboarding_faqs.html",
                           biz=biz, bid=bid, faqs=faqs, tpl=tpl, error=error)


@bp.route("/onboarding/<int:bid>/welcome", methods=["GET", "POST"])
@login_required
def onboarding_welcome(bid):
    """Step 5 — welcome messages; Finish flips status to 'active'."""
    biz = own_business_or_404(bid)
    tid, tpl, tone = _tpl(biz)
    # the business was created with the template's default welcome already
    default_en = (biz["welcome_en"]
                  or templates.render_welcome(tid, biz["name"],
                                              biz["tagline_en"], biz["tagline_hi"], "en"))
    default_hi = (biz["welcome_hi"]
                  or templates.render_welcome(tid, biz["name"],
                                              biz["tagline_en"], biz["tagline_hi"], "hi"))
    if request.method == "POST":
        welcome_en = request.form.get("welcome_en", "").strip() or default_en
        welcome_hi = request.form.get("welcome_hi", "").strip() or default_hi
        store().update_business(bid, welcome_en=welcome_en,
                                welcome_hi=welcome_hi, status="active")
        flash(f"“{biz['name']}” is live! Try the preview. 🚀")
        return redirect(url_for("dashboard.business_home", bid=bid))
    return render_template("dash_onboarding_welcome.html", biz=biz, bid=bid,
                           tpl=tpl, default_en=default_en, default_hi=default_hi)


# ---------------------------------------------------------------------------
# business home
# ---------------------------------------------------------------------------

@bp.route("/business/<int:bid>")
@login_required
def business_home(bid):
    st = store()
    biz = own_business_or_404(bid)
    alerts = st.list_alerts(bid, limit=50)
    tid, tpl, tone = _tpl(biz)
    return render_template(
        "dash_business.html",
        biz=biz, bid=bid, tpl=tpl, tid=tid, tone=tone,
        bookings=st.count_bookings(bid),
        bookings_list=st.list_bookings(bid, limit=30),
        alerts=alerts,
        unhandled=sum(1 for a in alerts if not a.get("handled")),
        messages=st.count_messages(bid),
    )


# ---------------------------------------------------------------------------
# menu builder (server-rendered page + JSON API for the vanilla-JS builder)
# ---------------------------------------------------------------------------

@bp.route("/business/<int:bid>/menu")
@login_required
def menu_page(bid):
    biz = own_business_or_404(bid)
    tid, tpl, tone = _tpl(biz)
    return render_template("dash_menu.html", biz=biz, bid=bid,
                           tpl=tpl, tid=tid, tone=tone)


@bp.get("/api/business/<int:bid>/menu")
@login_required
def api_menu(bid):
    own_business_or_404(bid)
    return jsonify({"ok": True, "categories": store().get_menu(bid)})


@bp.post("/api/business/<int:bid>/categories")
@login_required
def api_category_create(bid):
    own_business_or_404(bid)
    d = _json_body()
    name_en = (d.get("name_en") or "").strip()
    if not name_en:
        return _err("Category name is required.")
    emoji = (d.get("emoji") or "🍽️").strip() or "🍽️"
    cid = store().add_category(bid, name_en,
                               (d.get("name_hi") or "").strip(), emoji)
    return jsonify({"ok": True, "id": cid})


@bp.put("/api/categories/<int:cid>")
@login_required
def api_category_update(cid):
    cb = _category_biz(cid)
    if cb is None:
        return _err("Category not found.", 404)
    own_business_or_404(cb)
    d = _json_body()
    fields = {}
    if "name_en" in d:
        name_en = (d["name_en"] or "").strip()
        if not name_en:
            return _err("Category name cannot be empty.")
        fields["name_en"] = name_en
    if "name_hi" in d:
        fields["name_hi"] = (d["name_hi"] or "").strip()
    if "emoji" in d:
        fields["emoji"] = (d["emoji"] or "🍽️").strip() or "🍽️"
    if not fields:
        return _err("Nothing to update.")
    store().update_category(cid, **fields)
    return jsonify({"ok": True})


@bp.delete("/api/categories/<int:cid>")
@login_required
def api_category_delete(cid):
    cb = _category_biz(cid)
    if cb is None:
        return _err("Category not found.", 404)
    own_business_or_404(cb)
    store().delete_category(cid)  # also removes its items
    return jsonify({"ok": True})


@bp.post("/api/categories/<int:cid>/items")
@login_required
def api_item_create(cid):
    cb = _category_biz(cid)
    if cb is None:
        return _err("Category not found.", 404)
    own_business_or_404(cb)
    d = _json_body()
    name_en = (d.get("name_en") or "").strip()
    if not name_en:
        return _err("Item name is required.")
    try:
        price = int(d.get("price", 0))
    except (TypeError, ValueError):
        return _err("Price must be a whole number.")
    if price < 0:
        return _err("Price cannot be negative.")
    veg = d.get("veg", 1)
    veg = 1 if veg in (1, True, "1", "true", "veg") else 0
    iid = store().add_item(cid, name_en, (d.get("name_hi") or "").strip(),
                           price, veg, (d.get("description") or "").strip())
    return jsonify({"ok": True, "id": iid})


@bp.put("/api/items/<int:iid>")
@login_required
def api_item_update(iid):
    ib = _item_biz(iid)
    if ib is None:
        return _err("Item not found.", 404)
    own_business_or_404(ib)
    d = _json_body()
    fields = {}
    if "name_en" in d:
        name_en = (d["name_en"] or "").strip()
        if not name_en:
            return _err("Item name cannot be empty.")
        fields["name_en"] = name_en
    if "name_hi" in d:
        fields["name_hi"] = (d["name_hi"] or "").strip()
    if "price" in d:
        try:
            price = int(d["price"])
        except (TypeError, ValueError):
            return _err("Price must be a whole number.")
        if price < 0:
            return _err("Price cannot be negative.")
        fields["price"] = price
    if "veg" in d:
        fields["veg"] = 1 if d["veg"] in (1, True, "1", "true", "veg") else 0
    if "description" in d:
        fields["description"] = (d["description"] or "").strip()
    if not fields:
        return _err("Nothing to update.")
    store().update_item(iid, **fields)
    return jsonify({"ok": True})


@bp.delete("/api/items/<int:iid>")
@login_required
def api_item_delete(iid):
    ib = _item_biz(iid)
    if ib is None:
        return _err("Item not found.", 404)
    own_business_or_404(ib)
    store().delete_item(iid)
    return jsonify({"ok": True})


@bp.post("/api/business/<int:bid>/menu/reorder")
@login_required
def api_reorder_categories(bid):
    own_business_or_404(bid)
    ids = _json_body().get("categories") or []
    mine = {c["id"] for c in store().get_menu(bid)}
    if not all(i in mine for i in ids):
        return _err("Category list does not match this business.")
    store().reorder_categories(bid, [int(i) for i in ids])
    return jsonify({"ok": True})


@bp.post("/api/categories/<int:cid>/items/reorder")
@login_required
def api_reorder_items(cid):
    cb = _category_biz(cid)
    if cb is None:
        return _err("Category not found.", 404)
    own_business_or_404(cb)
    ids = _json_body().get("items") or []
    mine = set()
    for c in store().get_menu(cb):
        if c["id"] == cid:
            mine = {i["id"] for i in c["items"]}
    if not all(i in mine for i in ids):
        return _err("Item list does not match this category.")
    store().reorder_items(cid, [int(i) for i in ids])
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# FAQs (server-rendered editor)
# ---------------------------------------------------------------------------

@bp.route("/business/<int:bid>/faqs")
@login_required
def faqs_page(bid):
    biz = own_business_or_404(bid)
    return render_template("dash_faqs.html", biz=biz, bid=bid,
                           faqs=store().list_faqs(bid))


@bp.post("/business/<int:bid>/faqs/add")
@login_required
def faq_add(bid):
    own_business_or_404(bid)
    src = request.form.get("src", "manage")  # 'manage' or 'onboarding'
    faq_key = request.form.get("faq_key", "").strip()
    keywords = request.form.get("keywords", "").strip()
    answer_en = request.form.get("answer_en", "").strip()
    answer_hi = request.form.get("answer_hi", "").strip()
    if not faq_key:
        faq_key = _suggest_faq_key(keywords)
    if not answer_en:
        flash("The English answer is required.", "error")
    else:
        store().add_faq(bid, faq_key, keywords, answer_en, answer_hi)
        flash("FAQ added! ✅")
    dest = ("dashboard.onboarding_faqs" if src == "onboarding"
            else "dashboard.faqs_page")
    return redirect(url_for(dest, bid=bid))


@bp.post("/business/<int:bid>/faqs/<int:fid>/delete")
@login_required
def faq_delete(bid, fid):
    own_business_or_404(bid)
    if _faq_biz(fid) != bid:
        abort(404)
    store().delete_faq(fid)
    flash("FAQ deleted.")
    src = request.form.get("src", "manage")
    dest = ("dashboard.onboarding_faqs" if src == "onboarding"
            else "dashboard.faqs_page")
    return redirect(url_for(dest, bid=bid))


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

_SETTINGS_FIELDS = (
    "name", "tagline_en", "tagline_hi", "language",
    "hours_open", "hours_close", "last_booking",
    "address_en", "address_hi", "maps_link",
    "owner_phone", "welcome_en", "welcome_hi",
    "tone",
    "label_catalog_en", "label_catalog_hi",
    "label_book_en", "label_book_hi",
    "label_unit_en", "label_unit_hi",
)


@bp.route("/business/<int:bid>/settings", methods=["GET", "POST"])
@login_required
def settings(bid):
    biz = own_business_or_404(bid)
    tid, tpl, tone = _tpl(biz)
    error = None
    if request.method == "POST":
        fields = {k: request.form.get(k, "").strip() for k in _SETTINGS_FIELDS}
        fields["booking_enabled"] = 1 if request.form.get("booking_enabled") else 0
        if not fields["name"]:
            error = "Business name is required."
        elif fields["language"] not in ("en", "hi"):
            error = "Language must be en or hi."
        elif fields["tone"] not in ("", "friendly", "professional", "casual"):
            error = "Tone must be Friendly, Professional or Casual."
        else:
            store().update_business(bid, **fields)
            flash("Settings saved! ✅")
            return redirect(url_for("dashboard.settings", bid=bid))
        biz = {**biz, **fields}  # redisplay what they typed
    return render_template("dash_settings.html", biz=biz, bid=bid,
                           tpl=tpl, tid=tid, tone=tone, error=error)


# ---------------------------------------------------------------------------
# live preview (WhatsApp-style chat, zero Meta setup required)
# ---------------------------------------------------------------------------

@bp.route("/business/<int:bid>/preview")
@login_required
def preview(bid):
    """Phone-style chat UI that talks to the real engine via /demo/message."""
    biz = own_business_or_404(bid)
    tid, tpl, tone = _tpl(biz)
    return render_template("dash_preview.html", biz=biz, bid=bid,
                           tpl=tpl, tid=tid, tone=tone)


# ---------------------------------------------------------------------------
# WhatsApp connection (Meta Embedded Signup stub + demo simulate)
# ---------------------------------------------------------------------------

@bp.route("/business/<int:bid>/connect")
@login_required
def connect(bid):
    biz = own_business_or_404(bid)
    return render_template(
        "dash_connect.html", biz=biz, bid=bid,
        pnid=biz.get("whatsapp_phone_number_id") or "",
        token_set=bool(biz.get("whatsapp_token_enc")),
        demo=_demo_mode(),
    )


@bp.post("/business/<int:bid>/connect/exchange")
@login_required
def connect_exchange(bid):
    """Receive the Embedded-Signup `code` and (in production) exchange it
    for a system-user access token via Meta's Graph API.

    Stub behaviour: with DEMO_MODE=true we accept the stub code and mark
    the business connected with fake credentials so the whole flow can be
    clicked through today. Without DEMO_MODE we refuse with a clear
    message — the owner must finish their Meta app setup first.
    """
    own_business_or_404(bid)
    if not _demo_mode():
        return jsonify({
            "ok": False,
            "error": ("Meta app not configured yet. Create your Meta developer "
                      "app, fill META_APP_ID / META_CONFIG_ID on this page, "
                      "and see the checklist for the remaining steps."),
        }), 400
    data = _json_body()
    code = (data.get("code") or "stub").strip() or "stub"
    # In demo mode we also honour manually pasted credentials so the manual
    # form on the connect page stores exactly what the owner typed.
    pnid = (data.get("phone_number_id") or "").strip() or f"demo_pnid_{bid}"
    token = (data.get("token") or "").strip() or f"demo-token-{code[:12]}"
    store().set_whatsapp_credentials(bid, pnid, token)
    return jsonify({"ok": True, "demo": True,
                    "message": "Demo credentials stored — status is now 'connected'."})


@bp.post("/business/<int:bid>/connect/simulate")
@login_required
def connect_simulate(bid):
    """DEMO_MODE only: one-click fake connection for end-to-end testing."""
    if not _demo_mode():
        abort(403)
    own_business_or_404(bid)
    store().set_whatsapp_credentials(bid, f"demo_pnid_{bid}", "demo-token")
    flash("Simulated connection complete — status is now “connected”. 🔗")
    return redirect(url_for("dashboard.connect", bid=bid))


# ---------------------------------------------------------------------------
# Meta prerequisites checklist
# ---------------------------------------------------------------------------

@bp.route("/business/<int:bid>/checklist")
@login_required
def checklist(bid):
    biz = own_business_or_404(bid)
    return render_template("dash_checklist.html", biz=biz, bid=bid)
