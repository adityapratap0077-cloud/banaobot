"""TEMPORARY one-shot database-migration endpoints (Render PG -> Supabase).

Registered by server.py under /__mig/*. Every route requires the header
`X-Migrate-Token` matching the MIGRATE_TOKEN env var; without the env var
set, all routes return 404 (feature is inert in normal operation).

Routes:
  GET  /__mig/counts   -> {dialect, tables: {name: rows}, sequences: {...}}
  GET  /__mig/export   -> full JSON dump {tables: {name: {columns, rows}},
                                           sequences: {name: last_value}}
  POST /__mig/import   -> accepts the export JSON; truncates all tables,
                          inserts rows with FK checks deferred via
                          session_replication_role, restores sequences;
                          returns post-import counts.

DELETE THIS FILE (and its registration in server.py) once the migration
is verified. Added 2026-10-02 for the Render free-Postgres expiry move.
"""
import base64
import datetime
import decimal
import os

from flask import Blueprint, jsonify, request

import storage

bp = Blueprint("migrate_tmp", __name__)


def _authorized():
    token = os.environ.get("MIGRATE_TOKEN", "")
    if not token:
        return False
    return request.headers.get("X-Migrate-Token", "") == token


def _tables(cur):
    cur.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "ORDER BY tablename")
    return [r[0] for r in cur.fetchall()]


def _counts(cur, tables):
    out = {}
    for t in tables:
        cur.execute(f'SELECT count(*) FROM public."{t}"')
        out[t] = cur.fetchone()[0]
    return out


def _sequences(cur):
    cur.execute(
        "SELECT sequence_name FROM information_schema.sequences "
        "WHERE sequence_schema='public' ORDER BY sequence_name")
    out = {}
    for (name,) in cur.fetchall():
        cur.execute(f'SELECT last_value, is_called FROM public."{name}"')
        lv, ic = cur.fetchone()
        out[name] = {"last_value": lv, "is_called": ic}
    return out


def _enc(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return {"__t": "dt", "v": v.isoformat()}
    if isinstance(v, decimal.Decimal):
        return {"__t": "dec", "v": str(v)}
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"__t": "b64", "v": base64.b64encode(bytes(v)).decode()}
    if isinstance(v, (dict, list)):
        return {"__t": "json", "v": v}
    return str(v)


def _dec(v):
    if isinstance(v, dict) and "__t" in v:
        t = v["__t"]
        if t == "dt":
            return datetime.datetime.fromisoformat(v["v"])
        if t == "dec":
            return decimal.Decimal(v["v"])
        if t == "b64":
            return base64.b64decode(v["v"])
        if t == "json":
            from psycopg2.extras import Json
            return Json(v["v"])
    return v


@bp.route("/__mig/counts")
def counts():
    if not _authorized():
        return jsonify(error="not found"), 404
    if not storage.is_postgres():
        return jsonify(error="not postgres"), 501
    conn = storage.get_conn()
    try:
        cur = conn.cursor()
        tables = _tables(cur)
        return jsonify(dialect="postgres", tables=_counts(cur, tables),
                       sequences=_sequences(cur))
    finally:
        conn.close()


@bp.route("/__mig/export")
def export():
    if not _authorized():
        return jsonify(error="not found"), 404
    if not storage.is_postgres():
        return jsonify(error="not postgres"), 501
    conn = storage.get_conn()
    try:
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor()
        data = {"tables": {}, "sequences": _sequences(cur)}
        for t in _tables(cur):
            cur.execute(f'SELECT * FROM public."{t}"')
            cols = [d[0] for d in cur.description]
            rows = [[_enc(v) for v in row] for row in cur.fetchall()]
            data["tables"][t] = {"columns": cols, "rows": rows}
        return jsonify(data)
    finally:
        conn.close()


@bp.route("/__mig/import", methods=["POST"])
def import_():
    if not _authorized():
        return jsonify(error="not found"), 404
    if not storage.is_postgres():
        return jsonify(error="not postgres"), 501
    payload = request.get_json(force=True)
    conn = storage.get_conn()
    try:
        cur = conn.cursor()
        tables = _tables(cur)
        cur.execute("SET session_replication_role = 'replica'")
        if tables:
            cur.execute("TRUNCATE " + ", ".join(f'public."{t}"' for t in tables)
                        + " CASCADE")
        for t, spec in payload.get("tables", {}).items():
            if t not in tables:
                continue
            cols = spec["columns"]
            rows = spec["rows"]
            if not rows:
                continue
            col_sql = ", ".join(f'"{c}"' for c in cols)
            ph = ", ".join(["%s"] * len(cols))
            for row in rows:
                cur.execute(
                    f'INSERT INTO public."{t}" ({col_sql}) VALUES ({ph})',
                    [_dec(v) for v in row])
        for name, st in payload.get("sequences", {}).items():
            lv = int(st["last_value"])
            ic = bool(st["is_called"])
            cur.execute("SELECT setval(%s, %s, %s)",
                        (f'public."{name}"', lv, ic))
        cur.execute("SET session_replication_role = 'origin'")
        conn.commit()
        return jsonify(imported=True, tables=_counts(cur, tables),
                       sequences=_sequences(cur))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
