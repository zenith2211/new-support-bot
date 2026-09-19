"""
tests/storage.py — both storage backends, including the lost-update property.

    python -m tests.storage                  # JSON backend only
    DATABASE_URL=postgres://... python -m tests.storage

The Postgres checks are skipped without DATABASE_URL, and the exit code stays
0 — but the concurrency check is the whole reason this file exists, so run it
against a real database before trusting a serverless deploy.

Uses a throwaway table prefix and deletes it afterwards, so it is safe to
point at the same database the bot uses.
"""

import os
import sys
import threading

os.environ.setdefault("BOT_TOKEN", "123456:test-token-not-real")
os.environ.setdefault("ADMIN_IDS", "1")

FAILURES: list = []


def check(name: str, got, want):
    if got != want:
        FAILURES.append(f"{name}: got {got!r}, want {want!r}")


def ok(name: str, condition: bool, detail: str = ""):
    if not condition:
        FAILURES.append(f"{name}{': ' + detail if detail else ''}")


def exercise(backend, label: str):
    """Every backend must behave identically for the basics."""
    table = "t_probe"
    backend.ensure()

    check(f"{label}: empty table", backend.load(table), {})

    backend.put(table, "u1", {"balance": 5}, {"u1": {"balance": 5}})
    check(f"{label}: put then load", backend.load(table),
          {"u1": {"balance": 5}})

    # `stock` values are lists, not dicts — the schema must not assume objects.
    whole = {"u1": {"balance": 5}, "p1": ["line-a", "line-b"]}
    backend.put(table, "p1", ["line-a", "line-b"], whole)
    check(f"{label}: list record survives", backend.load(table).get("p1"),
          ["line-a", "line-b"])

    # mutate returning None must change nothing.
    def refuse(_record):
        return None

    backend.mutate(table, "u1", refuse, whole)
    check(f"{label}: refused mutate is a no-op",
          backend.load(table).get("u1"), {"balance": 5})

    def bump(record):
        record = dict(record or {})
        record["balance"] = record.get("balance", 0) + 10
        return record

    backend.mutate(table, "u1", bump, whole)
    check(f"{label}: mutate writes", backend.load(table).get("u1"),
          {"balance": 15})

    backend.delete(table, "p1", {"u1": {"balance": 15}})
    ok(f"{label}: delete removes the row",
       "p1" not in backend.load(table), str(backend.load(table)))

    backend.replace_all(table, {})
    check(f"{label}: replace_all clears", backend.load(table), {})


def concurrency(backend, label: str):
    """The property that matters: N concurrent credits must all land.

    A plain get/save loses updates here — each thread reads the same balance
    and writes back its own total, so the final figure is one increment, not
    N. mutate() takes a row lock, so every increment survives.
    """
    table = "t_probe_conc"
    threads = 8
    per_thread = 5
    backend.replace_all(table, {"w": {"balance": 0}})

    def add_one(record):
        record = dict(record or {})
        record["balance"] = float(record.get("balance") or 0) + 1
        return record

    def worker():
        for _ in range(per_thread):
            backend.mutate(table, "w", add_one, {})

    pool = [threading.Thread(target=worker) for _ in range(threads)]
    for thread in pool:
        thread.start()
    for thread in pool:
        thread.join()

    expected = threads * per_thread
    final = (backend.load(table).get("w") or {}).get("balance")
    check(f"{label}: no credits lost under {threads} threads", final,
          float(expected))
    backend.replace_all(table, {})


def table_registry():
    """store.TABLE_NAMES drives the migration tool. If a new Table is added
    and not listed, that table silently fails to migrate — so pin it."""
    from app import store
    declared = set(store.TABLE_NAMES)
    actual = {value.name for value in vars(store).values()
              if isinstance(value, store.Table)}
    ok("TABLE_NAMES lists every table", declared == actual,
       f"missing {actual - declared or '-'}, extra {declared - actual or '-'}")


def main() -> int:
    import tempfile
    from app import config

    # ── JSON backend ──────────────────────────────────────────
    config.DATA_DIR = tempfile.mkdtemp(prefix="storage-json-")
    from app import storage
    json_backend = storage.JsonBackend()
    exercise(json_backend, "json")
    concurrency(json_backend, "json")
    table_registry()
    print("  [     ok] json backend" if not FAILURES
          else f"  [FAIL x{len(FAILURES)}] json backend")

    # ── Postgres backend ──────────────────────────────────────
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        print("  [   skip] postgres backend (set DATABASE_URL to run)")
        print()
        print("The concurrency check on Postgres is the one that validates a")
        print("serverless deploy. Run it before trusting one.")
    else:
        before = len(FAILURES)
        try:
            pg = storage.PostgresBackend(dsn)
            exercise(pg, "postgres")
            concurrency(pg, "postgres")
        except Exception as exc:                 # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILURES.append(f"postgres: raised {type(exc).__name__}: {exc}")
        broke = len(FAILURES) - before
        print(f"  [{('FAIL x' + str(broke)) if broke else 'ok':>7}] "
              f"postgres backend")

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for problem in FAILURES:
            print(f"  - {problem}")
        return 1
    print("storage checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
