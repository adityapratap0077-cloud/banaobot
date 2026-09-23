"""BanaoBot dashboard — prompt-first bot builder (owner-facing web UI).

Flask Blueprint named ``bp``. The parent app mounts it as::

    import dashboard
    app.register_blueprint(dashboard.bp, url_prefix="/app")

The product: sign in, write ONE prompt describing your bot, get a live AI
bot with a public chat link. No templates, no onboarding wizards, no menu
builders.

Hard rules this module follows:
  * NEVER imports server.py or storage.py directly (circular-import risk).
    The Store instance is pulled from ``current_app.config["store"]`` in
    every route.
  * Every bot-scoped route verifies the bot belongs to the logged-in user
    via ``own_bot_or_404`` — a 404 (never a 403, never a leak) when it
    does not.
  * Passwords are hashed with werkzeug; login state lives in Flask's
    signed ``session`` (secret key is set by the parent app).
  * Raw brain keys are never rendered into templates or logs.
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

import brain

bp = Blueprint("dashboard", __name__, template_folder="templates")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def store():
    """The Store instance the parent app stashed in app config."""
    return current_app.config["store"]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("dashboard.login"))
        return view(*args, **kwargs)
    return wrapped


def own_bot_or_404(bid):
    """Return the bot dict, or 404 unless it belongs to the logged-in user."""
    try:
        bid = int(bid)
    except (TypeError, ValueError):
        abort(404)
    bot = store().get_bot(bid, session.get("user_id"))
    if bot is None:
        abort(404)
    return bot


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
        flash("Welcome to BanaoBot! Describe your first bot. 🎉")
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
                flash("Welcome to BanaoBot! Describe your first bot. 🎉")
                return redirect(url_for("dashboard.index"))
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
# bot library
# ---------------------------------------------------------------------------

@bp.route("/")
@login_required
def index():
    st = store()
    bots = st.list_bots(session["user_id"])
    return render_template(
        "dash_index.html",
        bots=bots,
        has_key=st.has_user_brain_key(session["user_id"]),
        email=session.get("email"),
    )


# ---------------------------------------------------------------------------
# prompt builder
# ---------------------------------------------------------------------------

@bp.route("/bots/new", methods=["GET", "POST"])
@login_required
def bot_new():
    error = None
    name = ""
    prompt = ""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        prompt = request.form.get("prompt", "").strip()
        if len(prompt) < 20:
            error = ("Your prompt is too short — describe your bot in at "
                     "least a sentence or two so it knows what to do.")
        else:
            bid = store().create_bot(session["user_id"], name or "My bot",
                                     prompt)
            flash("Your bot is ready! 🎉")
            return redirect(url_for("dashboard.bot_detail", bid=bid))
    return render_template("dash_bot_new.html", error=error,
                           name=name, prompt=prompt)


# ---------------------------------------------------------------------------
# bot page: edit prompt, preview chat, share link, delete
# ---------------------------------------------------------------------------

@bp.route("/bots/<bid>", methods=["GET", "POST"])
@login_required
def bot_detail(bid):
    bot = own_bot_or_404(bid)
    st = store()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        prompt = request.form.get("prompt", "").strip()
        if len(prompt) < 20:
            flash("Your prompt is too short — give your bot a little more "
                  "to work with.")
        else:
            st.update_bot(bot["id"], session["user_id"],
                          name=name or bot["name"], prompt=prompt)
            flash("Bot updated. ✨")
        return redirect(url_for("dashboard.bot_detail", bid=bot["id"]))
    return render_template(
        "dash_bot_detail.html",
        bot=bot,
        has_key=st.has_user_brain_key(session["user_id"]),
        chat_url=url_for("public_chat", token=bot["share_token"],
                         _external=True),
        preview_chat_url=url_for("dashboard.bot_chat", bid=bot["id"]),
    )


@bp.route("/bots/<bid>/delete", methods=["POST"])
@login_required
def bot_delete(bid):
    bot = own_bot_or_404(bid)
    store().delete_bot(bot["id"], session["user_id"])
    flash("Bot deleted.")
    return redirect(url_for("dashboard.index"))


@bp.route("/bots/<bid>/chat", methods=["POST"])
@login_required
def bot_chat(bid):
    """Owner preview chat: JSON {message} -> {ok, reply}."""
    bot = own_bot_or_404(bid)
    body = _json_body()
    message = (body.get("message") or "").strip()
    if not message:
        return _err("Type a message first.")
    key = store().get_user_brain_key(session["user_id"])
    history = session.get("preview_history_%d" % bot["id"], [])
    reply = brain.chat_with_prompt(key, bot["name"], bot["prompt"],
                                   history, message)
    history = (history + [("user", message[:1500]),
                          ("model", reply[:1500])])[-16:]
    session["preview_history_%d" % bot["id"]] = history
    return jsonify({"ok": True, "reply": reply})


# ---------------------------------------------------------------------------
# settings: the owner's brain key
# ---------------------------------------------------------------------------

@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    st = store()
    uid = session["user_id"]
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "remove":
            st.delete_user_brain_key(uid)
            flash("Brain key removed. Your bots are asleep until you add "
                  "a new one.")
        elif action == "save":
            key = request.form.get("brain_key", "").strip()
            if len(key) < 10:
                flash("That doesn't look like a real API key — paste the "
                      "full key from Google AI Studio.")
            else:
                st.save_user_brain_key(uid, key)
                flash("Brain key saved. Your bots are awake! 🧠")
        return redirect(url_for("dashboard.settings"))
    return render_template(
        "dash_settings.html",
        has_key=st.has_user_brain_key(uid),
        email=session.get("email"),
    )
