"""Postgres-compatibility tests for storage.py — runs on SQLite only.

Verifies the dual-dialect layer WITHOUT a live Postgres server:
  placeholder translation (? -> %s, literals untouched)
  DDL generation for both dialects (no SQLite-only syntax in PG mode)
  insert_returning_id on SQLite
  row -> dict normalization
  get_conn()/init_db() import surface + SQLite fallback when
  DATABASE_URL is unset

Usage: python3 test_postgres_compat.py
Exits non-zero on the first failure.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# These tests must never touch a real database server: make sure the
# Postgres path is not selected by accident.
os.environ.pop("DATABASE_URL", None)

import storage
from storage import Store

PASS = 0


def check(cond, label):
    global PASS
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    PASS += 1
    print(f"  ok: {label}")


# ------------------------------------------------- placeholder translation
print("== placeholder translation ==")
t = storage._translate_placeholders
check(t("SELECT * FROM users WHERE email=?") ==
      "SELECT * FROM users WHERE email=%s",
      "? becomes %s")
check(t("SELECT * FROM t WHERE a=? AND b=?") ==
      "SELECT * FROM t WHERE a=%s AND b=%s",
      "multiple placeholders all translate")
check(t("SELECT '?' AS q, 'it''s ? fine' FROM t WHERE a=?") ==
      "SELECT '?' AS q, 'it''s ? fine' FROM t WHERE a=%s",
      "? inside string literals (incl. '' escapes) is untouched")
check(t("UPDATE t SET a=?, b=? WHERE c=?", ) ==
      "UPDATE t SET a=%s, b=%s WHERE c=%s",
      "UPDATE placeholders translate")
check(t("no placeholders here") == "no placeholders here",
      "placeholder-free SQL is unchanged")

# ------------------------------------------------- DDL for both dialects
print("== DDL generation ==")
pg_ddl = storage._postgres_ddl()
check("AUTOINCREMENT" not in pg_ddl,
      "Postgres DDL has no AUTOINCREMENT")
check("BIGSERIAL PRIMARY KEY" in pg_ddl,
      "Postgres DDL uses BIGSERIAL PRIMARY KEY")
check("created_at TEXT NOT NULL" in pg_ddl
      and "updated_at TEXT NOT NULL" in pg_ddl,
      "Postgres DDL stores timestamps as TEXT")
check("INTEGER PRIMARY KEY AUTOINCREMENT" in storage.SCHEMA,
      "SQLite DDL is unchanged (still INTEGER PRIMARY KEY AUTOINCREMENT)")
check("CREATE TABLE IF NOT EXISTS" in pg_ddl
      and "CREATE INDEX IF NOT EXISTS" in pg_ddl,
      "IF NOT EXISTS survives the translation (valid in Postgres)")
check("ON DELETE CASCADE" in pg_ddl,
      "foreign-key cascades survive the translation")
# every BIGSERIAL table still has its plain counterpart count
check(pg_ddl.count("BIGSERIAL PRIMARY KEY") ==
      storage.SCHEMA.count("INTEGER PRIMARY KEY AUTOINCREMENT"),
      "one BIGSERIAL per AUTOINCREMENT table")

# ------------------------------------------------- get_conn / dialect
print("== get_conn / dialect ==")
conn = storage.get_conn(":memory:")
check(storage.dialect_of(conn) == "sqlite",
      "DATABASE_URL unset -> sqlite dialect")
check(not storage.is_postgres(), "is_postgres() is False without DATABASE_URL")
conn.close()

# ------------------------------------------------- execute() normalization
print("== execute() row normalization ==")
import sqlite3
raw = sqlite3.connect(":memory:")
cur = storage.execute(raw, "SELECT 1 AS one, 'x' AS two")
row = cur.fetchone()
check(row == {"one": 1, "two": "x"} and type(row) is dict,
      "fetchone returns a plain dict")
cur = storage.execute(raw, "SELECT 2 AS n UNION ALL SELECT 3 AS n")
rows = cur.fetchall()
check(rows == [{"n": 2}, {"n": 3}]
      and all(type(r) is dict for r in rows),
      "fetchall returns plain dicts")
cur = storage.execute(raw, "SELECT * FROM (SELECT 1 AS n) WHERE n=?", (99,))
check(cur.fetchone() is None, "fetchone is None on empty result")
raw.close()

# ------------------------------------------------- insert_returning_id
print("== insert_returning_id ==")
raw = sqlite3.connect(":memory:")
raw.execute("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " v TEXT)")
a = storage.insert_returning_id(raw, "INSERT INTO t (v) VALUES (?)", ("a",))
b = storage.insert_returning_id(raw, "INSERT INTO t (v) VALUES (?)", ("b",))
check((a, b) == (1, 2), "insert_returning_id returns 1, 2 on SQLite")
rows = storage.execute(raw, "SELECT id FROM t ORDER BY id").fetchall()
check([r["id"] for r in rows] == [1, 2],
      "rows actually landed with those ids")
raw.close()

# ------------------------------------------------- Store smoke on SQLite
print("== Store end-to-end on SQLite ==")
store = Store(":memory:")
uid = store.create_user("pg@test.local", "hash")
check(uid == 1, "create_user returns the new id")
check(store.create_user("pg@test.local", "hash") is None,
      "duplicate email -> None (IntegrityError path)")
check(store.get_user(uid)["email"] == "pg@test.local",
      "user round-trips after a rolled-back duplicate insert")
bid = store.create_bot(uid, "PG Bot", "You are a test bot.")
check(isinstance(bid, int) and bid >= 1, "create_bot returns the new id")
bot = store.get_bot(bid, uid)
check(bot["name"] == "PG Bot" and bot["share_token"],
      "bot round-trips with a share token")
check(isinstance(bot["created_at"], str) and "T" in bot["created_at"],
      "created_at is a UTC ISO-8601 string")
biz = store.create_business(uid, "PG Cafe", template_id="restaurant")
check(isinstance(biz, int), "create_business returns the new id")
cat = store.add_category(biz, "Drinks")
item = store.add_item(cat, "Cold brew", price=120)
faq = store.add_faq(biz, "hours", "hours, timing", "9-9", "9-9")
check(all(isinstance(x, int) for x in (cat, item, faq)),
      "add_category/add_item/add_faq return new ids")
menu = store.get_menu(biz)
check(menu[0]["items"][0]["name_en"] == "Cold brew",
      "menu round-trips through the new insert path")
store.save_session("+911234567890",
                   {"lang": "en", "state": "idle", "data": {}},
                   business_id=biz)
sess = store.get_session("+911234567890", business_id=biz)
check(sess is not None and sess["lang"] == "en",
      "session save/load works")
store.close()

# init_db import surface (python -c friendly)
check(callable(storage.init_db) and callable(storage.get_conn),
      "init_db and get_conn are importable")
s2 = storage.init_db(":memory:")
check(isinstance(s2, Store), "init_db returns a Store")
s2.close()

print(f"\nALL {PASS} POSTGRES-COMPAT CHECKS PASSED ✔")
