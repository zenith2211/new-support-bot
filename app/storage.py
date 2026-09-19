"""
app/storage.py — where records actually live.

Two backends behind one tiny interface:

  JsonBackend      one file per table under DATA_DIR. Zero setup, and what
                   you get when DATABASE_URL is unset. Single process only.
  PostgresBackend  one row per record. Survives restarts, redeploys and
                   ephemeral disks, and is the only option that works when
                   more than one process writes — i.e. anything serverless.

Why one row per record rather than one blob per table: two concurrent writers
saving a whole table would each write their own stale copy of it, so the later
write silently discards the earlier one. Per-record writes only collide when
two writers touch the *same* record, which is the narrow case `mutate()`
exists to make safe.

`mutate()` is the important primitive. Read-modify-write on a wallet balance
is a lost-update waiting to happen; on Postgres it runs as SELECT ... FOR
UPDATE inside a transaction, so concurrent credits queue instead of
overwriting each other. app/store.py routes every money path through it.
"""

import json
import logging
import os
import threading

from . import config

logger = logging.getLogger(__name__)


class JsonBackend:
    """One JSON file per table. Written atomically: tmp file + os.replace,
    so a crash mid-write cannot leave a half-written catalog."""

    kind = "json"
    # Whole-table writes, so a cached table is only safe with one writer.
    concurrent_safe = False

    def __init__(self):
        self._lock = threading.RLock()

    def _path(self, table: str) -> str:
        return os.path.join(config.DATA_DIR, f"{table}.json")

    def ensure(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)

    def load(self, table: str) -> dict:
        path = self._path(table)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError) as exc:
            logger.error("%s.json unreadable (%s) — starting empty",
                         table, exc)
            return {}

    def replace_all(self, table: str, data: dict):
        with self._lock:
            self.ensure()
            path = self._path(table)
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)

    # A file backend cannot write one record without rewriting the file, so
    # both of these fall back to a whole-table write. The caller passes the
    # full table because it already holds it in memory.
    def put(self, table: str, key: str, record, whole: dict):
        self.replace_all(table, whole)

    def delete(self, table: str, key: str, whole: dict):
        self.replace_all(table, whole)

    def mutate(self, table: str, key: str, fn, whole: dict | None = None):
        """Read-modify-write one record.

        Re-reads from disk rather than trusting the caller's copy, so this has
        the same contract as the Postgres version: mutate() is authoritative
        and never depends on how fresh a cache is. Costs one file read; worth
        it for having a single contract instead of two.
        """
        with self._lock:
            data = self.load(table)
            result = fn(data.get(key))
            if result is None:
                return None
            data[key] = result
            self.replace_all(table, data)
            return result


_SCHEMA = """
CREATE TABLE IF NOT EXISTS store_records (
    table_name TEXT        NOT NULL,
    record_id  TEXT        NOT NULL,
    data       JSONB       NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (table_name, record_id)
);
CREATE INDEX IF NOT EXISTS store_records_table
    ON store_records (table_name);
"""


class PostgresBackend:
    """One row per record, so concurrent writers do not clobber each other.

    Records are JSONB, which keeps every existing shape working untouched:
    users and orders are objects, `stock` values are arrays of strings.
    """

    kind = "postgres"
    concurrent_safe = True

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._lock = threading.RLock()
        self._ready = False
        try:
            import psycopg                       # noqa: PLC0415 - optional dep
            # Imported explicitly: psycopg.types.json happens to be reachable
            # from a bare `import psycopg` today, but that is incidental.
            from psycopg.types.json import Jsonb  # noqa: PLC0415
        except ImportError as exc:               # pragma: no cover
            raise RuntimeError(
                "DATABASE_URL is set but psycopg is not installed. "
                "Add 'psycopg[binary]' to requirements.txt."
            ) from exc
        self._psycopg = psycopg
        self._json = Jsonb

    def _connect(self):
        # A new connection per operation. Serverless invocations are short and
        # a pooler (Neon/Supabase pgbouncer) is the right place to keep these
        # warm — holding one open here would leak across cold starts.
        return self._psycopg.connect(self.dsn, autocommit=False)

    def ensure(self):
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(_SCHEMA)
                conn.commit()
            self._ready = True
            logger.info("postgres storage ready")

    def load(self, table: str) -> dict:
        self.ensure()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT record_id, data FROM store_records "
                    "WHERE table_name = %s", (table,))
                return {row[0]: row[1] for row in cur.fetchall()}

    def put(self, table: str, key: str, record, whole: dict | None = None):
        self.ensure()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO store_records (table_name, record_id, data) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (table_name, record_id) DO UPDATE "
                    "SET data = EXCLUDED.data, updated_at = now()",
                    (table, key, self._json(record)))
            conn.commit()

    def delete(self, table: str, key: str, whole: dict | None = None):
        self.ensure()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM store_records "
                    "WHERE table_name = %s AND record_id = %s", (table, key))
            conn.commit()

    def replace_all(self, table: str, data: dict):
        """Used by the JSON -> Postgres migration and by bulk clears."""
        self.ensure()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM store_records WHERE table_name = %s",
                            (table,))
                for key, record in data.items():
                    cur.execute(
                        "INSERT INTO store_records "
                        "(table_name, record_id, data) VALUES (%s, %s, %s)",
                        (table, str(key),
                         self._json(record)))
            conn.commit()

    def mutate(self, table: str, key: str, fn, whole: dict | None = None):
        """Read-modify-write one record without losing a concurrent update.

        SELECT ... FOR UPDATE takes a row lock for the life of the
        transaction, so two invocations crediting the same wallet queue up
        rather than both reading the old balance. `fn` returns the new record,
        or None to leave the row alone.
        """
        self.ensure()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data FROM store_records "
                    "WHERE table_name = %s AND record_id = %s FOR UPDATE",
                    (table, key))
                row = cur.fetchone()
                current = row[0] if row else None

                result = fn(current)
                if result is None:
                    conn.rollback()
                    return None

                cur.execute(
                    "INSERT INTO store_records (table_name, record_id, data) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (table_name, record_id) DO UPDATE "
                    "SET data = EXCLUDED.data, updated_at = now()",
                    (table, key, self._json(result)))
            conn.commit()
        return result


def build(dsn: str = ""):
    """Postgres when DATABASE_URL is set, otherwise JSON files."""
    dsn = dsn or config.DATABASE_URL
    if dsn:
        return PostgresBackend(dsn)
    return JsonBackend()
