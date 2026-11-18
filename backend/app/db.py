"""MySQL access with mysql-connector-python. Plain parameterised SQL, no ORM.

Every query uses %s placeholders, so values are sent separately from the SQL text and
user input is never pasted into a statement.
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import mysql.connector
from mysql.connector import pooling

from .config import get_settings

log = logging.getLogger("nutrimate.db")
SCHEMA = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
_pool: pooling.MySQLConnectionPool | None = None
_lock = threading.Lock()


def _conn_args(database: str | None = None) -> dict:
    s = get_settings()
    return dict(host=s.mysql_host, port=s.mysql_port, user=s.mysql_user, password=s.mysql_password,
                database=database or s.mysql_database, charset="utf8mb4", collation="utf8mb4_unicode_ci",
                autocommit=False)


def pool() -> pooling.MySQLConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            _pool = pooling.MySQLConnectionPool(pool_name="nutrimate", pool_size=get_settings().mysql_pool_size,
                                                pool_reset_session=True, **_conn_args())
    return _pool


def reset_pool() -> None:
    global _pool
    with _lock:
        _pool = None


def _fix(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            v = float(v)
        elif isinstance(v, (bytes, bytearray)):
            v = v.decode()
        out[k] = v
    return out


class Tx:
    """A connection with a dict cursor inside one transaction."""

    def __init__(self, con):
        self.con = con
        self.cur = con.cursor(dictionary=True)

    def all(self, sql: str, params: tuple | list | dict = ()) -> list[dict]:
        self.cur.execute(sql, params)
        return [_fix(r) for r in self.cur.fetchall()]

    def one(self, sql: str, params: tuple | list | dict = ()) -> dict | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def run(self, sql: str, params: tuple | list | dict = ()) -> int:
        """Execute a write. Returns lastrowid for inserts, else the affected row count."""
        self.cur.execute(sql, params)
        return self.cur.lastrowid or self.cur.rowcount

    def many(self, sql: str, rows: list) -> int:
        if not rows:
            return 0
        self.cur.executemany(sql, rows)
        return self.cur.rowcount


@contextmanager
def tx():
    con = pool().get_connection()
    t = Tx(con)
    try:
        yield t
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        t.cur.close()
        con.close()


def all_rows(sql: str, params=()) -> list[dict]:
    with tx() as t:
        return t.all(sql, params)


def one(sql: str, params=()) -> dict | None:
    with tx() as t:
        return t.one(sql, params)


def run(sql: str, params=()) -> int:
    with tx() as t:
        return t.run(sql, params)


def get_tx():
    """FastAPI dependency: one transaction per request."""
    with tx() as t:
        yield t


def dumps(obj) -> str:
    return json.dumps(obj, default=str)


def loads(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def init_schema(database: str | None = None) -> None:
    """Create all tables (idempotent)."""
    con = mysql.connector.connect(**_conn_args(database))
    cur = con.cursor()
    try:
        for stmt in SCHEMA.read_text(encoding="utf-8").split(";"):
            body = "\n".join(line for line in stmt.splitlines() if not line.strip().startswith("--")).strip()
            if body:
                cur.execute(body)
        con.commit()
    finally:
        cur.close()
        con.close()
