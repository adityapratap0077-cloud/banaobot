"""SQLite persistence for BanaoBot — self-serve multi-tenant WhatsApp bot platform.

Tables:
  users            dashboard accounts (email + password hash)
  businesses       one row per client business (settings, WhatsApp credentials,
                   template_id + label overrides + tone)
  menu_categories  per-business catalog sections ("menu" for restaurants)
  menu_items       items inside a category
  faqs             per-business keyword -> answer (EN + Hindi)
  sessions         one row per (business, customer phone): language, state
                   machine state, JSON scratch data (booking draft, ...)
  bookings         confirmed bookings (business-scoped)
  owner_alerts     human-handoff requests + shop order enquiries (business-scoped)
  message_log      inbound/outbound message counts (business-scoped)

Multi-tenancy rule: every customer-facing row carries business_id, and the
engine only ever sees data for ONE business (see get_business_bundle).
No cross-business leakage by construction.

Templates (templates.py): each business has a template_id (restaurant, shop,
freelancer, clinic, teacher, creator). Template defaults are copied into the
business row at creation (button labels, unit noun, welcome copy, booking
on/off) so the owner can tweak them in Settings afterwards.

The engine (engine.py) never touches this module directly — server.py and
dashboard.py mediate: load business bundle -> load session -> engine ->
apply _events -> save session.

Old single-business databases (the original Bhoj House demo schema) are
detected on startup and rebuilt: that DB only ever held test data.

Database backend: SQLite by default (local dev + tests). When the
DATABASE_URL environment variable is set, the app uses PostgreSQL
instead (psycopg2) — this is how production survives Render's ephemeral
disk. All SQL is written with `?` placeholders; the _Cursor wrapper
translates them to `%s` for Postgres, and rows are normalized to plain
dicts on both drivers so the rest of the code never sees the driver.

Timestamps are generated Python-side as UTC ISO-8601 strings (never
`datetime('now')` / `now()` in SQL) so both dialects store identical
values. Booleans are INTEGER 0/1. Each operation commits on its own
connection — no pooling at this scale; connections are closed by the
caller via Store.close().
"""

import base64
import hashlib
import json
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # local dev / tests without the pg driver
    psycopg2 = None

import templates
import sitefetch
from content import FAQS, MENU, RESTAURANT, STR


def _utcnow():
    """UTC ISO-8601 timestamp, generated Python-side so SQLite and
    Postgres store the identical value."""
    return datetime.now(timezone.utc).isoformat()


def is_postgres():
    """True when DATABASE_URL is set — the app should use PostgreSQL."""
    return bool(os.environ.get("DATABASE_URL"))


def get_conn(path="bot.db"):
    """Open a database connection.

    Returns a psycopg2 connection when DATABASE_URL is set, otherwise a
    sqlite3 connection to `path`. SQLite connections get
    check_same_thread=False (Flask's dev server is threaded) and foreign
    keys enforced; Postgres enforces foreign keys by default.
    """
    if is_postgres():
        if psycopg2 is None:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg2 is not installed "
                "(pip install psycopg2-binary)")
        return psycopg2.connect(os.environ["DATABASE_URL"])
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def dialect_of(conn):
    """'postgres' or 'sqlite' for a connection from get_conn()."""
    return ("postgres"
            if type(conn).__module__.split(".")[0] == "psycopg2"
            else "sqlite")


def _translate_placeholders(sql):
    """Translate `?` placeholders to `%s` for psycopg2.

    A `?` inside a single-quoted string literal is left alone.
    """
    out = []
    in_str = False
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            if in_str and i + 1 < n and sql[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_str = not in_str
            out.append(ch)
            i += 1
            continue
        out.append("%s" if (ch == "?" and not in_str) else ch)
        i += 1
    return "".join(out)


class _Cursor:
    """Driver-agnostic cursor wrapper.

    execute() accepts `?` placeholders on both drivers (translated to
    `%s` for Postgres); fetchone()/fetchall() return plain dicts (or
    None) so callers never touch sqlite3.Row / RealDictRow.
    """

    def __init__(self, conn):
        self._conn = conn
        self._pg = dialect_of(conn) == "postgres"
        if self._pg:
            self._cur = conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            self._cur = conn.cursor()

    def execute(self, sql, params=()):
        if self._pg:
            sql = _translate_placeholders(sql)
        self._cur.execute(sql, params or ())
        return self

    def fetchone(self):
        return self._norm_row(self._cur.fetchone())

    def fetchall(self):
        return [self._norm_row(r) for r in self._cur.fetchall()]

    def _norm_row(self, row):
        """Normalize one row to a plain dict.

        sqlite3.Row and psycopg2's RealDictRow both convert via dict();
        a bare tuple (sqlite connection without the Row factory) is
        zipped with cursor.description column names.
        """
        if row is None:
            return None
        if isinstance(row, dict):
            return dict(row)
        try:
            return dict(row)
        except (TypeError, ValueError):
            pass
        cols = [d[0] for d in (self._cur.description or [])]
        if isinstance(row, (tuple, list)) and len(cols) == len(row):
            return dict(zip(cols, row))
        return row

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        if self._pg:
            raise RuntimeError(
                "lastrowid is SQLite-only; use insert_returning_id()")
        return self._cur.lastrowid

    def close(self):
        self._cur.close()


def execute(conn, sql, params=()):
    """Run SQL with `?` placeholders on either driver.

    Returns a _Cursor (rows come back as plain dicts). The caller owns
    committing/closing the connection; the cursor is closed when
    garbage-collected, or explicitly via cur.close().
    """
    cur = _Cursor(conn)
    cur.execute(sql, params)
    return cur


def insert_returning_id(conn, sql, params=()):
    """INSERT a row and return its new id.

    SQLite uses cursor.lastrowid; Postgres gets `RETURNING id`
    appended. `sql` must be a plain INSERT with `?` placeholders.
    """
    cur = _Cursor(conn)
    try:
        if cur._pg:
            cur.execute(sql + " RETURNING id", params)
            row = cur.fetchone()
            return row["id"] if row else None
        cur.execute(sql, params)
        return cur._cur.lastrowid
    finally:
        cur.close()


def init_db(path="bot.db"):
    """Create (or open) the database and return a ready Store.

    Uses Postgres when DATABASE_URL is set, else SQLite at `path`.
    `python -c "from storage import init_db; init_db()"` friendly.
    """
    return Store(path)


if psycopg2 is not None:
    _INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg2.IntegrityError)
else:
    _INTEGRITY_ERRORS = (sqlite3.IntegrityError,)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    google_sub    TEXT UNIQUE,
    created_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS user_brain_keys (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    key_enc    TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    prompt     TEXT NOT NULL,
    website_url TEXT,
    theme_color TEXT,
    share_token TEXT UNIQUE NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bots_user ON bots(user_id, created_at);
CREATE TABLE IF NOT EXISTS whatsapp_connections (
    user_id          INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    phone_number_id  TEXT NOT NULL,
    access_token_enc TEXT NOT NULL,
    app_secret_enc   TEXT,
    verify_token     TEXT UNIQUE NOT NULL,
    bot_id           INTEGER REFERENCES bots(id) ON DELETE SET NULL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wa_pnid ON whatsapp_connections(phone_number_id);
CREATE TABLE IF NOT EXISTS businesses (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                INTEGER NOT NULL DEFAULT 0,
    name                   TEXT NOT NULL,
    template_id            TEXT NOT NULL DEFAULT 'restaurant',
    booking_enabled        INTEGER NOT NULL DEFAULT 1,
    label_catalog_en       TEXT NOT NULL DEFAULT '',
    label_catalog_hi       TEXT NOT NULL DEFAULT '',
    label_book_en          TEXT NOT NULL DEFAULT '',
    label_book_hi          TEXT NOT NULL DEFAULT '',
    label_unit_en          TEXT NOT NULL DEFAULT '',
    label_unit_hi          TEXT NOT NULL DEFAULT '',
    tone                   TEXT NOT NULL DEFAULT '',
    tagline_en             TEXT NOT NULL DEFAULT '',
    tagline_hi             TEXT NOT NULL DEFAULT '',
    language               TEXT NOT NULL DEFAULT 'en',
    hours_open             TEXT NOT NULL DEFAULT '11:00',
    hours_close            TEXT NOT NULL DEFAULT '23:00',
    last_booking           TEXT NOT NULL DEFAULT '22:30',
    address_en             TEXT NOT NULL DEFAULT '',
    address_hi             TEXT NOT NULL DEFAULT '',
    maps_link              TEXT NOT NULL DEFAULT '',
    welcome_en             TEXT NOT NULL DEFAULT '',
    welcome_hi             TEXT NOT NULL DEFAULT '',
    owner_phone            TEXT NOT NULL DEFAULT '',
    whatsapp_phone_number_id TEXT UNIQUE,
    whatsapp_token_enc     TEXT,
    status                 TEXT NOT NULL DEFAULT 'draft',
    is_demo                INTEGER NOT NULL DEFAULT 0,
    created_at             INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS menu_categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name_en     TEXT NOT NULL,
    name_hi     TEXT NOT NULL DEFAULT '',
    emoji       TEXT NOT NULL DEFAULT '\U0001F37D\uFE0F',
    sort        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS menu_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES menu_categories(id) ON DELETE CASCADE,
    name_en     TEXT NOT NULL,
    name_hi     TEXT NOT NULL DEFAULT '',
    price       INTEGER NOT NULL DEFAULT 0,
    veg         INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    sort        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS faqs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    faq_key     TEXT NOT NULL,
    keywords    TEXT NOT NULL,
    answer_en   TEXT NOT NULL,
    answer_hi   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS templates (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    emoji           TEXT NOT NULL DEFAULT '',
    blurb           TEXT NOT NULL DEFAULT '',
    default_tone    TEXT NOT NULL DEFAULT 'friendly',
    booking_enabled INTEGER NOT NULL DEFAULT 1,
    show_veg        INTEGER NOT NULL DEFAULT 1,
    catalog_en      TEXT NOT NULL DEFAULT '',
    catalog_hi      TEXT NOT NULL DEFAULT '',
    item_plural_en  TEXT NOT NULL DEFAULT '',
    item_plural_hi  TEXT NOT NULL DEFAULT '',
    btn_catalog_en  TEXT NOT NULL DEFAULT '',
    btn_catalog_hi  TEXT NOT NULL DEFAULT '',
    btn_action_en   TEXT NOT NULL DEFAULT '',
    btn_action_hi   TEXT NOT NULL DEFAULT '',
    unit_en         TEXT NOT NULL DEFAULT '',
    unit_hi         TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions (
    business_id INTEGER NOT NULL,
    phone       TEXT NOT NULL,
    lang        TEXT NOT NULL DEFAULT 'en',
    state       TEXT NOT NULL DEFAULT 'idle',
    data        TEXT NOT NULL DEFAULT '{}',
    updated_at  INTEGER NOT NULL,
    PRIMARY KEY (business_id, phone)
);
CREATE TABLE IF NOT EXISTS bookings (
    id          TEXT PRIMARY KEY,
    business_id INTEGER NOT NULL,
    phone       TEXT NOT NULL,
    name        TEXT NOT NULL,
    date        TEXT NOT NULL,   -- YYYY-MM-DD
    time        TEXT NOT NULL,   -- HH:MM 24h
    party_size  INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'confirmed',
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS owner_alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    phone       TEXT NOT NULL,
    reason      TEXT NOT NULL,
    handled     INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS message_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    phone       TEXT NOT NULL,
    direction   TEXT NOT NULL,   -- 'in' | 'out'
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_biz ON bookings(business_id, created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_biz ON owner_alerts(business_id, created_at);
CREATE INDEX IF NOT EXISTS idx_msglog_biz ON message_log(business_id, created_at);
"""

# Tables from the original single-business demo schema. If we find these
# without the new `businesses` table, the DB is the old demo DB (test data
# only) and gets rebuilt.
_OLD_TABLES = ("sessions", "bookings", "owner_alerts", "faqs")


def _postgres_ddl():
    """The SCHEMA above translated for PostgreSQL.

    - `INTEGER PRIMARY KEY AUTOINCREMENT` -> `BIGSERIAL PRIMARY KEY`
      (Postgres has no AUTOINCREMENT keyword)
    - created_at/updated_at `INTEGER` -> `TEXT`: both dialects store the
      Python-generated UTC ISO-8601 strings from _utcnow()
    Everything else (IF NOT EXISTS, composite PKs, REFERENCES ... ON
    DELETE CASCADE, ON CONFLICT upserts) is valid in both dialects.
    """
    ddl = SCHEMA.replace(
        "INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    ddl = re.sub(r"\b(created_at|updated_at)\s+INTEGER NOT NULL",
                 r"\1 TEXT NOT NULL", ddl)
    return ddl


def _table_names(conn):
    """Names of all tables, on either driver."""
    if dialect_of(conn) == "postgres":
        rows = execute(
            conn,
            "SELECT tablename AS name FROM pg_tables "
            "WHERE schemaname='public'").fetchall()
    else:
        rows = execute(
            conn,
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def _exec_script(conn, script):
    """Run a multi-statement DDL script on either driver.

    sqlite3 has executescript(); for psycopg2 the script is split on `;`
    (the schema contains no semicolons inside string literals).
    """
    if dialect_of(conn) == "postgres":
        for stmt in script.split(";"):
            if stmt.strip():
                execute(conn, stmt)
    else:
        conn.executescript(script)


# ---------------------------------------------------------------------------
# Token "encryption"
# ---------------------------------------------------------------------------
# WhatsApp access tokens are stored per business. If the `cryptography`
# package is available we use Fernet; otherwise we fall back to
# XOR-with-secret + base64 (obfuscation, NOT real encryption).
# PRODUCTION NOTE: use a proper secret manager / KMS for these tokens.

def _dev_mode() -> bool:
    """Local dev only: BANAOBOT_DEV=1 or FLASK_DEBUG=1. Never set in production."""
    return os.environ.get("BANAOBOT_DEV") == "1" or os.environ.get("FLASK_DEBUG") == "1"


def _resolve_token_secret() -> bytes:
    """Resolve the token-encryption secret, failing CLOSED on misconfiguration.

    SECURITY: there is deliberately NO silent fallback to a hardcoded
    constant. BANAOBOT_SECRET is generated for production by render.yaml
    (generateValue: true), so a raise here only fires when someone deploys
    or runs without configuring the secret at all.
    """
    secret = os.environ.get("BANAOBOT_SECRET")
    if secret:
        return secret.encode()
    if _dev_mode():
        sys.stderr.write(
            "WARNING: BANAOBOT_SECRET is not set — using an insecure DEV-ONLY "
            "token key. NEVER use this in production.\n"
        )
        return b"banaobot-dev-secret"
    raise RuntimeError(
        "BANAOBOT_SECRET is not set. Refusing to encrypt/decrypt WhatsApp and "
        "Gemini tokens with an insecure fallback. Set BANAOBOT_SECRET "
        "(render.yaml generates it for the Render deploy), or export "
        "BANAOBOT_DEV=1 for local development."
    )


# Resolved once at startup (module import) so a misconfigured process fails
# fast instead of silently encrypting with a public fallback key.
_TOKEN_SECRET = _resolve_token_secret()


def _secret() -> bytes:
    return _TOKEN_SECRET


def encrypt_token(plaintext: str) -> str:
    if not plaintext:
        return ""
    try:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(hashlib.sha256(_secret()).digest())
        return "fernet1:" + Fernet(key).encrypt(plaintext.encode()).decode()
    except ImportError:
        pad = hashlib.sha256(_secret()).digest()
        raw = plaintext.encode()
        xored = bytes(b ^ pad[i % len(pad)] for i, b in enumerate(raw))
        return "xor1:" + base64.b64encode(xored).decode()


def decrypt_token(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    if ciphertext.startswith("fernet1:"):
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(hashlib.sha256(_secret()).digest())
        return Fernet(key).decrypt(ciphertext[len("fernet1:"):].encode()).decode()
    if ciphertext.startswith("xor1:"):
        pad = hashlib.sha256(_secret()).digest()
        raw = base64.b64decode(ciphertext[len("xor1:"):])
        return bytes(b ^ pad[i % len(pad)] for i, b in enumerate(raw)).decode()
    return ""  # unknown format: fail closed


class Store:
    def __init__(self, path="bot.db"):
        self.path = path
        # Postgres when DATABASE_URL is set (production on Render),
        # otherwise SQLite (local dev + tests). `path` is ignored in
        # Postgres mode.
        self._conn = get_conn(path)
        self._pg = dialect_of(self._conn) == "postgres"
        if self._pg:
            # Serialize schema init across gunicorn workers. On a fresh
            # database, concurrent CREATE TABLE (BIGSERIAL implicitly
            # creates sequences) from two workers races and the loser
            # dies with UniqueViolation on pg_class_relname_nsp_index —
            # which fails the whole Render deploy (build succeeds, the
            # new instances crash on boot). Session-level lock, not
            # xact-level: the migrate/seed helpers commit, which would
            # release an xact-level lock early. Released in `finally`,
            # so a crash can never wedge later boots.
            execute(
                self._conn,
                "SELECT pg_advisory_lock(hashtext('banaobot_schema_init'))",
            ).close()
        try:
            tables_before = _table_names(self._conn)
            _exec_script(self._conn,
                         _postgres_ddl() if self._pg else SCHEMA)
            self._conn.commit()
            self._maybe_migrate(tables_before)
            self._ensure_template_columns()
            self._seed_templates()
        finally:
            if self._pg:
                execute(
                    self._conn,
                    "SELECT pg_advisory_unlock("
                    "hashtext('banaobot_schema_init'))",
                ).close()
        self._default_biz_id = None

    def close(self):
        """Close the underlying connection. Idempotent."""
        try:
            self._conn.close()
        except Exception:
            pass

    def _reconnect(self):
        """Drop the current connection and open a fresh one.

        Called when the long-lived connection died. Safe to call on a
        healthy connection too (just churns it).
        """
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = get_conn(self.path)

    def _ensure_live(self):
        """Make sure the Postgres connection is usable, reconnecting if
        it died.

        Each gunicorn worker keeps one long-lived connection. Render's
        free Postgres can drop idle connections (deploys, restarts,
        network blips); without this check a dead connection makes every
        DB-touching request 500 until the next deploy — exactly the
        outage debugged on 2026-09-23 (signup/login/settings all 500d
        while the database itself was perfectly healthy).
        """
        if not self._pg:
            return
        try:
            # Clear any aborted-transaction state left by a previous
            # failure; a no-op on a healthy idle connection.
            self._conn.rollback()
        except Exception:
            pass
        try:
            if self._conn.closed:
                raise RuntimeError("connection closed")
            probe = self._conn.cursor()
            probe.execute("SELECT 1")
            probe.close()
        except Exception:
            self._reconnect()

    @contextmanager
    def _cur(self):
        self._ensure_live()
        cur = _Cursor(self._conn)
        try:
            yield cur
        except Exception:
            # Postgres aborts the whole transaction on any error — roll
            # back so the connection stays usable. Harmless on SQLite.
            self._conn.rollback()
            raise
        else:
            self._conn.commit()
        finally:
            cur.close()

    # -- schema migration ------------------------------------------------
    def _maybe_migrate(self, tables_before):
        fresh = "businesses" not in tables_before
        if fresh and tables_before & set(_OLD_TABLES):
            # Old single-business demo DB: its tables only ever held test
            # data, so rebuild them in the new multi-tenant shape.
            print("[store] old single-business schema detected — rebuilding "
                  "(old DB held test data only)")
            for t in _OLD_TABLES:
                execute(self._conn, f"DROP TABLE IF EXISTS {t}")
            self._conn.commit()
        self._migrate_users_google_sub()
        self._migrate_bots_website_columns()
        if fresh:
            self._seed_bhoj_house()
            self._seed_aditya()

    def _add_column_if_missing(self, table, column, col_ddl):
        """Portable ADD COLUMN: IF NOT EXISTS on Postgres, PRAGMA check
        + plain ADD COLUMN on SQLite."""
        if self._pg:
            execute(self._conn,
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                    f"{column} {col_ddl}")
        else:
            cols = {r["name"] for r in
                    execute(self._conn,
                            f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                execute(self._conn,
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_ddl}")
        self._conn.commit()

    def _migrate_bots_website_columns(self):
        """Add bots.website_url / bots.theme_color to DBs made before the
        build-from-website feature."""
        for col in ("website_url", "theme_color"):
            self._add_column_if_missing("bots", col, "TEXT")

    def _migrate_users_google_sub(self):
        """Add users.google_sub to DBs created before Google sign-in.

        Plain TEXT (not UNIQUE): SQLite cannot ADD a UNIQUE column via
        ALTER TABLE, and pre-existing DBs never had the constraint.
        Fresh DBs get UNIQUE from the schema itself.
        """
        self._add_column_if_missing("users", "google_sub", "TEXT")

    def _seed_aditya(self):
        """Seed Aditya Pratap's personal creator bot (business #2).

        Showcases the creator/personal template on a fresh deploy: same
        content as his local bot (catalog, FAQs, labels, tone).
        """
        now = _utcnow()
        tpl = templates.get("creator")
        welcome_en = ("Hey! *Aditya Pratap* here ✨\n"
                      "Hindi hip-hop artist & Creative Technologist 🎤 | Label: Adiroxx\n"
                      "\nCheck out what I've got 👇")
        welcome_hi = ("Hey! *Aditya Pratap* here ✨\n"
                      "हिंदी हिप-हॉप आर्टिस्ट और क्रिएटिव टेक्नोलॉजिस्ट 🎤\n"
                      "\nDekho mere paas kya hai 👇")
        categories = [
            {"name_en": "Music", "name_hi": "म्यूज़िक", "emoji": "🎵", "items": [
                {"name_en": "मुखौटे (Mukhaute)", "name_hi": "",
                 "description": 'Latest single — dark lyrical trap. Search '
                              '"Mukhaute Aditya Pratap" on YouTube & Spotify.'},
                {"name_en": "GUTTER GOSPEL", "name_hi": "",
                 "description": "20-track explicit debut album, ~55 min. "
                                "Full lyrics + streaming links on request."},
            ]},
            {"name_en": "Services", "name_hi": "सर्विसेज़", "emoji": "🎬", "items": [
                {"name_en": "ReelForge Promo Reel", "name_hi": "",
                 "description": "$40 single reel, $99 three-pack. 48h delivery, "
                                "2 revisions. DM @dyafterdark_ on Instagram to order."},
                {"name_en": "Custom Rap Verse / Feature", "name_hi": "",
                 "description": "Verses, hooks and features for your track. "
                                'Tap "Book a Call" and let\'s talk.'},
            ]},
        ]
        faqs = [
            ("collab", "collab, collaboration, sponsor, brand, partner",
             "🤝 *Collabs*\nI do! Share your brand + idea here and I'll get back "
             "with rates and timelines. For anything urgent, tap 'Book a Call'. ✨",
             "🤝 *कोलैब*\nHaan, karta hoon! Apna brand + idea yahin bhejo, rates "
             "aur timeline bata dunga. Urgent ho to 'Book a Call' dabao. ✨"),
            ("pricing", "price, pricing, cost, charge, rate, fees, कीमत",
             "💰 *Pricing*\nEverything's listed under Offerings with clear prices — "
             "no DMs asking 'price pls'. 😄 Tap below to browse.",
             "💰 *प्राइसिंग*\nSab kuch Offerings mein saaf price ke saath hai — "
             "'price pls' wale DM ki zaroorat nahi. 😄 Neeche dekho."),
            ("contact", "contact, email, reach, dm, संपर्क",
             "📩 *Contact*\nFastest way is right here on WhatsApp! For longer "
             "stuff, book a call and we'll talk properly. ✨",
             "📩 *संपर्क*\nSabse fast yahin WhatsApp par! Lambi baat ke liye "
             "call book kar lo. ✨"),
            ("who", "who are you, about, artist, bio, परिचय",
             "I'm Aditya Pratap — Hindi hip-hop artist and Creative Technologist "
             "from Gorakhpur, India. I make dark, lyrical trap (label: Adiroxx) "
             "and I build AI-powered web products.",
             "मैं आदित्य प्रताप हूँ — गोरखपुर का हिंदी हिप-हॉप आर्टिस्ट और "
             "क्रिएटिव टेक्नोलॉजिस्ट।"),
            ("listen", "listen, music, song, spotify, youtube, gaana, सुनो",
             'Search "Aditya Pratap" or "Mukhaute" on YouTube and Spotify. '
             "Latest drop: मुखौटे. Debut album: GUTTER GOSPEL (20 tracks).",
             'YouTube और Spotify पर "Aditya Pratap" या "Mukhaute" सर्च करो।'),
            ("gigs", "gig, show, perform, feature, collab, book you, शो",
             'For gigs, features and brand collabs — tap "📅 Book a Call" and '
             "pick a time. Let's make something loud. 🔊",
             'गिग, फीचर या ब्रांड कोलैब के लिए "📅 Book a Call" दबाओ और टाइम चुनो।'),
            ("reelforge", "reelforge, promo, video, reel price, वीडियो",
             "ReelForge = AI promo reels for your business. $40 single, $99 "
             "three-pack, delivered in 48h with 2 revisions. Order via "
             "Instagram DM: @dyafterdark_.",
             "ReelForge = तुम्हारे बिज़नेस के लिए AI प्रोमो रील। $40 सिंगल, "
             "$99 थ्री-पैक।"),
        ]
        with self._cur() as cur:
            biz_id = insert_returning_id(
                self._conn,
                """INSERT INTO businesses
                   (user_id, name, template_id, booking_enabled,
                    label_catalog_en, label_catalog_hi,
                    label_book_en, label_book_hi,
                    label_unit_en, label_unit_hi, tone,
                    tagline_en, tagline_hi, language,
                    hours_open, hours_close, last_booking,
                    address_en, address_hi, maps_link,
                    welcome_en, welcome_hi, owner_phone,
                    status, is_demo, created_at)
                   VALUES (0,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "Aditya Pratap", "creator", 1,
                    tpl["btn_catalog"]["en"], tpl["btn_catalog"]["hi"],
                    tpl["btn_action"]["en"], tpl["btn_action"]["hi"],
                    tpl["unit"]["en"], tpl["unit"]["hi"], "casual",
                    "Hindi hip-hop artist & Creative Technologist 🎤 | Label: Adiroxx",
                    "हिंदी हिप-हॉप आर्टिस्ट और क्रिएटिव टेक्नोलॉजिस्ट 🎤",
                    "en", "11:00", "23:00", "22:30", "", "", "",
                    welcome_en, welcome_hi, "",
                    "active", 0, now,
                ),
            )
            for s, cat in enumerate(categories):
                cat_id = insert_returning_id(
                    self._conn,
                    """INSERT INTO menu_categories
                       (business_id, name_en, name_hi, emoji, sort)
                       VALUES (?,?,?,?,?)""",
                    (biz_id, cat["name_en"], cat["name_hi"], cat["emoji"], s),
                )
                for i, it in enumerate(cat["items"]):
                    cur.execute(
                        """INSERT INTO menu_items
                           (category_id, name_en, name_hi, price, veg,
                            description, sort)
                           VALUES (?,?,?,?,?,?,?)""",
                        (cat_id, it["name_en"], it["name_hi"], 0, 1,
                         it["description"], i),
                    )
            for key, keywords, answer_en, answer_hi in faqs:
                cur.execute(
                    """INSERT INTO faqs
                       (business_id, faq_key, keywords, answer_en, answer_hi)
                       VALUES (?,?,?,?,?)""",
                    (biz_id, key, keywords, answer_en, answer_hi),
                )

    def _ensure_template_columns(self):
        """Add template/tone columns to pre-template databases, backfilled
        as restaurant (the only kind that existed before templates)."""
        ddl = {
            "template_id": "TEXT NOT NULL DEFAULT 'restaurant'",
            "booking_enabled": "INTEGER NOT NULL DEFAULT 1",
            "label_catalog_en": "TEXT NOT NULL DEFAULT ''",
            "label_catalog_hi": "TEXT NOT NULL DEFAULT ''",
            "label_book_en": "TEXT NOT NULL DEFAULT ''",
            "label_book_hi": "TEXT NOT NULL DEFAULT ''",
            "label_unit_en": "TEXT NOT NULL DEFAULT ''",
            "label_unit_hi": "TEXT NOT NULL DEFAULT ''",
            "tone": "TEXT NOT NULL DEFAULT ''",
            "brain_api_key_enc": "TEXT NOT NULL DEFAULT ''",
            "brain_enabled": "INTEGER NOT NULL DEFAULT 0",
        }
        for col, col_ddl in ddl.items():
            self._add_column_if_missing("businesses", col, col_ddl)
        tpl = templates.get("restaurant")
        with self._cur() as cur:
            cur.execute(
                "UPDATE businesses SET template_id='restaurant' "
                "WHERE template_id IS NULL OR template_id=''")
            backfill = {
                "label_catalog_en": tpl["btn_catalog"]["en"],
                "label_catalog_hi": tpl["btn_catalog"]["hi"],
                "label_book_en": tpl["btn_action"]["en"],
                "label_book_hi": tpl["btn_action"]["hi"],
                "label_unit_en": tpl["unit"]["en"],
                "label_unit_hi": tpl["unit"]["hi"],
            }
            for col, val in backfill.items():
                cur.execute(
                    f"UPDATE businesses SET {col}=? "
                    f"WHERE {col} IS NULL OR {col}=''",
                    (val,),
                )

    # -- templates -------------------------------------------------------
    def _seed_templates(self):
        """Sync the templates table from the templates.py registry.

        The table is the queryable record of available bot types (used by
        the onboarding picker); the registry remains the source of truth
        for long-form copy, FAQ seeds and booking confirmations. Sync is
        idempotent — re-running updates existing rows.
        """
        cols = ("id", "name", "emoji", "blurb", "default_tone",
                "booking_enabled", "show_veg",
                "catalog_en", "catalog_hi",
                "item_plural_en", "item_plural_hi",
                "btn_catalog_en", "btn_catalog_hi",
                "btn_action_en", "btn_action_hi",
                "unit_en", "unit_hi")
        with self._cur() as cur:
            for tid in templates.ids():
                t = templates.get(tid)
                cur.execute(
                    f"INSERT INTO templates ({', '.join(cols)}) "
                    f"VALUES ({', '.join('?' * len(cols))}) "
                    f"ON CONFLICT(id) DO UPDATE SET "
                    + ", ".join(f"{c}=excluded.{c}" for c in cols[1:]),
                    (tid, t["name"], t["emoji"], t["blurb"],
                     t["default_tone"], 1 if t["booking_enabled"] else 0,
                     1 if t["show_veg"] else 0,
                     t["catalog"]["en"], t["catalog"]["hi"],
                     t["item_plural"]["en"], t["item_plural"]["hi"],
                     t["btn_catalog"]["en"], t["btn_catalog"]["hi"],
                     t["btn_action"]["en"], t["btn_action"]["hi"],
                     t["unit"]["en"], t["unit"]["hi"]),
                )

    def get_templates(self):
        """All bot types for the onboarding picker, in registry order."""
        with self._cur() as cur:
            rows = cur.execute("SELECT * FROM templates").fetchall()
        by_id = {r["id"]: dict(r) for r in rows}
        return [by_id[tid] for tid in templates.ids() if tid in by_id]
    def _seed_bhoj_house(self):
        """Seed the original demo restaurant from content.py as business #1."""
        now = _utcnow()
        tpl = templates.get("restaurant")
        with self._cur() as cur:
            biz_id = insert_returning_id(
                self._conn,
                """INSERT INTO businesses
                   (user_id, name, template_id, booking_enabled,
                    label_catalog_en, label_catalog_hi,
                    label_book_en, label_book_hi,
                    label_unit_en, label_unit_hi, tone,
                    tagline_en, tagline_hi, language,
                    hours_open, hours_close, last_booking,
                    address_en, address_hi, maps_link,
                    welcome_en, welcome_hi, owner_phone,
                    status, is_demo, created_at)
                   VALUES (0,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    RESTAURANT["name"], "restaurant", 1,
                    tpl["btn_catalog"]["en"], tpl["btn_catalog"]["hi"],
                    tpl["btn_action"]["en"], tpl["btn_action"]["hi"],
                    tpl["unit"]["en"], tpl["unit"]["hi"], "",
                    RESTAURANT["tagline_en"], RESTAURANT["tagline_hi"],
                    "en",
                    RESTAURANT["hours_open"], RESTAURANT["hours_close"],
                    RESTAURANT["last_booking"],
                    RESTAURANT["address_en"], RESTAURANT["address_hi"],
                    RESTAURANT["maps_link"],
                    STR["welcome"]["en"], STR["welcome"]["hi"],
                    RESTAURANT["phone_display"],
                    "active", 1, now,
                ),
            )
            for s, cat in enumerate(MENU):
                cat_id = insert_returning_id(
                    self._conn,
                    """INSERT INTO menu_categories
                       (business_id, name_en, name_hi, emoji, sort)
                       VALUES (?,?,?,?,?)""",
                    (biz_id, cat["name_en"], cat["name_hi"], cat["emoji"], s),
                )
                for i, it in enumerate(cat["items"]):
                    cur.execute(
                        """INSERT INTO menu_items
                           (category_id, name_en, name_hi, price, veg,
                            description, sort)
                           VALUES (?,?,?,?,?,?,?)""",
                        (
                            cat_id, it["name_en"], it["name_hi"],
                            it["price"], 1 if it["veg"] else 0, "", i,
                        ),
                    )
            for faq in FAQS:
                cur.execute(
                    """INSERT INTO faqs
                       (business_id, faq_key, keywords, answer_en, answer_hi)
                       VALUES (?,?,?,?,?)""",
                    (
                        biz_id, faq["id"], ", ".join(faq["keywords"]),
                        faq["answer_en"], faq["answer_hi"],
                    ),
                )

    def get_default_business_id(self):
        """Id of the seeded Bhoj House demo business (None if deleted)."""
        if self._default_biz_id is None:
            with self._cur() as cur:
                row = cur.execute(
                    "SELECT id FROM businesses WHERE is_demo=1 LIMIT 1"
                ).fetchone()
                if row:
                    self._default_biz_id = row["id"]
                else:
                    row = cur.execute(
                        "SELECT id FROM businesses ORDER BY id LIMIT 1"
                    ).fetchone()
                    self._default_biz_id = row["id"] if row else None
        return self._default_biz_id

    def _biz(self, business_id):
        """Resolve None -> default demo business id."""
        return business_id if business_id is not None else self.get_default_business_id()

    # -- users -----------------------------------------------------------
    def create_user(self, email, password_hash, google_sub=None):
        with self._cur():
            try:
                return insert_returning_id(
                    self._conn,
                    "INSERT INTO users (email, password_hash, google_sub,"
                    " created_at) VALUES (?,?,?,?)",
                    (email.strip().lower(), password_hash, google_sub,
                     _utcnow()),
                )
            except _INTEGRITY_ERRORS:
                self._conn.rollback()  # reset aborted PG transaction
                return None  # email (or google_sub) already taken

    def get_user_by_email(self, email):
        with self._cur() as cur:
            row = cur.execute(
                "SELECT * FROM users WHERE email=?", (email.strip().lower(),)
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_google_sub(self, sub):
        with self._cur() as cur:
            row = cur.execute(
                "SELECT * FROM users WHERE google_sub=?", (sub,)
            ).fetchone()
        return dict(row) if row else None

    def set_google_sub(self, user_id, sub):
        """Link a Google account to an existing email/password user."""
        with self._cur() as cur:
            try:
                cur.execute(
                    "UPDATE users SET google_sub=? WHERE id=?", (sub, user_id)
                )
            except _INTEGRITY_ERRORS:
                self._conn.rollback()  # reset aborted PG transaction
                return False  # this Google account is linked elsewhere
            return cur.rowcount > 0

    def get_user(self, user_id):
        with self._cur() as cur:
            row = cur.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    # -- prompt-first bots -------------------------------------------------
    # One encrypted Gemini key per owner (shared by all their bots), and one
    # row per bot: name + the owner's prompt + an unguessable public share
    # token. All reads are owner-scoped — a different user never sees
    # another owner's bot.

    def save_user_brain_key(self, user_id, key_plain):
        """Store/replace the owner's encrypted Gemini key."""
        enc = encrypt_token((key_plain or "").strip())
        now = _utcnow()
        with self._cur() as cur:
            cur.execute(
                "INSERT INTO user_brain_keys (user_id, key_enc, updated_at)"
                " VALUES (?,?,?)"
                " ON CONFLICT(user_id) DO UPDATE SET key_enc=excluded.key_enc,"
                " updated_at=excluded.updated_at",
                (user_id, enc, now),
            )
        return True

    def get_user_brain_key(self, user_id):
        """Return the decrypted key, or "" when the owner has none."""
        with self._cur() as cur:
            row = cur.execute(
                "SELECT key_enc FROM user_brain_keys WHERE user_id=?",
                (user_id,),
            ).fetchone()
        if not row:
            return ""
        try:
            return decrypt_token(row["key_enc"]) or ""
        except Exception:
            return ""  # fail closed: corrupt ciphertext reads as no key

    def delete_user_brain_key(self, user_id):
        with self._cur() as cur:
            cur.execute(
                "DELETE FROM user_brain_keys WHERE user_id=?", (user_id,))
            return cur.rowcount > 0

    def has_user_brain_key(self, user_id):
        return bool(self.get_user_brain_key(user_id))

    @staticmethod
    def _new_share_token():
        import secrets as _secrets
        return _secrets.token_urlsafe(24)

    def create_bot(self, user_id, name, prompt, website_url=None,
                   theme_color=None):
        """Create a bot for this owner. Returns the bot id.

        website_url / theme_color come from the build-from-website flow;
        theme_color is strictly normalized to "#rrggbb" or stored as None.
        """
        name = (name or "").strip() or "My bot"
        token = self._new_share_token()
        website_url = (website_url or "").strip() or None
        theme_color = sitefetch.normalize_theme_hex(theme_color)
        with self._cur():
            for _ in range(5):  # astronomically unlikely to loop
                try:
                    return insert_returning_id(
                        self._conn,
                        "INSERT INTO bots (user_id, name, prompt,"
                        " website_url, theme_color, share_token,"
                        " created_at) VALUES (?,?,?,?,?,?,?)",
                        (user_id, name, (prompt or "").strip(),
                         website_url, theme_color, token, _utcnow()),
                    )
                except _INTEGRITY_ERRORS:
                    self._conn.rollback()  # reset aborted PG transaction
                    token = self._new_share_token()
            raise RuntimeError("could not mint a unique bot share token")

    def list_bots(self, user_id):
        with self._cur() as cur:
            rows = cur.execute(
                "SELECT * FROM bots WHERE user_id=? ORDER BY created_at DESC,"
                " id DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_bot(self, bot_id, user_id=None):
        """Fetch a bot; when user_id is given the bot must belong to them."""
        with self._cur() as cur:
            row = cur.execute(
                "SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
        if not row:
            return None
        bot = dict(row)
        if user_id is not None and bot["user_id"] != user_id:
            return None
        return bot

    def get_bot_by_token(self, token):
        """Public lookup: anyone with the unguessable token can chat."""
        with self._cur() as cur:
            row = cur.execute(
                "SELECT * FROM bots WHERE share_token=?", (token or "",)
            ).fetchone()
        return dict(row) if row else None

    def update_bot(self, bot_id, user_id, name=None, prompt=None,
                   website_url=None, theme_color=None):
        """Owner-scoped update. Returns True when the bot exists and the
        owner matches."""
        bot = self.get_bot(bot_id, user_id)
        if bot is None:
            return False
        fields = {}
        if name is not None:
            fields["name"] = (name or "").strip() or bot["name"]
        if prompt is not None:
            fields["prompt"] = (prompt or "").strip()
        if website_url is not None:
            fields["website_url"] = (website_url or "").strip() or None
        if theme_color is not None:
            fields["theme_color"] = sitefetch.normalize_theme_hex(
                theme_color)
        if not fields:
            return True
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._cur() as cur:
            cur.execute(
                f"UPDATE bots SET {sets} WHERE id=? AND user_id=?",
                (*fields.values(), bot_id, user_id),
            )
            return cur.rowcount > 0

    def delete_bot(self, bot_id, user_id):
        """Owner-scoped delete. Returns True when a row was removed."""
        with self._cur() as cur:
            cur.execute(
                "DELETE FROM bots WHERE id=? AND user_id=?",
                (bot_id, user_id),
            )
            return cur.rowcount > 0

    # -- WhatsApp Cloud API connections ------------------------------------
    # One connection per owner: their Meta phone_number_id + encrypted
    # access token, a generated verify_token for Meta's webhook handshake,
    # the prompt-first bot that answers incoming messages, and an
    # enabled flag. Raw tokens are never exposed by the getters used for
    # display — they return masked status only.

    @staticmethod
    def _new_verify_token():
        import secrets as _secrets
        return _secrets.token_urlsafe(24)

    def save_whatsapp_connection(self, user_id, phone_number_id,
                                 access_token_plain, app_secret_plain=""):
        """Create or replace the owner's WhatsApp connection.

        The verify_token survives updates (Meta's subscription keeps
        working); it is only generated for a brand-new connection.
        """
        pnid = (phone_number_id or "").strip()
        token = (access_token_plain or "").strip()
        if not pnid or len(token) < 10:
            raise ValueError("phone_number_id and a real access token "
                             "are required")
        secret = (app_secret_plain or "").strip()
        existing = self.get_whatsapp_connection(user_id)
        verify = (existing["verify_token"] if existing
                  else self._new_verify_token())
        now = _utcnow()
        with self._cur() as cur:
            cur.execute(
                "INSERT INTO whatsapp_connections "
                "(user_id, phone_number_id, access_token_enc, app_secret_enc,"
                " verify_token, bot_id, enabled, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                " phone_number_id=excluded.phone_number_id,"
                " access_token_enc=excluded.access_token_enc,"
                " app_secret_enc=excluded.app_secret_enc",
                (user_id, pnid, encrypt_token(token),
                 encrypt_token(secret) if secret else None,
                 verify,
                 existing["bot_id"] if existing else None,
                 existing["enabled"] if existing else 1,
                 now),
            )
        return True

    def _wa_row_to_dict(self, row, include_secrets=False):
        conn = dict(row)
        conn["enabled"] = bool(conn["enabled"])
        if include_secrets:
            try:
                conn["access_token"] = decrypt_token(conn["access_token_enc"] or "")
            except Exception:
                conn["access_token"] = ""
            try:
                conn["app_secret"] = decrypt_token(conn["app_secret_enc"] or "")
            except Exception:
                conn["app_secret"] = ""
        else:
            conn.pop("access_token_enc", None)
            conn.pop("app_secret_enc", None)
        return conn

    def get_whatsapp_connection(self, user_id):
        """Owner's connection without raw secrets (safe for templates)."""
        with self._cur() as cur:
            row = cur.execute(
                "SELECT * FROM whatsapp_connections WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return self._wa_row_to_dict(row) if row else None

    def _get_whatsapp_connection_secrets(self, user_id):
        """Internal: connection WITH decrypted secrets for sending."""
        with self._cur() as cur:
            row = cur.execute(
                "SELECT * FROM whatsapp_connections WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return self._wa_row_to_dict(row, include_secrets=True) if row else None

    def get_whatsapp_connection_by_pnid(self, phone_number_id):
        """Webhook lookup: which owner owns this Meta phone_number_id."""
        with self._cur() as cur:
            row = cur.execute(
                "SELECT * FROM whatsapp_connections WHERE phone_number_id=?",
                (phone_number_id or "",),
            ).fetchone()
        return self._wa_row_to_dict(row, include_secrets=True) if row else None

    def get_whatsapp_connection_by_verify_token(self, verify_token):
        """Meta handshake lookup. Secrets not needed here."""
        with self._cur() as cur:
            row = cur.execute(
                "SELECT * FROM whatsapp_connections WHERE verify_token=?",
                (verify_token or "",),
            ).fetchone()
        return self._wa_row_to_dict(row) if row else None

    def set_whatsapp_bot(self, user_id, bot_id):
        """Link a bot to the connection. bot_id must belong to the owner
        (or None to unlink). Returns True on success."""
        if bot_id is not None:
            bot = self.get_bot(bot_id, user_id)
            if bot is None:
                return False
        with self._cur() as cur:
            cur.execute(
                "UPDATE whatsapp_connections SET bot_id=? WHERE user_id=?",
                (bot_id, user_id),
            )
            return cur.rowcount > 0

    def set_whatsapp_enabled(self, user_id, enabled):
        with self._cur() as cur:
            cur.execute(
                "UPDATE whatsapp_connections SET enabled=? WHERE user_id=?",
                (1 if enabled else 0, user_id),
            )
            return cur.rowcount > 0

    def delete_whatsapp_connection(self, user_id):
        with self._cur() as cur:
            cur.execute(
                "DELETE FROM whatsapp_connections WHERE user_id=?",
                (user_id,),
            )
            return cur.rowcount > 0

    # -- businesses ------------------------------------------------------
    _BIZ_FIELDS = (
        "name", "tagline_en", "tagline_hi", "language",
        "hours_open", "hours_close", "last_booking",
        "address_en", "address_hi", "maps_link",
        "welcome_en", "welcome_hi", "owner_phone", "status",
        "booking_enabled",
        "label_catalog_en", "label_catalog_hi",
        "label_book_en", "label_book_hi",
        "label_unit_en", "label_unit_hi",
        "tone",
        "brain_enabled",
    )

    def create_business(self, user_id, name, template_id="restaurant", **kwargs):
        """Create a business, copying the template's defaults (button labels,
        unit noun, welcome copy, booking on/off, starter FAQs) into the row
        so the owner can tweak them afterwards. Explicit kwargs win."""
        tid = template_id if template_id in templates.ids() else "restaurant"
        tpl = templates.get(tid)
        name = name.strip()
        fields = {
            "name": name,
            "user_id": user_id,
            "template_id": tid,
            "created_at": _utcnow(),
            # overridable template defaults:
            "booking_enabled": 1 if tpl["booking_enabled"] else 0,
            "label_catalog_en": tpl["btn_catalog"]["en"],
            "label_catalog_hi": tpl["btn_catalog"]["hi"],
            "label_book_en": tpl["btn_action"]["en"],
            "label_book_hi": tpl["btn_action"]["hi"],
            "label_unit_en": tpl["unit"]["en"],
            "label_unit_hi": tpl["unit"]["hi"],
            "tone": "",
        }
        # welcome copy: explicit non-empty value wins, else template default
        for wk, lang in (("welcome_en", "en"), ("welcome_hi", "hi")):
            if kwargs.get(wk):
                fields[wk] = kwargs[wk]
            else:
                fields[wk] = templates.render_welcome(
                    tid, name, kwargs.get("tagline_en") or "",
                    kwargs.get("tagline_hi") or "", lang)
        for k in self._BIZ_FIELDS:
            if k in ("welcome_en", "welcome_hi"):
                continue  # handled above
            if k in kwargs and kwargs[k] is not None:
                v = kwargs[k]
                if k == "booking_enabled":
                    v = 1 if v else 0
                fields[k] = v
        cols = ", ".join(fields)
        with self._cur():
            bid = insert_returning_id(
                self._conn,
                f"INSERT INTO businesses ({cols})"
                f" VALUES ({','.join('?'*len(fields))})",
                tuple(fields.values()),
            )
        # starter FAQs for the template (owner can edit/delete them later)
        for faq in tpl["faq_seeds"]:
            self.add_faq(bid, faq["id"], faq["keywords"],
                         faq["answer_en"], faq["answer_hi"])
        return bid

    def get_business(self, business_id):
        with self._cur() as cur:
            row = cur.execute(
                "SELECT * FROM businesses WHERE id=?", (business_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_businesses(self, user_id):
        with self._cur() as cur:
            rows = cur.execute(
                "SELECT * FROM businesses WHERE user_id=? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_business_by_phone_number_id(self, pnid):
        if not pnid:
            return None
        with self._cur() as cur:
            row = cur.execute(
                "SELECT * FROM businesses WHERE whatsapp_phone_number_id=?", (pnid,)
            ).fetchone()
        return dict(row) if row else None

    def update_business(self, business_id, **fields):
        fields = {k: v for k, v in fields.items() if k in self._BIZ_FIELDS}
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._cur() as cur:
            cur.execute(
                f"UPDATE businesses SET {sets} WHERE id=?",
                (*fields.values(), business_id),
            )

    def set_whatsapp_credentials(self, business_id, phone_number_id, token_plain):
        with self._cur() as cur:
            cur.execute(
                """UPDATE businesses
                   SET whatsapp_phone_number_id=?, whatsapp_token_enc=?, status='connected'
                   WHERE id=?""",
                (phone_number_id, encrypt_token(token_plain), business_id),
            )

    def get_whatsapp_token(self, business_id):
        biz = self.get_business(business_id)
        if not biz or not biz.get("whatsapp_token_enc"):
            return ""
        return decrypt_token(biz["whatsapp_token_enc"])

    # -- brain (Gemini API key, encrypted at rest like WhatsApp tokens) -----
    def set_brain_key(self, business_id, key_plain):
        with self._cur() as cur:
            cur.execute(
                "UPDATE businesses SET brain_api_key_enc=? WHERE id=?",
                (encrypt_token(key_plain), business_id),
            )

    def get_brain_key(self, business_id):
        biz = self.get_business(business_id)
        if not biz or not biz.get("brain_api_key_enc"):
            return ""
        return decrypt_token(biz["brain_api_key_enc"])

    def clear_brain_key(self, business_id):
        with self._cur() as cur:
            cur.execute(
                "UPDATE businesses SET brain_api_key_enc='', brain_enabled=0 "
                "WHERE id=?", (business_id,),
            )

    # -- menu ------------------------------------------------------------
    def add_category(self, business_id, name_en, name_hi="", emoji="\U0001F37D\uFE0F"):
        with self._cur() as cur:
            row = cur.execute(
                "SELECT COALESCE(MAX(sort),-1)+1 AS s FROM menu_categories"
                " WHERE business_id=?", (business_id,)
            ).fetchone()
            return insert_returning_id(
                self._conn,
                """INSERT INTO menu_categories
                   (business_id, name_en, name_hi, emoji, sort)
                   VALUES (?,?,?,?,?)""",
                (business_id, name_en.strip(), name_hi.strip(), emoji,
                 row["s"]),
            )

    def update_category(self, cat_id, **fields):
        allowed = {"name_en", "name_hi", "emoji", "sort"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        with self._cur() as cur:
            cur.execute(
                f"UPDATE menu_categories SET {','.join(f'{k}=?' for k in fields)}"
                " WHERE id=?",
                (*fields.values(), cat_id),
            )

    def delete_category(self, cat_id):
        with self._cur() as cur:
            cur.execute("DELETE FROM menu_items WHERE category_id=?", (cat_id,))
            cur.execute("DELETE FROM menu_categories WHERE id=?", (cat_id,))

    def reorder_categories(self, business_id, ordered_ids):
        with self._cur() as cur:
            for s, cid in enumerate(ordered_ids):
                cur.execute(
                    "UPDATE menu_categories SET sort=? WHERE id=? AND business_id=?",
                    (s, cid, business_id),
                )

    def add_item(self, category_id, name_en, name_hi="", price=0, veg=1,
                 description=""):
        with self._cur() as cur:
            row = cur.execute(
                "SELECT COALESCE(MAX(sort),-1)+1 AS s FROM menu_items"
                " WHERE category_id=?", (category_id,)
            ).fetchone()
            return insert_returning_id(
                self._conn,
                """INSERT INTO menu_items
                   (category_id, name_en, name_hi, price, veg, description, sort)
                   VALUES (?,?,?,?,?,?,?)""",
                (category_id, name_en.strip(), name_hi.strip(), int(price),
                 1 if veg else 0, description.strip(), row["s"]),
            )

    def update_item(self, item_id, **fields):
        allowed = {"name_en", "name_hi", "price", "veg", "description", "sort"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        if "veg" in fields:
            fields["veg"] = 1 if fields["veg"] else 0
        if "price" in fields:
            fields["price"] = int(fields["price"])
        with self._cur() as cur:
            cur.execute(
                f"UPDATE menu_items SET {','.join(f'{k}=?' for k in fields)}"
                " WHERE id=?",
                (*fields.values(), item_id),
            )

    def delete_item(self, item_id):
        with self._cur() as cur:
            cur.execute("DELETE FROM menu_items WHERE id=?", (item_id,))

    def reorder_items(self, category_id, ordered_ids):
        with self._cur() as cur:
            for s, iid in enumerate(ordered_ids):
                cur.execute(
                    "UPDATE menu_items SET sort=? WHERE id=? AND category_id=?",
                    (s, iid, category_id),
                )

    def get_menu(self, business_id):
        """Full menu: categories ordered, each with its items ordered."""
        with self._cur() as cur:
            cats = cur.execute(
                "SELECT * FROM menu_categories WHERE business_id=?"
                " ORDER BY sort, id", (business_id,)
            ).fetchall()
            out = []
            for c in cats:
                items = cur.execute(
                    "SELECT * FROM menu_items WHERE category_id=?"
                    " ORDER BY sort, id", (c["id"],)
                ).fetchall()
                d = dict(c)
                d["items"] = [dict(i) for i in items]
                out.append(d)
        return out

    # -- faqs ------------------------------------------------------------
    def add_faq(self, business_id, faq_key, keywords, answer_en, answer_hi):
        if isinstance(keywords, (list, tuple)):
            keywords = ", ".join(keywords)
        with self._cur():
            return insert_returning_id(
                self._conn,
                """INSERT INTO faqs
                   (business_id, faq_key, keywords, answer_en, answer_hi)
                   VALUES (?,?,?,?,?)""",
                (business_id, faq_key.strip(), keywords, answer_en,
                 answer_hi),
            )

    def update_faq(self, faq_id, **fields):
        allowed = {"faq_key", "keywords", "answer_en", "answer_hi"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if isinstance(fields.get("keywords"), (list, tuple)):
            fields["keywords"] = ", ".join(fields["keywords"])
        if not fields:
            return
        with self._cur() as cur:
            cur.execute(
                f"UPDATE faqs SET {','.join(f'{k}=?' for k in fields)} WHERE id=?",
                (*fields.values(), faq_id),
            )

    def delete_faq(self, faq_id):
        with self._cur() as cur:
            cur.execute("DELETE FROM faqs WHERE id=?", (faq_id,))

    def list_faqs(self, business_id):
        with self._cur() as cur:
            rows = cur.execute(
                "SELECT * FROM faqs WHERE business_id=? ORDER BY id", (business_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -- business bundle for the engine ----------------------------------
    @staticmethod
    def _booking_prefix(name):
        words = [w for w in (name or "").replace("&", " ").split() if w]
        letters = "".join(w[0] for w in words[:2]).upper()
        return (letters or "BX")[:4]

    def get_business_bundle(self, business_id):
        """Everything engine.py needs for ONE business. No cross-biz data."""
        biz = self.get_business(business_id)
        if not biz:
            return None
        menu = []
        for c in self.get_menu(business_id):
            menu.append({
                "id": str(c["id"]),
                "name": {"en": c["name_en"], "hi": c["name_hi"] or c["name_en"]},
                "emoji": c["emoji"],
                "items": [
                    {
                        "name": {"en": i["name_en"],
                                 "hi": i["name_hi"] or i["name_en"]},
                        "price": i["price"],
                        "veg": bool(i["veg"]),
                        "description": i["description"],
                    }
                    for i in c["items"]
                ],
            })
        faqs = [
            {
                "id": f["faq_key"],
                "keywords": [k.strip() for k in f["keywords"].split(",") if k.strip()],
                "answer": {"en": f["answer_en"], "hi": f["answer_hi"]},
            }
            for f in self.list_faqs(business_id)
        ]
        return {
            "id": biz["id"],
            "name": biz["name"],
            "prefix": self._booking_prefix(biz["name"]),
            "tagline": {"en": biz["tagline_en"], "hi": biz["tagline_hi"]},
            "owner_phone": biz["owner_phone"],
            "address": {"en": biz["address_en"], "hi": biz["address_hi"]},
            "maps_link": biz["maps_link"],
            "hours_open": biz["hours_open"] or "11:00",
            "hours_close": biz["hours_close"] or "23:00",
            "last_booking": biz["last_booking"] or "22:30",
            "language": biz["language"] or "en",
            "welcome": {"en": biz["welcome_en"], "hi": biz["welcome_hi"]},
            "tone": (biz.get("tone") or "").strip()
                    or templates.get(biz.get("template_id") or "restaurant")["default_tone"],
            "tpl": self._build_tpl(biz),
            "menu": menu,
            "faqs": faqs,
            "brain_enabled": bool(biz.get("brain_enabled")),
            "brain_key": (self.get_brain_key(business_id)
                          if biz.get("brain_enabled") else ""),
        }

    # -- template merge helper ---------------------------------------------
    @staticmethod
    def _build_tpl(biz):
        """Merge template defaults with the business's label overrides.

        Button labels / unit noun come from the row (owner-editable; empty
        means "use the template default"). Structural strings (headings,
        confirmations, hours note) come straight from the template.
        """
        tid = biz.get("template_id") or "restaurant"
        tpl = templates.get(tid)

        def pick(col, default):
            v = (biz.get(col) or "").strip()
            return v if v else default

        return {
            "id": tid,
            "name": tpl["name"],
            "emoji": tpl["emoji"],
            "booking_enabled": bool(biz.get("booking_enabled", 1)),
            "catalog": tpl["catalog"],
            "item_plural": tpl["item_plural"],
            "btn_catalog": {
                "en": pick("label_catalog_en", tpl["btn_catalog"]["en"]),
                "hi": pick("label_catalog_hi", tpl["btn_catalog"]["hi"]),
            },
            "btn_action": {
                "en": pick("label_book_en", tpl["btn_action"]["en"]),
                "hi": pick("label_book_hi", tpl["btn_action"]["hi"]),
            },
            "unit": {
                "en": pick("label_unit_en", tpl["unit"]["en"]),
                "hi": pick("label_unit_hi", tpl["unit"]["hi"]),
            },
            "unit_word": tpl["unit_word"],
            "catalog_heading": tpl["catalog_heading"],
            "show_veg": tpl["show_veg"],
            "booked_ok": tpl["booked_ok"],
            "hours_note": tpl["hours_note"],
            "cat_examples": tpl["cat_examples"],
            "item_example": tpl["item_example"],
        }

    # -- sessions (business-scoped) --------------------------------------
    def get_session(self, phone, business_id=None):
        """Return the session dict for a phone number, or None if new.

        business_id=None resolves to the seeded demo business, which keeps
        the original single-business behaviour working unchanged.
        """
        business_id = self._biz(business_id)
        with self._cur() as cur:
            row = cur.execute(
                "SELECT lang, state, data FROM sessions"
                " WHERE business_id=? AND phone=?", (business_id, phone)
            ).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row["data"])
        except (ValueError, TypeError):
            data = {}
        session = {"lang": row["lang"], "state": row["state"], "data": data}
        # top-level session keys stashed under reserved names at save time
        for k in ("lang_locked", "hist"):
            sk = "_sess_" + k
            if isinstance(data, dict) and sk in data:
                session[k] = data.pop(sk)
        return session

    def save_session(self, phone, session, business_id=None):
        """Persist a session dict. Strips the transient '_events' key."""
        business_id = self._biz(business_id)
        session = dict(session or {})
        session.pop("_events", None)
        data_dict = dict(session.get("data", {}) or {})
        # stash top-level session keys so they survive the round-trip
        for k in ("lang_locked", "hist"):
            if k in session:
                data_dict["_sess_" + k] = session[k]
        data = json.dumps(data_dict, ensure_ascii=False)
        with self._cur() as cur:
            cur.execute(
                """INSERT INTO sessions
                   (business_id, phone, lang, state, data, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(business_id, phone) DO UPDATE SET
                     lang=excluded.lang, state=excluded.state,
                     data=excluded.data, updated_at=excluded.updated_at""",
                (
                    business_id, phone,
                    session.get("lang", "en"),
                    session.get("state", "idle"),
                    data,
                    _utcnow(),
                ),
            )

    # -- bookings (business-scoped) --------------------------------------
    def save_booking(self, booking, business_id=None):
        business_id = self._biz(business_id)
        with self._cur() as cur:
            cur.execute(
                """INSERT INTO bookings
                   (id, business_id, phone, name, date, time, party_size,
                    status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)""",
                (
                    booking["id"], business_id,
                    booking["phone"], booking["name"],
                    booking["date"], booking["time"],
                    booking["party_size"], _utcnow(),
                ),
            )

    def list_bookings(self, business_id=None, limit=100):
        business_id = self._biz(business_id)
        with self._cur() as cur:
            rows = cur.execute(
                "SELECT * FROM bookings WHERE business_id=?"
                " ORDER BY created_at DESC LIMIT ?",
                (business_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_bookings(self, business_id=None):
        business_id = self._biz(business_id)
        with self._cur() as cur:
            return cur.execute(
                "SELECT COUNT(*) AS n FROM bookings WHERE business_id=?",
                (business_id,),
            ).fetchone()["n"]

    # -- owner alerts (business-scoped) ----------------------------------
    def add_alert(self, phone, reason, business_id=None):
        business_id = self._biz(business_id)
        with self._cur() as cur:
            cur.execute(
                "INSERT INTO owner_alerts (business_id, phone, reason, handled, created_at)"
                " VALUES (?, ?, ?, 0, ?)",
                (business_id, phone, reason[:500], _utcnow()),
            )

    def list_alerts(self, business_id=None, limit=100):
        business_id = self._biz(business_id)
        with self._cur() as cur:
            rows = cur.execute(
                "SELECT * FROM owner_alerts WHERE business_id=?"
                " ORDER BY created_at DESC LIMIT ?",
                (business_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- message log ------------------------------------------------------
    def log_message(self, business_id, phone, direction):
        with self._cur() as cur:
            cur.execute(
                "INSERT INTO message_log (business_id, phone, direction, created_at)"
                " VALUES (?,?,?,?)",
                (business_id, phone, direction, _utcnow()),
            )

    def count_messages(self, business_id, direction=None):
        q = "SELECT COUNT(*) AS n FROM message_log WHERE business_id=?"
        args = [business_id]
        if direction:
            q += " AND direction=?"
            args.append(direction)
        with self._cur() as cur:
            return cur.execute(q, args).fetchone()["n"]
